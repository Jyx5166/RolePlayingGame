"""Public engine exports without loading the engine during rule/loader imports."""

def __getattr__(name: str):
    if name in {"DMEngine", "GamePhase", "GameState"}:
        from . import engine
        return getattr(engine, name)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
from .permission import PermissionMatrix
from .validator import SpeechValidator, ValidationResult

__all__ = [
    "DMEngine",
    "GamePhase",
    "GameState",
    "PermissionMatrix",
    "SpeechValidator",
    "ValidationResult",
]
