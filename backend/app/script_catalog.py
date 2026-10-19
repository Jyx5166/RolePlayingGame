"""Immutable script publication and public catalog; no Agent runtime is created here."""
from __future__ import annotations

import hashlib
import json
import uuid
from copy import deepcopy
from typing import Any

from authoring_validation import inspect_authoring
from game_service import GameService
from loader.script_loader import ScriptLoader
from paths import scripts_dir
from security import validate_script_payload
from storage import AppStore


BUILTIN_SCRIPT_IDS = (
    "fog_harbor_clocktower", "rainy_night_letter", "last_train",
    "deep_sea_echo", "old_house_corridor", "silent_theater",
)


def script_version(script: dict[str, Any]) -> str:
    return hashlib.sha256(json.dumps(script, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()).hexdigest()[:16]


class ScriptCatalog:
    def __init__(self, store: AppStore, service: GameService) -> None:
        self.store, self.service = store, service

    def _items(self, user_id: int) -> list[dict[str, Any]]:
        loader = ScriptLoader(scripts_dir())
        builtins = []
        for script_id in BUILTIN_SCRIPT_IDS:
            script = loader.load(script_id)
            builtins.append({"catalog_id": script_id, "version": script_version(script),
                             "source": "builtin", "script": script})
        return [*builtins,
                *[{**row, "source": "imported"} for row in self.store.list_published_scripts(user_id)]]

    def public_item(self, item: dict[str, Any]) -> dict[str, Any]:
        preview = self.service.inspect_script(item["script"], "deduction")
        return {**preview, "catalog_id": item["catalog_id"], "version": item["version"],
                "source": item["source"], "tags": item["script"]["script_meta"].get("tags", []),
                "provenance": item["script"]["script_meta"].get("provenance")}

    def list(self, user_id: int, query: str = "") -> list[dict[str, Any]]:
        items = [self.public_item(item) for item in self._items(user_id)]
        keyword = query.strip().casefold()
        return [item for item in items if not keyword or keyword in item["title"].casefold()
                or any(keyword in tag.casefold() for tag in item["tags"])]

    def resolve(self, user_id: int, catalog_id: str, version: str | None = None) -> dict[str, Any]:
        for item in self._items(user_id):
            if item["catalog_id"] == catalog_id and (version is None or item["version"] == version):
                return item
        if version:
            with self.store._connect() as connection:
                row = connection.execute('SELECT * FROM script_revisions WHERE catalog_id=? AND version=? AND user_id=?',(catalog_id,version,user_id)).fetchone()
            if row:
                return {**dict(row),'source':'imported','script':json.loads(row['script_json'])}
        raise KeyError("剧本不存在或无权访问")

    def publish(self, user_id: int, script: dict[str, Any], title: str, tags: list[str], *, authoring_job_id: str | None = None) -> dict[str, Any]:
        # Direct imports share deterministic authoring checks with workshop
        # publication, while retaining legacy scripts' compatibility warnings.
        validate_script_payload(script)
        normalized = deepcopy(script)
        if not isinstance(normalized.get("script_meta"), dict):
            raise ValueError("缺少 script_meta")
        normalized["script_meta"].update(title=title.strip(), tags=list(dict.fromkeys(tag.strip() for tag in tags if tag.strip())))
        checks = inspect_authoring(normalized)
        if not checks['passed']:
            raise ValueError('剧本作者校验未通过：' + '；'.join(checks['errors'][:5]))
        preview = self.service.inspect_script(normalized, "deduction")
        catalog_id, job_id = str(uuid.uuid4()), authoring_job_id or str(uuid.uuid4())
        version = script_version(normalized)
        self.store.publish_script(user_id, catalog_id, version, job_id, normalized, normalized["script_meta"]["tags"])
        with self.store._connect() as connection:
            if connection.execute("SELECT name FROM sqlite_master WHERE name='script_revisions'").fetchone():
                from storage import utc_now
                connection.execute('INSERT OR IGNORE INTO script_revisions VALUES (?,?,?,?,?)',
                    (catalog_id,version,user_id,json.dumps(normalized,ensure_ascii=False),utc_now()))
        return {**preview, "catalog_id": catalog_id, "version": version, "tags": normalized["script_meta"]["tags"],
                "source": "imported", "authoring_job_id": job_id,
                "workflow_steps": ["imported", "normalized", "validated", "previewed", "published"]}
