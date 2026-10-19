from __future__ import annotations

import os
import sys
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv


from paths import data_dir
ENV_FILE = Path(os.environ['AI_MURDER_MYSTERY_ENV_FILE']) if os.environ.get('AI_MURDER_MYSTERY_ENV_FILE') else (
    data_dir()/'config'/'.env' if getattr(sys,'frozen',False) else Path(__file__).resolve().parents[1]/'config'/'.env')


@dataclass(frozen=True)
class AppSettings:
    app_title: str
    app_env: str
    cookie_secure: bool
    llm_provider: str
    llm_model: str
    llm_base_url: str
    llm_api_key: str
    llm_timeout_seconds: float
    llm_context_window: int
    llm_input_limit: int
    llm_output_limit: int
    llm_safety_margin: int
    llm_reasoning_effort: str


def load_settings() -> AppSettings:
    load_dotenv(ENV_FILE, override=False)
    app_env = os.getenv("APP_ENV", "development").strip().lower()
    cookie_secure_env = os.getenv("COOKIE_SECURE")
    cookie_secure = (
        app_env == "production"
        if cookie_secure_env is None
        else cookie_secure_env.strip().lower() in {"1", "true", "yes", "on"}
    )
    return AppSettings(
        app_title=os.getenv("APP_TITLE", "剧镜 · AI 剧本杀"),
        app_env=app_env,
        cookie_secure=cookie_secure,
        llm_provider=os.getenv("LLM_PROVIDER", "echo"),
        llm_model=os.getenv("LLM_MODEL", "qwen3-32b"),
        llm_base_url=os.getenv("LLM_BASE_URL", "http://localhost:11434/v1"),
        llm_api_key=os.getenv("LLM_API_KEY", "ollama"),
        llm_timeout_seconds=float(os.getenv("LLM_TIMEOUT_SECONDS", "120")),
        llm_context_window=int(os.getenv("LLM_CONTEXT_WINDOW", "32768")),
        llm_input_limit=int(os.getenv("LLM_INPUT_TOKEN_LIMIT", "23000")),
        llm_output_limit=int(os.getenv("LLM_MAX_OUTPUT_TOKENS", "8192")),
        llm_safety_margin=int(os.getenv("LLM_TOKEN_SAFETY_MARGIN", "1024")),
        llm_reasoning_effort=os.getenv("LLM_REASONING_EFFORT", "").strip(),
    )
