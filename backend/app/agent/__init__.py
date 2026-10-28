"""Public role-agent exports without loading instances during context imports."""


def __getattr__(name: str):
    if name == "AgentInstance":
        from .instance import AgentInstance
        return AgentInstance
    if name == "AgentPool":
        from .pool import AgentPool
        return AgentPool
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


__all__ = ["AgentInstance", "AgentPool"]
