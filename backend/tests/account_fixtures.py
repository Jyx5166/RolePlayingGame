"""Generate disposable account credentials for isolated regression tests."""

from __future__ import annotations

import secrets


def new_test_password() -> str:
    return secrets.token_urlsafe(24)


def new_test_account(prefix: str = "test") -> dict[str, str]:
    return {
        "username": f"{prefix[:19]}_{secrets.token_hex(6)}",
        "password": new_test_password(),
    }
