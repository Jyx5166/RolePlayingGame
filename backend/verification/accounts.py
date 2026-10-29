"""Random verification accounts, persisted only in Git-ignored local exports."""
from __future__ import annotations

import json
import os
import secrets
import uuid
from pathlib import Path
from typing import Any


def new_verification_account(prefix: str) -> dict[str, str]:
    return {
        "username": f"{prefix[:19]}_{uuid.uuid4().hex[:12]}",
        "password": secrets.token_urlsafe(32),
    }


def save_verification_account(path: Path, account: dict[str, str]) -> None:
    if path.name not in {"qa-access.json", "access.json"}:
        raise ValueError("Verification credentials require an ignored account export filename")
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
        json.dump(account, stream)
    path.chmod(0o600)


def verification_session(
    store: Any, directory: Path, *, prefix: str, require_existing: bool = False,
) -> dict[str, Any]:
    path = directory / "qa-access.json"
    if path.exists():
        account = json.loads(path.read_text(encoding="utf-8"))
        if (
            not isinstance(account, dict)
            or set(account) != {"username", "password"}
            or not all(isinstance(value, str) and value for value in account.values())
        ):
            raise ValueError("Invalid local verification account export")
        return store.login(**account)
    if require_existing:
        raise ValueError("No local verification account export; generate the fixtures first")
    account = new_verification_account(prefix)
    session = store.register(**account)
    save_verification_account(path, account)
    return session
