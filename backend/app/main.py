from __future__ import annotations

import asyncio
import hmac
import uuid
from copy import deepcopy
from pathlib import Path
from typing import Any, Literal

from fastapi import (
    Depends,
    FastAPI,
    Header,
    HTTPException,
    Query,
    Request,
    Response,
    WebSocket,
    WebSocketDisconnect,
)
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.exception_handlers import (
    http_exception_handler,
    request_validation_exception_handler,
)
from fastapi.exceptions import RequestValidationError
from pydantic import BaseModel, ConfigDict, Field

from agent.pool import AgentPool
from config import load_settings
from dm.engine import DMEngine
from game_service import GameService
from workflow import GameWorkflow
from runtime.contracts import RuntimeAccessError
from llm.factory import LLMFactory
from loader.script_loader import ScriptLoader
from paths import data_dir, frontend_dir, scripts_dir
from registry.mechanic_registry import MechanicRegistry
from registry.skill_registry import SkillRegistry
from security import LoginRateLimiter, MAX_REQUEST_BYTES, validate_script_payload
from skill.deduction import DeductionSkill
from skill.faction import FactionSkill
from skill.narrative import NarrativeSkill
from storage import AppStore
from script_catalog import BUILTIN_SCRIPT_IDS, ScriptCatalog
from script_workshop import ScriptWorkshop
from workflow_config import load_workflow_settings
from ws.handlers import (
    build_autonomy_activity,
    build_game_init,
    build_phase_messages,
    handle_client_message,
    handle_message,
)
from ws.lifecycle import await_with_heartbeat, heartbeat_message, send_connected
from ws.protocol import (
    ProtocolError,
    error_envelope,
    event_envelope,
    parse_command,
    resume_envelope,
    snapshot_envelope,
)


class Credentials(BaseModel):
    username: str
    password: str


class ScriptInspection(BaseModel):
    mode: str
    script: dict[str, Any] | None = None
    script_id: str | None = None


class GameCreation(BaseModel):
    category: str
    mode: str
    player_role_id: str
    script: dict[str, Any] | None = None
    script_id: str | None = None


class ScriptPublication(BaseModel):
    model_config = ConfigDict(extra="forbid")
    script: dict[str, Any]
    title: str = Field(min_length=1, max_length=120)
    tags: list[str] = Field(default_factory=list, max_length=12)


class GamePreparation(BaseModel):
    model_config = ConfigDict(extra="forbid")
    catalog_id: str = Field(min_length=1, max_length=128)
    version: str = Field(min_length=1, max_length=64)
    request_id: str = Field(default_factory=lambda: str(uuid.uuid4()), min_length=8, max_length=128)


class AuthoringRequest(BaseModel):
    model_config = ConfigDict(extra='forbid')
    mode: Literal['import','ai'] = 'import'
    request_id: str = Field(min_length=8,max_length=128)
    title: str = Field(min_length=1,max_length=120)
    tags: list[str] = Field(default_factory=list,max_length=12)
    topic: str = Field(default='',max_length=2000)
    script: dict[str,Any] | None = None
    catalog_id: str | None = None
    source_job_id: str | None = Field(default=None,max_length=128)


class GameActivation(BaseModel):
    model_config = ConfigDict(extra="forbid")
    player_role_id: str = Field(min_length=1, max_length=128)


def resolve_script(script: dict[str, Any] | None, script_id: str | None) -> dict[str, Any]:
    if (script is None) == (script_id is None):
        raise ValueError("必须且只能选择上传剧本或内置剧本")
    if script_id is not None:
        if script_id not in BUILTIN_SCRIPT_IDS:
            raise ValueError("未知的内置剧本")
        return ScriptLoader(scripts_dir()).load(script_id)
    validate_script_payload(script)
    return script


class NotebookUpdate(BaseModel):
    content: str


class UserSummary(BaseModel):
    id: int
    username: str


class AuthSessionResponse(BaseModel):
    user: UserSummary
    csrf_token: str


class MeResponse(UserSummary):
    csrf_token: str


class WebSocketTicketResponse(BaseModel):
    ticket: str
    expires_in: int


class OkResponse(BaseModel):
    ok: bool


class GameSummaryResponse(BaseModel):
    id: int
    title: str
    category: str
    mode: str
    player_role_id: str | None
    ai_agent_count: int
    current_stage: int
    current_phase: str
    total_stages: int
    status: str
    created_at: str
    updated_at: str
    lifecycle_version: int = 1
    catalog_script_id: str | None = None
    script_version: str | None = None
    run_id: str | None = None


class GameCreationResponse(GameSummaryResponse):
    orchestration: dict[str, Any]


class DomainEventResponse(BaseModel):
    type: str
    payload: dict[str, Any]
    created_at: str


class GameDetailResponse(GameSummaryResponse):
    events: list[DomainEventResponse]
    has_opening: bool = False
    before_first_stage: bool = False


class ScriptInspectionResponse(BaseModel):
    script_id: str
    title: str
    total_stages: int
    role_count: int
    ai_agent_count: int
    supported_modes: list[str]
    playable_roles: list[dict[str, Any]]
    story_background: str


class NotebookSaveResponse(BaseModel):
    content: str
    updated_at: str
    stage: int | None = None
    phase: str = "legacy_unknown"
    revision: int | None = None


class RealtimeEventResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    event_id: int
    request_id: str
    type: str
    payload: dict[str, Any]
    created_at: str


class RealtimeEventPage(BaseModel):
    items: list[RealtimeEventResponse]
    next_cursor: int
    has_more: bool


def build_dm() -> DMEngine:
    settings = load_settings()
    llm_factory = LLMFactory(
        {
            "provider": settings.llm_provider,
            "model": settings.llm_model,
            "base_url": settings.llm_base_url,
            "api_key": settings.llm_api_key,
            "timeout": settings.llm_timeout_seconds,
            "context_window": settings.llm_context_window,
            "input_limit": settings.llm_input_limit,
            "output_limit": settings.llm_output_limit,
            "safety_margin": settings.llm_safety_margin,
            "reasoning_effort": settings.llm_reasoning_effort,
        }
    )
    skills = SkillRegistry()
    for skill in (NarrativeSkill, DeductionSkill, FactionSkill):
        skills.register(skill)
    return DMEngine(
        ScriptLoader(scripts_dir()),
        AgentPool(),
        llm_factory,
        MechanicRegistry(),
        skills,
    )


def create_app(
    database_path: str | Path | None = None,
    *,
    allow_legacy_token_response: bool = False,
) -> FastAPI:
    settings = load_settings()
    application = FastAPI(title=settings.app_title)
    store = AppStore(database_path or data_dir() / "app.db")
    service = GameService(store, build_dm)
    login_user_limiter = LoginRateLimiter(max_attempts=5)
    login_ip_limiter = LoginRateLimiter(max_attempts=20)
    cookie_name = "__Host-ai_mm_session" if settings.cookie_secure else "ai_mm_session"
    application.state.store = store
    application.state.game_service = service
    application.state.cookie_name = cookie_name
    application.state.command_locks = {}
    application.state.active_connections = {}
    script_catalog = ScriptCatalog(store, service)
    workshop = ScriptWorkshop(script_catalog)
    application.state.script_workshop = workshop
    application.state.authoring_tasks = {}

    frontend = frontend_dir()
    application.mount("/static", StaticFiles(directory=frontend), name="static")

    @application.middleware("http")
    async def security_headers(request: Request, call_next: Any) -> Response:
        incoming_request_id = request.headers.get("X-Request-ID", "")
        request.state.request_id = (
            incoming_request_id
            if 8 <= len(incoming_request_id) <= 128
            else str(uuid.uuid4())
        )
        content_length = request.headers.get("content-length")
        if content_length:
            try:
                request_size = int(content_length)
            except ValueError:
                request_size = 0
            if request_size > MAX_REQUEST_BYTES:
                content = (
                    {
                        "code": "PAYLOAD_TOO_LARGE",
                        "message": "请求体不能超过 5 MB",
                        "request_id": request.state.request_id,
                        "details": {},
                    }
                    if request.url.path.startswith("/api/v1/")
                    else {"detail": "请求体不能超过 5 MB"}
                )
                response: Response = JSONResponse(
                    status_code=413,
                    content=content,
                )
            else:
                response = await call_next(request)
        else:
            response = await call_next(request)
        if request.url.path in {"/", "/login", "/register", "/play", "/scripts/new", "/personal-center"} or request.url.path.startswith(("/api/", "/cases", "/games/")):
            response.headers["Cache-Control"] = "no-store, private"
        elif request.url.path in {"/static/app.js", "/static/styles.css"}:
            response.headers["Cache-Control"] = "no-cache"
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "no-referrer"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Content-Security-Policy"] = (
            "default-src 'self'; script-src 'self'; style-src 'self'; "
            "img-src 'self' data:; connect-src 'self' ws: wss:; "
            "object-src 'none'; base-uri 'self'; frame-ancestors 'none'"
        )
        response.headers["X-Request-ID"] = request.state.request_id
        return response

    @application.exception_handler(HTTPException)
    async def api_http_exception(request: Request, exc: HTTPException) -> Response:
        if not request.url.path.startswith("/api/v1/"):
            return await http_exception_handler(request, exc)
        code_by_status = {
            400: "VALIDATION_ERROR",
            401: "AUTH_REQUIRED",
            403: "FORBIDDEN",
            404: "RESOURCE_NOT_FOUND",
            409: "CONFLICT",
            413: "PAYLOAD_TOO_LARGE",
            429: "RATE_LIMITED",
        }
        return JSONResponse(
            status_code=exc.status_code,
            headers=exc.headers,
            content={
                "code": code_by_status.get(exc.status_code, "REQUEST_FAILED"),
                "message": str(exc.detail),
                "request_id": request.state.request_id,
                "details": {},
            },
        )

    @application.exception_handler(RequestValidationError)
    async def api_validation_exception(
        request: Request,
        exc: RequestValidationError,
    ) -> Response:
        if not request.url.path.startswith("/api/v1/"):
            return await request_validation_exception_handler(request, exc)
        return JSONResponse(
            status_code=422,
            content={
                "code": "VALIDATION_ERROR",
                "message": "请求参数格式无效",
                "request_id": request.state.request_id,
                "details": {"errors": exc.errors()},
            },
        )

    def require_user(
        request: Request,
        authorization: str | None = Header(default=None),
        x_csrf_token: str | None = Header(default=None),
    ) -> dict[str, Any]:
        bearer_token = _bearer_token(authorization) if allow_legacy_token_response else None
        token = bearer_token or request.cookies.get(cookie_name)
        user = store.user_for_token(token)
        if user is None:
            raise HTTPException(status_code=401, detail="请先登录")
        if (
            bearer_token is None
            and request.method not in {"GET", "HEAD", "OPTIONS"}
            and (
                not x_csrf_token
                or not hmac.compare_digest(x_csrf_token, user["csrf_token"])
            )
        ):
            raise HTTPException(status_code=403, detail="CSRF 校验失败")
        return {**user, "token": token, "auth_source": "bearer" if bearer_token else "cookie"}

    def issue_session_response(response: Response, session: dict[str, Any]) -> dict[str, Any]:
        response.set_cookie(
            key=cookie_name,
            value=session["token"],
            max_age=30 * 24 * 60 * 60,
            httponly=True,
            secure=settings.cookie_secure,
            samesite="lax",
            path="/",
        )
        payload = {
            "user": session["user"],
            "csrf_token": session["csrf_token"],
        }
        if allow_legacy_token_response:
            payload["token"] = session["token"]
        return payload

    def clear_session_cookie(response: Response) -> None:
        response.delete_cookie(
            key=cookie_name,
            httponly=True,
            secure=settings.cookie_secure,
            samesite="lax",
            path="/",
        )

    @application.get("/health")
    async def health() -> dict[str, str]:
        return {"status": "ok"}

    @application.get("/")
    @application.get("/login")
    @application.get("/register")
    async def desktop_ui() -> FileResponse:
        return FileResponse(frontend / "index.html")

    @application.get("/cases")
    @application.get("/cases/{case_path:path}")
    @application.get("/play")
    @application.get("/scripts/new")
    @application.get("/personal-center")
    @application.get("/games/{case_path:path}")
    async def desktop_case_route(case_path: str = "") -> FileResponse:
        return FileResponse(frontend / "index.html")

    @application.post("/api/auth/register")
    @application.post("/api/v1/auth/register", response_model=AuthSessionResponse)
    async def register(body: Credentials, response: Response) -> dict[str, Any]:
        try:
            return issue_session_response(
                response,
                store.register(body.username, body.password),
            )
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @application.post("/api/auth/login")
    @application.post("/api/v1/auth/login", response_model=AuthSessionResponse)
    async def login(body: Credentials, request: Request, response: Response) -> dict[str, Any]:
        client_host = request.client.host if request.client else "unknown"
        username_key = f"user:{body.username.strip().casefold()}"
        ip_key = f"ip:{client_host}"
        retry_after = max(
            login_user_limiter.retry_after([username_key]),
            login_ip_limiter.retry_after([ip_key]),
        )
        if retry_after:
            raise HTTPException(
                status_code=429,
                detail="登录尝试过于频繁，请稍后重试",
                headers={"Retry-After": str(retry_after)},
            )
        try:
            session = store.login(body.username, body.password)
        except ValueError as exc:
            login_user_limiter.record_failure([username_key])
            login_ip_limiter.record_failure([ip_key])
            raise HTTPException(status_code=401, detail=str(exc)) from exc
        login_user_limiter.clear(username_key)
        return issue_session_response(response, session)

    @application.get("/api/me")
    @application.get("/api/v1/me", response_model=MeResponse)
    async def me(user: dict[str, Any] = Depends(require_user)) -> dict[str, Any]:
        return {
            "id": user["id"],
            "username": user["username"],
            "csrf_token": user["csrf_token"],
        }

    @application.post("/api/auth/logout")
    @application.post("/api/v1/auth/logout", response_model=OkResponse)
    async def logout(
        response: Response,
        user: dict[str, Any] = Depends(require_user),
    ) -> dict[str, bool]:
        store.logout(user["token"])
        clear_session_cookie(response)
        return {"ok": True}

    @application.post("/api/games/{game_id}/ws-ticket")
    @application.post(
        "/api/v1/games/{game_id}/ws-ticket",
        response_model=WebSocketTicketResponse,
    )
    async def websocket_ticket(
        game_id: int,
        controller_id: str = Query(default='', max_length=64),
        user: dict[str, Any] = Depends(require_user),
    ) -> dict[str, Any]:
        try:
            ticket = store.create_websocket_ticket(
                user["id"],
                game_id,
                user["session_key"],
                controller_id=controller_id,
            )
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        return {"ticket": ticket, "expires_in": 30}

    @application.get(
        "/api/v1/games/{game_id}/events",
        response_model=RealtimeEventPage,
    )
    async def realtime_events(
        game_id: int,
        after_event_id: int = Query(default=0, ge=0),
        limit: int = Query(default=100, ge=1, le=100),
        user: dict[str, Any] = Depends(require_user),
    ) -> dict[str, Any]:
        try:
            rows = store.list_realtime_events(
                user["id"],
                game_id,
                after_event_id,
                limit + 1,
            )
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        has_more = len(rows) > limit
        items = rows[:limit]
        return {
            "items": items,
            "next_cursor": (
                int(items[-1]["event_id"])
                if items
                else after_event_id
            ),
            "has_more": has_more,
        }

    @application.get("/api/catalog")
    @application.get("/api/v1/catalog")
    async def catalog(user: dict[str, Any] = Depends(require_user)) -> dict[str, Any]:
        return {
            "categories": [
                {"id": "mystery", "name": "悬疑推理", "description": "线索、秘密与真相还原"},
            ],
            "modes": [
                {"id": "deduction", "name": "推理对抗", "description": "允许隐瞒与角色博弈"},
            ],
        }

    @application.post("/api/scripts/inspect")
    @application.post(
        "/api/v1/scripts/inspect",
        response_model=ScriptInspectionResponse,
    )
    async def inspect_script(
        body: ScriptInspection,
        user: dict[str, Any] = Depends(require_user),
    ) -> dict[str, Any]:
        try:
            script = resolve_script(body.script, body.script_id)
            return service.inspect_script(script, body.mode)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @application.get("/api/scripts/example")
    @application.get("/api/v1/scripts/example", response_model=ScriptInspectionResponse)
    async def example_script(user: dict[str, Any] = Depends(require_user)) -> dict[str, Any]:
        return service.inspect_script(ScriptLoader(scripts_dir()).load("fog_harbor_clocktower"), "deduction")

    @application.get("/api/v1/scripts/schema")
    async def script_schema(user: dict[str, Any] = Depends(require_user)) -> dict[str, Any]:
        return ScriptLoader.json_schema()

    @application.get("/api/v1/scripts")
    async def list_scripts(q: str = Query(default="", max_length=120), user: dict[str, Any] = Depends(require_user)) -> list[dict[str, Any]]:
        return script_catalog.list(user["id"], q)

    @application.post("/api/v1/scripts", status_code=201)
    async def publish_script(body: ScriptPublication, user: dict[str, Any] = Depends(require_user)) -> dict[str, Any]:
        try:
            return script_catalog.publish(user["id"], body.script, body.title, body.tags)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @application.post("/api/v1/game-preparations", status_code=201, response_model=GameSummaryResponse)
    async def prepare_game(body: GamePreparation, user: dict[str, Any] = Depends(require_user)) -> dict[str, Any]:
        try:
            existing = store.find_preparation_request(user["id"], body.request_id, body.catalog_id, body.version)
            if existing is not None:
                return existing
            item = script_catalog.resolve(user["id"], body.catalog_id, body.version)
            service.inspect_script(item["script"], "deduction")
            return store.prepare_game(user["id"], item["script"], item["catalog_id"], item["version"], body.request_id,
                                      workflow_config=load_workflow_settings().model_dump())
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc

    @application.post('/api/v1/authoring-jobs',status_code=202)
    async def authoring_job(body: AuthoringRequest,user: dict[str,Any]=Depends(require_user)):
        if (body.mode=='import' and body.script is None) or (body.mode=='ai' and not body.topic.strip()):
            raise HTTPException(status_code=400,detail='请提供剧本文件或创作主题')
        try:
            job,created = workshop.create(user['id'],body.request_id,body.mode,
                {'title':body.title,'tags':body.tags,'topic':body.topic,'script':body.script,
                 'source_job_id':body.source_job_id},body.catalog_id)
            if created:
                task = asyncio.create_task(workshop.execute(user['id'],job['job_id']))
                application.state.authoring_tasks[job['job_id']] = task
                task.add_done_callback(lambda completed: application.state.authoring_tasks.pop(job['job_id'],None))
            return job
        except KeyError as exc:
            raise HTTPException(status_code=404,detail=str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(status_code=409,detail=str(exc)) from exc

    @application.get('/api/v1/authoring-jobs/{job_id}')
    async def read_authoring_job(job_id: str,user: dict[str,Any]=Depends(require_user)):
        try: return workshop.job(user['id'],job_id)
        except KeyError as exc: raise HTTPException(status_code=404,detail=str(exc)) from exc

    @application.post('/api/v1/authoring-jobs/{job_id}/publish',status_code=201)
    async def publish_authoring_job(job_id: str,user: dict[str,Any]=Depends(require_user)):
        try: return workshop.publish(user['id'],job_id)
        except KeyError as exc: raise HTTPException(status_code=404,detail=str(exc)) from exc
        except ValueError as exc: raise HTTPException(status_code=409,detail=str(exc)) from exc

    @application.post('/api/v1/authoring-jobs/{job_id}/cancel')
    async def cancel_authoring_job(job_id: str,user: dict[str,Any]=Depends(require_user)):
        try:
            workshop.cancel(user['id'],job_id)
            task=application.state.authoring_tasks.get(job_id)
            if task is not None:
                task.cancel();await asyncio.gather(task,return_exceptions=True)
            return workshop.job(user['id'],job_id)
        except KeyError as exc:raise HTTPException(status_code=404,detail=str(exc)) from exc
        except ValueError as exc:raise HTTPException(status_code=409,detail=str(exc)) from exc

    @application.get('/api/v1/scripts/{catalog_id}/edit')
    async def script_edit_data(catalog_id: str,user: dict[str,Any]=Depends(require_user)):
        try:
            item = script_catalog.resolve(user['id'],catalog_id)
            if item['source']!='imported': raise KeyError('只能编辑自己的剧本')
            return {'script':item['script'],'versions':workshop.revisions(user['id'],catalog_id),
                    'source_job_id':workshop.source_job_for_catalog(user['id'],catalog_id)}
        except KeyError as exc: raise HTTPException(status_code=404,detail=str(exc)) from exc

    @application.get("/api/v1/games/{game_id}/preparation")
    async def game_preparation(game_id: int, user: dict[str, Any] = Depends(require_user)) -> dict[str, Any]:
        try:
            game = store.get_game(user["id"], game_id, include_script=True)
            opening = game["script"].get("opening")
            return {"game": service._public_game(game), "script": service.inspect_script(game["script"], game["mode"]),
                    "tags": game["script"]["script_meta"].get("tags", []),
                    "opening": {"title": opening["title"], "content": opening["content"]} if opening else None}
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    @application.post("/api/v1/games/{game_id}/activate", response_model=GameSummaryResponse)
    async def activate_game(game_id: int, body: GameActivation, user: dict[str, Any] = Depends(require_user)) -> dict[str, Any]:
        lock = application.state.command_locks.setdefault(game_id, asyncio.Lock())
        try:
            async with lock:
                return await service.activate_game(user["id"], game_id, body.player_role_id)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc

    @application.post("/api/v1/games/{game_id}/pause", response_model=GameSummaryResponse)
    async def pause_game(game_id: int, user: dict[str, Any] = Depends(require_user)) -> dict[str, Any]:
        lock = application.state.command_locks.setdefault(game_id, asyncio.Lock())
        try:
            async with lock:
                game = service.pause_game(user["id"], game_id)
            active = application.state.active_connections.get(game_id)
            if active is not None:
                await active.close(code=1000, reason="游戏已暂停")
            return game
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    @application.post("/api/games")
    @application.post("/api/v1/games", response_model=GameCreationResponse)
    async def create_game(
        body: GameCreation,
        user: dict[str, Any] = Depends(require_user),
    ) -> dict[str, Any]:
        try:
            script = resolve_script(body.script, body.script_id)
            return await service.create_game(
                user["id"], script, body.category, body.mode, body.player_role_id
            )
        except (KeyError, ValueError) as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @application.get("/api/games")
    @application.get(
        "/api/v1/games",
        response_model=list[GameSummaryResponse],
    )
    async def list_games(user: dict[str, Any] = Depends(require_user)) -> list[dict[str, Any]]:
        return store.list_games(user["id"])

    @application.get("/api/games/{game_id}")
    @application.get(
        "/api/v1/games/{game_id}",
        response_model=GameDetailResponse,
    )
    async def game_detail(game_id: int, user: dict[str, Any] = Depends(require_user)) -> dict[str, Any]:
        try:
            game = store.get_game(user["id"], game_id, include_script=True)
            has_opening = bool(game["script"].get("opening"))
            return {**service._public_game(game), "events": store.list_events(user["id"], game_id),
                    "has_opening": has_opening,
                    "before_first_stage": has_opening and game["current_stage"] == 1
                    and game["current_phase"] in {"opening", "private_reveal"}}
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    @application.delete("/api/games/{game_id}")
    @application.delete(
        "/api/v1/games/{game_id}",
        response_model=OkResponse,
    )
    async def delete_game(
        game_id: int,
        user: dict[str, Any] = Depends(require_user),
    ) -> dict[str, bool]:
        try:
            service.delete_game(user["id"], game_id)
            return {"ok": True}
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    @application.get("/api/games/{game_id}/notebook")
    @application.get("/api/v1/games/{game_id}/notebook")
    async def player_notebook(
        game_id: int,
        user: dict[str, Any] = Depends(require_user),
    ) -> dict[str, Any]:
        try:
            return service.get_player_notebook(user["id"], game_id)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc

    @application.put("/api/games/{game_id}/notebook/manual")
    @application.put(
        "/api/v1/games/{game_id}/notebook/manual",
        response_model=NotebookSaveResponse,
    )
    async def save_player_notebook(
        game_id: int,
        body: NotebookUpdate,
        user: dict[str, Any] = Depends(require_user),
    ) -> dict[str, Any]:
        if len(body.content) > 10_000:
            raise HTTPException(status_code=400, detail="推理手记不能超过 10000 个字符")
        try:
            return service.save_player_manual_notes(
                user["id"],
                game_id,
                body.content,
            )
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc

    @application.get("/api/games/{game_id}/role-records")
    @application.get("/api/v1/games/{game_id}/role-records")
    async def role_records(
        game_id: int,
        user: dict[str, Any] = Depends(require_user),
    ) -> dict[str, Any]:
        try:
            return service.get_role_records(user["id"], game_id)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc

    @application.get("/api/v1/games/{game_id}/execution-logs")
    async def execution_logs(game_id: int, user: dict[str, Any] = Depends(require_user)) -> dict[str, Any]:
        try:
            return service.runtime_store.logs(user["id"], game_id)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    @application.post('/api/v1/games/{game_id}/takeover')
    async def takeover_game(game_id: int, user: dict[str, Any] = Depends(require_user)):
        try:
            game = service.leases.invalidate(user['id'],game_id)
            service.sessions.pop(game_id,None)
            active = application.state.active_connections.get(game_id)
            if active is not None:
                await active.close(code=4409,reason='游戏已被另一个窗口接管')
            return game
        except KeyError as exc:
            raise HTTPException(status_code=404,detail=str(exc)) from exc

    @application.post('/api/v1/games/{game_id}/cancel-preparation')
    async def cancel_preparation(game_id: int,user: dict[str,Any]=Depends(require_user)):
        try:
            with store.transaction():
                game=store.get_game(user['id'],game_id)
                if game['status']=='preparing':
                    store.set_game_lifecycle(game_id,paused_at=None,status='abandoned')
                    store.add_event(game_id,'preparation_cancelled',{})
                elif game['status']!='abandoned':
                    raise HTTPException(status_code=409,detail='已开始的游戏不能取消选角')
            return store.get_game(user['id'],game_id)
        except KeyError as exc:raise HTTPException(status_code=404,detail=str(exc)) from exc

    @application.get('/api/v1/games/{game_id}/execution-log-pages')
    async def execution_log_pages(game_id: int,kind: Literal['models','tools','runs']='tools',actor_role_id: str='',
                                  offset: int=Query(default=0,ge=0),limit: int=Query(default=30,ge=1,le=100),user: dict[str,Any]=Depends(require_user)):
        try: return service.runtime_store.log_page(user['id'],game_id,kind,actor_role_id,offset,limit)
        except KeyError as exc: raise HTTPException(status_code=404,detail=str(exc)) from exc

    @application.get('/api/v1/games/{game_id}/export')
    async def export_game(game_id: int,user: dict[str,Any]=Depends(require_user)):
        try:
            game = store.get_game(user['id'],game_id)
            records = service.get_role_records(user['id'],game_id) if game['status']=='completed' else service.get_player_notebook(user['id'],game_id)
            logs = service.runtime_store.logs(user['id'],game_id)
            return JSONResponse({'schema_version':'1.0','game':game,'records':records,'execution':logs},
                headers={'Content-Disposition':f'attachment; filename="game-{game_id}.json"'})
        except KeyError as exc: raise HTTPException(status_code=404,detail=str(exc)) from exc
        except ValueError as exc: raise HTTPException(status_code=409,detail=str(exc)) from exc

    async def run_game_websocket(
        ws: WebSocket,
        user: dict[str, Any],
        game_id: int,
        *,
        protocol_v1: bool = False,
        after_event_id: int = 0,
    ) -> None:
        try:
            _, dm = await service.get_engine(user["id"], game_id)
        except KeyError:
            await ws.close(code=4404, reason="游戏记录不存在")
            return
        except ValueError:
            await ws.close(code=4409, reason="游戏存档无法恢复，请检查存档版本")
            return

        await ws.accept()
        command_lock = application.state.command_locks.setdefault(game_id, asyncio.Lock())
        await await_with_heartbeat(ws, command_lock.acquire(), game_id, protocol_v1)
        try:
            if dm.workflow_enabled and dm.workflow_settings.model_hosting and dm.state.scene_phase.value in {'briefing','dm_hosting'}:
                await GameWorkflow(service,user['id'],dm).dispatch(f'hosting:{dm.state.current_stage_num}:{dm.state.scene_phase.value}',{'type':'hosting_tick'})
            game_init = build_game_init(
                dm,
                history_events=store.list_events(user["id"], game_id),
            )
            initial_phase_messages: list[dict[str, Any]] = []
            if dm.uses_scene_flow():
                initial_phase_messages = build_phase_messages(dm)
                service.persist_engine_events(game_id, dm)
            latest_event_id = store.latest_realtime_event_id(game_id)
        finally:
            command_lock.release()
        if protocol_v1:
            if after_event_id > 0 and after_event_id <= latest_event_id:
                cursor = after_event_id
                while True:
                    pending_events = store.list_realtime_events(user["id"], game_id, cursor, 200)
                    if pending_events:
                        cursor = int(pending_events[-1]["event_id"])
                    await send_connected(ws, resume_envelope(game_id, cursor, pending_events))
                    if cursor >= latest_event_id or not pending_events:
                        break
                await send_connected(ws, snapshot_envelope(game_id, latest_event_id, game_init, initial_phase_messages))
            else:
                await send_connected(ws,
                    snapshot_envelope(
                        game_id,
                        latest_event_id,
                        game_init,
                        initial_phase_messages,
                    )
                )
        else:
            await send_connected(ws, game_init)
            for response in initial_phase_messages:
                await send_connected(ws, response)
                if response.get("type") == "dm_narration_chunk":
                    await asyncio.sleep(0.035)
        last_sent_event_id = latest_event_id if protocol_v1 else 0
        try:
            while True:
                if not store.session_is_active(user["session_key"]):
                    await ws.close(code=4401, reason="登录状态已失效")
                    return
                if protocol_v1:
                    for event in store.list_realtime_events(user["id"], game_id, last_sent_event_id, 200):
                        await send_connected(ws, event_envelope(game_id, event))
                        last_sent_event_id = int(event["event_id"])
                phase_remaining = dm.investigation_seconds_remaining()
                autonomy_remaining = dm.autonomy_seconds_until_next()
                deadlines = [
                    value
                    for value in (phase_remaining, autonomy_remaining)
                    if value is not None
                ]
                timeout = max(0.05, float(min([*deadlines, 5.0])))
                internal_message = False
                prefix_responses: list[dict[str, Any]] = []
                try:
                    message = await asyncio.wait_for(
                        ws.receive_json(),
                        timeout=timeout,
                    )
                except TimeoutError:
                    if not store.session_is_active(user["session_key"]):
                        await ws.close(code=4401, reason="登录状态已失效")
                        return
                    current_phase_remaining = dm.investigation_seconds_remaining()
                    if (
                        current_phase_remaining is not None
                        and current_phase_remaining <= 0
                    ):
                        message = {"type": "phase_timeout"}
                    else:
                        activity = build_autonomy_activity(dm)
                        if activity is None:
                            await send_connected(ws, heartbeat_message(game_id, protocol_v1))
                            continue
                        prefix_responses.append(activity)
                        message = {"type": "autonomy_tick"}
                    internal_message = True
                request_id = f"server:{uuid.uuid4()}" if internal_message else None
                if protocol_v1 and not internal_message:
                    try:
                        envelope, message = parse_command(message, game_id)
                        request_id = envelope.request_id
                    except ProtocolError as exc:
                        await send_connected(ws,
                            error_envelope(
                                game_id,
                                exc.code,
                                str(exc),
                                exc.request_id,
                            )
                        )
                        continue
                try:
                    streamed_event_ids: set[int] = set()
                    async with command_lock:
                        if store.get_game(user["id"], game_id)["status"] == "paused":
                            raise ValueError("游戏已暂停")
                        existing_events = (
                            store.realtime_events_for_request(
                                game_id,
                                str(request_id),
                            )
                            if protocol_v1 and request_id
                            else []
                        )
                        if dm.workflow_enabled:
                            async def stream_committed():
                                nonlocal last_sent_event_id
                                if protocol_v1:
                                    for event in store.list_realtime_events(user['id'],game_id,last_sent_event_id,200):
                                        await send_connected(ws,event_envelope(game_id,event))
                                        last_sent_event_id=int(event['event_id'])
                                        streamed_event_ids.add(last_sent_event_id)
                            async def stream_activity(payload):
                                envelope = heartbeat_message(game_id,protocol_v1)
                                if protocol_v1:
                                    envelope.update(type=payload['type'],request_id=request_id,payload=payload)
                                else:
                                    envelope=payload
                                await send_connected(ws,envelope)
                            responses = await await_with_heartbeat(ws,
                                GameWorkflow(service, user["id"], dm).dispatch(str(request_id or uuid.uuid4()), message,activity_sink=stream_activity),
                                game_id, protocol_v1,on_tick=stream_committed if protocol_v1 else None)
                            realtime_events = store.realtime_events_for_request(game_id, str(request_id)) if protocol_v1 and request_id else []
                        elif existing_events:
                            realtime_events = existing_events
                            responses = []
                        else:
                            before = dm.export_runtime_snapshot()
                            pending_before = deepcopy(dm._require_state().persistence_events)
                            try:
                                handled = await await_with_heartbeat(ws, (
                                    handle_message(dm, message)
                                    if internal_message
                                    else handle_client_message(dm, message)
                                ), game_id, protocol_v1)
                                responses = [*prefix_responses, *handled]
                                with store.transaction():
                                    service.record_responses(game_id, dm, responses)
                                    realtime_events = (
                                        store.record_realtime_events(game_id, str(request_id), responses)
                                        if protocol_v1 and request_id else []
                                    )
                            except BaseException:
                                dm.restore_runtime_snapshot(before)
                                dm._require_state().persistence_events = pending_before
                                raise
                except WebSocketDisconnect:
                    raise
                except Exception as exc:
                    responses = [
                        {
                            "type": "error",
                            "code": "WS_COMMAND_FAILED",
                            "message": str(exc),
                        }
                    ]
                    realtime_events = (
                        store.record_realtime_events(
                            game_id,
                            str(request_id),
                            responses,
                        )
                        if protocol_v1 and request_id
                        else []
                    )
                if protocol_v1:
                    for event in realtime_events:
                        if int(event['event_id']) in streamed_event_ids:
                            continue
                        await send_connected(ws, event_envelope(game_id, event))
                        last_sent_event_id = max(last_sent_event_id, int(event["event_id"]))
                        if event["type"] == "dm_narration_chunk":
                            await asyncio.sleep(0.035)
                else:
                    for response in responses:
                        await send_connected(ws, response)
                        if response.get("type") == "dm_narration_chunk":
                            await asyncio.sleep(0.035)
        except WebSocketDisconnect:
            return

    async def serve_game_websocket(ws: WebSocket, user: dict[str, Any], game_id: int,
                                   *, protocol_v1: bool = False, after_event_id: int = 0) -> None:
        try:
            game = store.get_game(user["id"], game_id)
        except KeyError:
            await ws.close(code=4404, reason="游戏记录不存在")
            return
        if game.get("lifecycle_version", 1) < 2:
            await run_game_websocket(ws, user, game_id, protocol_v1=protocol_v1, after_event_id=after_event_id)
            return
        if game["status"] == "preparing":
            await ws.close(code=4409, reason="请先选择角色")
            return
        # Only one connection may advance a new-version game's runtime at a time.
        if game_id in application.state.active_connections:
            await ws.close(code=4409, reason="本场游戏正在另一个窗口运行")
            return
        controller = user.get('controller_id') or 'legacy:'+user['session_key']
        settings_for_lease = service.workflow_defaults
        from workflow_config import WorkflowSettings
        full_game = store.get_game(user['id'],game_id,include_script=True)
        if full_game.get('workflow_config_json'):
            settings_for_lease = WorkflowSettings.model_validate_json(full_game['workflow_config_json'])
        try:
            service.leases.claim(user['id'],game_id,controller,settings_for_lease)
            service.sessions.pop(game_id,None)
        except RuntimeAccessError:
            await ws.close(code=4409,reason='本场游戏正在另一个窗口运行，或处于重连保留期')
            return
        application.state.active_connections[game_id] = ws
        async def pulse():
            while True:
                await asyncio.sleep(settings_for_lease.heartbeat_seconds)
                try:
                    service.leases.heartbeat(game_id,settings_for_lease)
                except RuntimeAccessError:
                    await ws.close(code=4409,reason='本场游戏已暂停或被接管')
                    return
        heartbeat_task = asyncio.create_task(pulse())
        try:
            await run_game_websocket(ws, user, game_id, protocol_v1=protocol_v1, after_event_id=after_event_id)
        finally:
            heartbeat_task.cancel()
            lock = application.state.command_locks.setdefault(game_id, asyncio.Lock())
            async with lock:
                try:
                    if service.leases.owned(game_id):
                        service.pause_game(user["id"], game_id)
                        service.leases.release(game_id,settings_for_lease)
                except KeyError:
                    pass
                application.state.active_connections.pop(game_id, None)
                service.sessions.pop(game_id, None)

    @application.websocket("/ws/v1/games/{game_id}")
    async def game_ws(
        ws: WebSocket,
        game_id: int,
        ticket: str = Query(default=""),
        after_event_id: int = Query(default=0, ge=0),
    ) -> None:
        ticket_user = store.consume_websocket_ticket(ticket, game_id)
        if ticket_user is None:
            await ws.close(code=4401, reason="连接票据无效或已过期")
            return
        user = {
            "id": ticket_user["user_id"],
            "username": ticket_user["username"],
            "session_key": ticket_user["session_key"],
            "controller_id": ticket_user['controller_id'],
        }
        await serve_game_websocket(
            ws,
            user,
            game_id,
            protocol_v1=True,
            after_event_id=after_event_id,
        )

    if allow_legacy_token_response:

        @application.websocket("/game")
        async def legacy_game_ws(
            ws: WebSocket,
            token: str = Query(default=""),
            game_id: int = Query(),
        ) -> None:
            user = store.user_for_token(token)
            if user is None:
                await ws.close(code=4401, reason="请先登录")
                return
            await serve_game_websocket(ws, user, game_id)

    return application


def _bearer_token(authorization: str | None) -> str | None:
    if not authorization or not authorization.startswith("Bearer "):
        return None
    return authorization.removeprefix("Bearer ").strip()


app = create_app()
