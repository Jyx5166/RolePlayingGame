"""Coherent shortened cases for tests concerned only with final decisions."""
from copy import deepcopy


async def advance_to_investigation(engine) -> None:
    """Read the available opening/role/briefing screens before testing investigation."""
    for _ in range(4):
        if engine.state.scene_phase.value == "investigation":
            return
        if engine.state.scene_phase.value not in {"opening", "briefing", "private_reveal"}:
            raise AssertionError(f"Cannot begin investigation from {engine.state.scene_phase.value}")
        await engine.advance_scene_phase()
    raise AssertionError("Investigation was not reached after the introduction")


def single_stage_script(script: dict) -> dict:
    result = deepcopy(script)
    result["script_meta"]["total_stages"] = 1
    for role in result["roles"]:
        role["stage_knowledge"] = {"stage_1": role["stage_knowledge"]["stage_1"]}
        for block in role["stage_knowledge"]["stage_1"].get("blocks", []):
            block["unlock_stage"] = 1
    if "stage_flow" in result:
        result["stage_flow"] = {"stage_1": result["stage_flow"]["stage_1"]}
        result["stage_flow"]["stage_1"]["resolution"].pop("vote", None)
    search = result.get("mechanics_config", {}).get("search", {})
    if "ap_per_stage" in search:
        search["ap_per_stage"] = search["ap_per_stage"][:1]
    for target in search.get("search_targets", []):
        target["unlock_stage"] = 1
    availability = result.get("mechanics_config", {}).get("whisper", {}).get("role_available_from_stage", {})
    for role_id in availability:
        availability[role_id] = 1
    for constraint in result.get("hard_constraints", []):
        constraint["until_stage"] = 1
    return result
