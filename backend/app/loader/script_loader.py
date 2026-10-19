from __future__ import annotations

import json
from string import Formatter
from pathlib import Path
from typing import Any

from pydantic import ValidationError

from dm.task_evaluator import validate_task_checks
from .script_schema import ScriptDocument


class ScriptValidationError(ValueError):
    """Raised when script structure, permissions or runtime references are invalid."""


class ScriptLoader:
    def __init__(self, scripts_dir: str | Path) -> None:
        self.scripts_dir = Path(scripts_dir)

    def load(self, script_id: str) -> dict[str, Any]:
        path = self.scripts_dir / f"{script_id}.json"
        if not path.exists():
            raise FileNotFoundError(f"Script not found: {path}")

        with path.open("r", encoding="utf-8") as f:
            script = json.load(f)

        self.validate(script)
        return script

    def validate(self, script: dict[str, Any]) -> None:
        self._object(script, "script")
        required_top = ["script_meta", "story_background", "roles", "truth"]
        for key in required_top:
            if key not in script:
                raise ScriptValidationError(f"Missing top-level field: {key}")

        meta = script["script_meta"]
        self._object(meta, "script_meta")
        for key in ["script_id", "title", "total_stages", "supported_skills"]:
            if key not in meta:
                raise ScriptValidationError(f"Missing script_meta.{key}")

        for field in ("script_id", "title"):
            self._text(meta[field], f"script_meta.{field}")
        self._integer(meta["total_stages"], "script_meta.total_stages", 1)
        self._strings(meta["supported_skills"], "script_meta.supported_skills", nonempty=True)
        tags = meta.get("tags", [])
        self._strings(tags, "script_meta.tags")
        if len(tags) > 12 or any(not tag.strip() or len(tag) > 24 for tag in tags):
            raise ScriptValidationError("tags 最多 12 个，每个标签需要 1 至 24 个字符")
        if not set(meta["supported_skills"]).issubset({"narrative", "deduction", "faction"}):
            raise ScriptValidationError("script_meta.supported_skills contains unsupported skills")
        self._text(script["story_background"], "story_background")
        self._object(script["truth"], "truth")
        self._text(script["truth"].get("full_story"), "truth.full_story")
        for field in ("complete_timeline", "role_arcs"):
            self._object(script["truth"].get(field, {}), f"truth.{field}")
            for value in script["truth"].get(field, {}).values():
                self._text(value, f"truth.{field} value")
        if not isinstance(script["roles"], list) or len(script["roles"]) < 2:
            raise ScriptValidationError("roles must contain at least two roles")

        role_ids: set[str] = set()
        for role in script["roles"]:
            self._object(role, "role")
            for key in ["role_id", "role_name", "human_playable", "public_identity", "stage_knowledge"]:
                if key not in role:
                    raise ScriptValidationError(f"Role missing field {key}: {role}")
            role_id = role["role_id"]
            for field in ("role_id", "role_name", "public_identity"):
                self._text(role[field], f"role.{field}")
            if role_id in {"dm", "*"}:
                raise ScriptValidationError(f"role_id uses a reserved permission identifier: {role_id}")
            if not isinstance(role["human_playable"], bool):
                raise ScriptValidationError("role.human_playable must be boolean")
            self._object(role["stage_knowledge"], f"{role_id}.stage_knowledge")
            if role_id in role_ids:
                raise ScriptValidationError(f"Duplicate role_id: {role_id}")
            role_ids.add(role_id)

            for stage in range(1, int(meta["total_stages"]) + 1):
                stage_key = f"stage_{stage}"
                if stage_key not in role["stage_knowledge"]:
                    raise ScriptValidationError(f"{role_id} missing {stage_key}")
                self._object(role["stage_knowledge"][stage_key], f"{role_id}.{stage_key}")
                blocks = role["stage_knowledge"][stage_key].get("blocks", [])
                if not isinstance(blocks, list):
                    raise ScriptValidationError(f"{role_id}.{stage_key}.blocks must be a list")
                for block in blocks:
                    self._validate_info_block(role_id, stage_key, block)

        if not any(role["human_playable"] for role in script["roles"]):
            raise ScriptValidationError("roles must include a human-playable role")
        for role in script["roles"]:
            for stage in range(1, meta["total_stages"] + 1):
                for block in role["stage_knowledge"][f"stage_{stage}"].get("blocks", []):
                    if block["owner_role"] not in role_ids | {"dm", "*"}:
                        raise ScriptValidationError("info block owner_role references an unknown role")

        self._validate_mechanics(script, role_ids)
        self._validate_stage_flow(script, role_ids, int(meta["total_stages"]))
        constraints = script.get("hard_constraints", [])
        if not isinstance(constraints, list):
            raise ScriptValidationError("hard_constraints must be a list")
        for constraint in constraints:
            self._object(constraint, "hard_constraint")
            self._text(constraint.get("role_id"), "hard_constraint.role_id")
            if constraint.get("role_id") not in role_ids | {"*"}:
                raise ScriptValidationError("hard_constraint.role_id is invalid")
            self._integer(constraint.get("until_stage"), "hard_constraint.until_stage", 1)
            self._strings(constraint.get("keywords"), "hard_constraint.keywords", nonempty=True)
            self._text(constraint.get("message"), "hard_constraint.message")

        self._validate_contract(script, role_ids)

    @staticmethod
    def json_schema() -> dict[str, Any]:
        """Return the same versioned authoring schema used by typed validation."""
        return ScriptDocument.model_json_schema()

    def _validate_contract(self, script: dict[str, Any], role_ids: set[str]) -> None:
        # Legacy files are parsed through the same model, without modifying the
        # caller's dictionary or silently adding a version to persisted content.
        versioned = "schema_version" in script
        if versioned and script["schema_version"] != "1.0":
            raise ScriptValidationError("Unsupported schema_version; expected 1.0")
        try:
            ScriptDocument.model_validate({"schema_version": "1.0", **script})
        except ValidationError as exc:
            errors = "; ".join(
                f"{'.'.join(str(part) for part in error['loc'])}: {error['msg']}"
                for error in exc.errors(include_input=False, include_url=False)
            )
            raise ScriptValidationError(errors) from exc

        meta = script["script_meta"]
        total = meta["total_stages"]
        expected_stages = {f"stage_{stage}" for stage in range(1, total + 1)}
        skills = meta["supported_skills"]
        self._unique(skills, "script_meta.supported_skills")
        recommended = meta.get("recommended_player_role")
        if recommended is not None and not any(
            role["role_id"] == recommended and role["human_playable"]
            for role in script["roles"]
        ):
            raise ScriptValidationError("recommended_player_role must reference a human-playable role")

        block_ids: dict[str, tuple[dict[str, Any], set[str]]] = {}
        for role in script["roles"]:
            role_id = role["role_id"]
            if set(role["stage_knowledge"]) != expected_stages:
                raise ScriptValidationError(f"{role_id}.stage_knowledge must contain exactly the declared stages")
            for stage_key, knowledge in role["stage_knowledge"].items():
                containing_stage = int(stage_key.removeprefix("stage_"))
                for block in knowledge.get("blocks", []):
                    previous = block_ids.get(block["block_id"])
                    if previous is not None:
                        previous_block, containing_roles = previous
                        # Existing saved games repeated an identical public
                        # block in different role documents. Preserve those
                        # unversioned snapshots; new authoring uses unique IDs.
                        if (versioned or block["visibility"] != "public"
                                or block != previous_block or role_id in containing_roles):
                            raise ScriptValidationError(f"Duplicate block_id: {block['block_id']}")
                        containing_roles.add(role_id)
                    else:
                        block_ids[block["block_id"]] = (block, {role_id})
                    self._stage_range(block["unlock_stage"], total, "info block.unlock_stage")
                    if block["unlock_stage"] < containing_stage:
                        raise ScriptValidationError("info block.unlock_stage cannot precede its containing stage")
                    if block["visibility"] == "self_only" and block["owner_role"] != role_id:
                        raise ScriptValidationError("self_only info block owner_role must match its containing role")
                    if block["visibility"] == "dm_only" and block["owner_role"] != "dm":
                        raise ScriptValidationError("dm_only info block owner_role must be dm")

        truth = script["truth"]
        if not set(truth.get("role_arcs", {})).issubset(role_ids):
            raise ScriptValidationError("truth.role_arcs references an unknown role")
        if truth.get("culprit_role_id") is not None and truth["culprit_role_id"] not in role_ids:
            raise ScriptValidationError("truth.culprit_role_id references an unknown role")
        flow = script.get("stage_flow")
        if script.get("opening") is not None and not flow:
            raise ScriptValidationError("opening requires a nonempty stage_flow")
        if flow and set(flow) != expected_stages:
            raise ScriptValidationError("stage_flow must contain exactly the declared stages")
        if versioned and "deduction" in skills:
            if not flow:
                raise ScriptValidationError("versioned deduction scripts require stage_flow")
            if not truth.get("evidence_chain"):
                raise ScriptValidationError("versioned deduction scripts require truth.evidence_chain")

        enabled = script.get("mechanics_enabled", [])
        self._unique(enabled, "mechanics_enabled")
        mechanics = script.get("mechanics_config", {})
        if not set(mechanics).issubset(enabled):
            raise ScriptValidationError("mechanics_config contains a disabled mechanic")
        search = mechanics.get("search", {})
        clues: dict[str, tuple[int, int]] = {}
        for target in search.get("search_targets", []):
            unlock = target.get("unlock_stage", 1)
            self._stage_range(unlock, total, "search target.unlock_stage")
            for position, clue in enumerate(target.get("clues", []), start=1):
                clues[clue["id"]] = (unlock, position)
        for value in mechanics.get("whisper", {}).get("role_available_from_stage", {}).values():
            self._stage_range(value, total, "whisper availability stage")
        for constraint in script.get("hard_constraints", []):
            self._stage_range(constraint["until_stage"], total, "hard_constraint.until_stage")

        def check_clue(clue_id: str, stage: int) -> None:
            if clue_id not in clues:
                raise ScriptValidationError(f"Unknown clue reference: {clue_id}")
            unlock, position = clues[clue_id]
            ap = search.get("ap_per_stage", [1])
            available_ap = sum(
                ap[min(index - 1, len(ap) - 1)]
                for index in range(unlock, stage + 1)
                if not flow or "search" in flow[f"stage_{index}"]["investigation"]["enabled_actions"]
            )
            if "search" not in enabled or available_ap < position:
                raise ScriptValidationError(f"Clue {clue_id} is not reachable by stage {stage}")

        for item in truth.get("evidence_chain", []):
            self._unique(item["clue_ids"], "truth.evidence_chain.clue_ids")
            for clue_id in item["clue_ids"]:
                check_clue(clue_id, total)

        for stage_key, config in (flow or {}).items():
            stage = int(stage_key.removeprefix("stage_"))
            actions = config["investigation"]["enabled_actions"]
            self._unique(actions, f"stage_flow.{stage_key}.investigation.enabled_actions")
            conditions = config["investigation"].get("end_conditions", {})
            for counter, action in (("minimum_searches", "search"), ("minimum_whispers", "whisper")):
                if conditions.get(counter, 0) and action not in actions:
                    raise ScriptValidationError(f"{counter} requires the {action} action")
            for checks in config.get("personal_task_checks", {}).values():
                self._validate_task_references(checks, stage, actions, check_clue)
            resolution = config["resolution"]
            for vote_name in ("vote", "final_decision"):
                vote = resolution.get(vote_name)
                if vote is not None and vote_name == "final_decision" and stage != total:
                    self._validate_vote_config(
                        f"stage_flow.{stage_key}.resolution.final_decision", vote, role_ids,
                        allow_penalty=False,
                    )
            penalty = (resolution.get("vote") or {}).get("penalty")
            if penalty is not None:
                target_stage = stage + penalty.get("target_stage_offset", 1)
                self._stage_range(target_stage, total, "vote penalty target stage")
                if penalty.get("completion_checks"):
                    target_actions = flow[f"stage_{target_stage}"]["investigation"]["enabled_actions"]
                    self._validate_task_references(penalty["completion_checks"], target_stage, target_actions, check_clue)

    @staticmethod
    def _unique(values: list[str], path: str) -> None:
        if len(values) != len(set(values)):
            raise ScriptValidationError(f"{path} must be unique")

    @staticmethod
    def _stage_range(stage: int, total: int, path: str) -> None:
        if not 1 <= stage <= total:
            raise ScriptValidationError(f"{path} must be within 1..{total}")

    @staticmethod
    def _validate_task_references(checks: list[dict[str, Any]], stage: int, actions: list[str], check_clue: Any) -> None:
        for check in checks:
            if check["type"] == "clue_disclosure":
                if check.get("clue_id") is not None:
                    check_clue(check["clue_id"], stage)
                required_action = "whisper" if check["channel"] == "private" else "public_speech"
                if required_action not in actions:
                    raise ScriptValidationError(f"task clue disclosure requires the {required_action} action")
            else:
                for event in check["event_types"]:
                    required_action = "search" if event == "search" else (
                        "whisper" if "private" in event else "public_speech"
                    )
                    if required_action not in actions:
                        raise ScriptValidationError(f"task event {event} requires the {required_action} action")

    @staticmethod
    def _object(value: Any, path: str) -> None:
        if not isinstance(value, dict):
            raise ScriptValidationError(f"{path} must be an object")

    @staticmethod
    def _text(value: Any, path: str) -> None:
        if not isinstance(value, str) or not value.strip():
            raise ScriptValidationError(f"{path} must be a non-empty string")

    @staticmethod
    def _integer(value: Any, path: str, minimum: int = 0) -> None:
        if not isinstance(value, int) or isinstance(value, bool) or value < minimum:
            raise ScriptValidationError(f"{path} must be an integer >= {minimum}")

    @staticmethod
    def _strings(value: Any, path: str, *, nonempty: bool = False) -> None:
        if not isinstance(value, list) or (nonempty and not value) or not all(
            isinstance(item, str) and item.strip() for item in value
        ):
            raise ScriptValidationError(f"{path} must be a string list")

    def _validate_mechanics(self, script: dict[str, Any], role_ids: set[str]) -> None:
        enabled = script.get("mechanics_enabled", [])
        self._strings(enabled, "mechanics_enabled")
        if not set(enabled).issubset({"search", "whisper"}):
            raise ScriptValidationError("mechanics_enabled contains unsupported mechanics")
        config = script.get("mechanics_config", {})
        self._object(config, "mechanics_config")
        for name in enabled:
            self._object(config.get(name, {}), f"mechanics_config.{name}")
        if "search" in enabled:
            search = config.get("search", {})
            ap = search.get("ap_per_stage", [1])
            if not isinstance(ap, list) or not ap:
                raise ScriptValidationError("search.ap_per_stage must be non-empty")
            for value in ap:
                self._integer(value, "search.ap_per_stage item")
            targets = search.get("search_targets", [])
            if not isinstance(targets, list):
                raise ScriptValidationError("search.search_targets must be a list")
            target_ids: set[str] = set()
            clue_ids: set[str] = set()
            for target in targets:
                self._object(target, "search target")
                self._text(target.get("id"), "search target.id")
                self._text(target.get("name", target["id"]), "search target.name")
                self._integer(target.get("unlock_stage", 1), "search target.unlock_stage", 1)
                if target["id"] in target_ids:
                    raise ScriptValidationError("duplicate search target.id")
                target_ids.add(target["id"])
                clues = target.get("clues", [])
                if not isinstance(clues, list):
                    raise ScriptValidationError("search target.clues must be a list")
                for clue in clues:
                    self._object(clue, "clue")
                    self._text(clue.get("id"), "clue.id")
                    self._text(clue.get("content"), "clue.content")
                    if clue["id"] in clue_ids:
                        raise ScriptValidationError("duplicate clue.id")
                    clue_ids.add(clue["id"])
                    if clue.get("exclusivity", "shared") not in ("shared", "exclusive"):
                        raise ScriptValidationError("clue.exclusivity is invalid")
        if "whisper" in enabled:
            whisper = config.get("whisper", {})
            self._integer(whisper.get("max_sessions_per_stage", 2), "whisper.max_sessions_per_stage")
            availability = whisper.get("role_available_from_stage", {})
            self._object(availability, "whisper.role_available_from_stage")
            if not set(availability).issubset(role_ids):
                raise ScriptValidationError("whisper availability references an unknown role")
            for value in availability.values():
                self._integer(value, "whisper availability stage", 1)

    def _validate_info_block(self, role_id: str, stage_key: str, block: dict[str, Any]) -> None:
        self._object(block, f"{role_id}.{stage_key}.block")
        required = ["block_id", "type", "content", "visibility", "unlock_stage", "owner_role"]
        for key in required:
            if key not in block:
                raise ScriptValidationError(f"{role_id}.{stage_key} block missing {key}: {block}")
        for field in ("block_id", "type", "content", "visibility", "owner_role"):
            self._text(block[field], f"info block.{field}")
        if block["visibility"] not in {"public", "self_only", "dm_only"}:
            raise ScriptValidationError("info block.visibility is invalid")
        self._integer(block["unlock_stage"], "info block.unlock_stage", 1)

    def _validate_stage_flow(
        self,
        script: dict[str, Any],
        role_ids: set[str],
        total_stages: int,
    ) -> None:
        flow = script.get("stage_flow")
        if flow is None:
            return
        if not isinstance(flow, dict):
            raise ScriptValidationError("stage_flow must be an object")
        if not flow:
            return

        allowed_actions = {"public_speech", "search", "whisper"}
        for stage in range(1, total_stages + 1):
            stage_key = f"stage_{stage}"
            if stage_key not in flow:
                raise ScriptValidationError(f"stage_flow missing {stage_key}")
            config = flow[stage_key]
            if not isinstance(config, dict):
                raise ScriptValidationError(f"stage_flow.{stage_key} must be an object")
            for field in ["title", "public_briefing", "dm_hosting"]:
                if not isinstance(config.get(field), str) or not config[field].strip():
                    raise ScriptValidationError(f"stage_flow.{stage_key}.{field} must be non-empty")

            public_tasks = config.get("public_tasks", [])
            if not isinstance(public_tasks, list) or not all(
                isinstance(item, str) and item.strip() for item in public_tasks
            ):
                raise ScriptValidationError(
                    f"stage_flow.{stage_key}.public_tasks must be a string list"
                )

            personal_tasks = config.get("personal_tasks", {})
            if not isinstance(personal_tasks, dict):
                raise ScriptValidationError(
                    f"stage_flow.{stage_key}.personal_tasks must be an object"
                )
            unknown_roles = set(personal_tasks) - role_ids
            if unknown_roles:
                raise ScriptValidationError(
                    f"stage_flow.{stage_key}.personal_tasks contains unknown roles: "
                    + ", ".join(sorted(unknown_roles))
                )
            for task in personal_tasks.values():
                self._text(task, f"stage_flow.{stage_key}.personal_task")
            task_checks = config.get("personal_task_checks", {})
            self._object(task_checks, f"stage_flow.{stage_key}.personal_task_checks")
            if not set(task_checks).issubset(role_ids):
                raise ScriptValidationError("personal_task_checks references an unknown role")
            for checks in task_checks.values():
                self._validate_task_checks(checks, role_ids)

            investigation = config.get("investigation")
            if not isinstance(investigation, dict):
                raise ScriptValidationError(
                    f"stage_flow.{stage_key}.investigation must be an object"
                )
            duration = investigation.get("duration_seconds", 0)
            if not isinstance(duration, int) or isinstance(duration, bool) or duration < 0:
                raise ScriptValidationError(
                    f"stage_flow.{stage_key}.investigation.duration_seconds must be >= 0"
                )
            enabled = investigation.get("enabled_actions", [])
            self._strings(enabled, f"stage_flow.{stage_key}.investigation.enabled_actions", nonempty=True)
            if not set(enabled).issubset(allowed_actions):
                raise ScriptValidationError(
                    f"stage_flow.{stage_key}.investigation.enabled_actions is invalid"
                )
            manual = investigation.get("allow_manual_end", True)
            if not isinstance(manual, bool) or (duration == 0 and not manual):
                raise ScriptValidationError(f"stage_flow.{stage_key}.investigation must allow timeout or manual majority vote")
            if "search" in enabled and "search" not in script.get("mechanics_enabled", []):
                raise ScriptValidationError(f"stage_flow.{stage_key} enables search without the mechanic")
            if "whisper" in enabled and "whisper" not in script.get("mechanics_enabled", []):
                raise ScriptValidationError(f"stage_flow.{stage_key} enables whisper without the mechanic")
            end_conditions = investigation.get("end_conditions", {})
            if not isinstance(end_conditions, dict):
                raise ScriptValidationError(
                    f"stage_flow.{stage_key}.investigation.end_conditions must be an object"
                )
            if end_conditions.get("mode", "all") not in ("all", "any"):
                raise ScriptValidationError(
                    f"stage_flow.{stage_key}.investigation.end_conditions.mode is invalid"
                )
            if end_conditions.get("actor_scope", "human") not in ("human", "all"):
                raise ScriptValidationError(
                    f"stage_flow.{stage_key}.investigation.end_conditions.actor_scope is invalid"
                )
            if "auto_end" in end_conditions and not isinstance(
                end_conditions["auto_end"], bool
            ):
                raise ScriptValidationError(
                    f"stage_flow.{stage_key}.investigation.end_conditions.auto_end "
                    "must be boolean"
                )
            if end_conditions.get("auto_end", False):
                raise ScriptValidationError(
                    f"stage_flow.{stage_key}.investigation.end_conditions.auto_end must be false; only timeout or majority vote may end investigation"
                )
            for field in (
                "minimum_public_messages",
                "minimum_searches",
                "minimum_whispers",
            ):
                if field not in end_conditions:
                    continue
                value = end_conditions[field]
                if not isinstance(value, int) or isinstance(value, bool) or value < 0:
                    raise ScriptValidationError(
                        f"stage_flow.{stage_key}.investigation.end_conditions.{field} "
                        "must be >= 0"
                    )
            autonomy = investigation.get("autonomy", {})
            if not isinstance(autonomy, dict):
                raise ScriptValidationError(
                    f"stage_flow.{stage_key}.investigation.autonomy must be an object"
                )
            for field, minimum in (
                ("initial_delay_seconds", 0),
                ("interval_seconds", 1),
                ("max_turns", 0),
            ):
                if field not in autonomy:
                    continue
                value = autonomy[field]
                if not isinstance(value, (int, float)) or isinstance(value, bool) or value < minimum:
                    raise ScriptValidationError(
                        f"stage_flow.{stage_key}.investigation.autonomy.{field} "
                        f"must be >= {minimum}"
                    )
            for field in ("enabled", "allow_private"):
                if field in autonomy and not isinstance(autonomy[field], bool):
                    raise ScriptValidationError(
                        f"stage_flow.{stage_key}.investigation.autonomy.{field} "
                        "must be boolean"
                    )

            self._validate_resolution(
                script,
                stage_key,
                config.get("resolution"),
                role_ids,
                is_final_stage=stage == total_stages,
            )

    def _validate_resolution(
        self,
        script: dict[str, Any],
        stage_key: str,
        resolution: Any,
        role_ids: set[str],
        *,
        is_final_stage: bool,
    ) -> None:
        path = f"stage_flow.{stage_key}.resolution"
        if not isinstance(resolution, dict):
            raise ScriptValidationError(f"{path} must be an object")
        if not isinstance(resolution.get("title"), str) or not resolution["title"].strip():
            raise ScriptValidationError(f"{path}.title must be non-empty")

        metric = resolution.get("metric")
        if not isinstance(metric, dict):
            raise ScriptValidationError(f"{path}.metric must be an object")
        for field in ("key", "label", "unit"):
            if not isinstance(metric.get(field), str) or not metric[field].strip():
                raise ScriptValidationError(f"{path}.metric.{field} must be non-empty")
        initial = metric.get("initial", 0)
        if not isinstance(initial, int) or isinstance(initial, bool):
            raise ScriptValidationError(f"{path}.metric.initial must be an integer")

        rules = resolution.get("scoring_rules")
        if not isinstance(rules, list) or not rules:
            raise ScriptValidationError(f"{path}.scoring_rules must be a non-empty list")
        for index, rule in enumerate(rules):
            rule_path = f"{path}.scoring_rules[{index}]"
            if not isinstance(rule, dict):
                raise ScriptValidationError(f"{rule_path} must be an object")
            if not isinstance(rule.get("label"), str) or not rule["label"].strip():
                raise ScriptValidationError(f"{rule_path}.label must be non-empty")
            event_types = rule.get("event_types")
            if not isinstance(event_types, list) or not event_types or not all(
                isinstance(item, str) and item.strip() for item in event_types
            ):
                raise ScriptValidationError(f"{rule_path}.event_types must be a string list")
            points = rule.get("points_per_event")
            maximum = rule.get("max_points")
            if not isinstance(points, int) or isinstance(points, bool):
                raise ScriptValidationError(f"{rule_path}.points_per_event must be an integer")
            if not isinstance(maximum, int) or isinstance(maximum, bool) or maximum < 0:
                raise ScriptValidationError(f"{rule_path}.max_points must be >= 0")

        adjustments = resolution.get("role_adjustments", {})
        if not isinstance(adjustments, dict):
            raise ScriptValidationError(f"{path}.role_adjustments must be an object")
        unknown_adjustments = set(adjustments) - role_ids
        if unknown_adjustments:
            raise ScriptValidationError(
                f"{path}.role_adjustments contains unknown roles: "
                + ", ".join(sorted(unknown_adjustments))
            )
        for role_id, adjustment in adjustments.items():
            if not isinstance(adjustment, dict):
                raise ScriptValidationError(f"{path}.role_adjustments.{role_id} must be an object")
            if not isinstance(adjustment.get("points"), int) or isinstance(
                adjustment.get("points"), bool
            ):
                raise ScriptValidationError(
                    f"{path}.role_adjustments.{role_id}.points must be an integer"
                )
            if not isinstance(adjustment.get("reason"), str) or not adjustment["reason"].strip():
                raise ScriptValidationError(
                    f"{path}.role_adjustments.{role_id}.reason must be non-empty"
                )

        vote = resolution.get("vote")
        if vote is not None:
            self._validate_vote_config(f"{path}.vote", vote, role_ids, allow_penalty=True)

        final_decision = resolution.get("final_decision")
        if is_final_stage:
            self._validate_vote_config(
                f"{path}.final_decision",
                final_decision,
                role_ids,
                allow_penalty=False,
            )
            culprit_role_id = script.get("truth", {}).get("culprit_role_id")
            self._text(culprit_role_id, "truth.culprit_role_id")
            if culprit_role_id not in role_ids:
                raise ScriptValidationError(
                    "truth.culprit_role_id must reference a known role for the final decision"
                )
            if culprit_role_id not in final_decision["eligible_role_ids"]:
                raise ScriptValidationError("final decision must include the culprit among eligible roles")

    def _validate_vote_config(
        self,
        path: str,
        vote: Any,
        role_ids: set[str],
        *,
        allow_penalty: bool,
    ) -> None:
        if not isinstance(vote, dict):
            raise ScriptValidationError(f"{path} must be an object")
        if not isinstance(vote.get("prompt"), str) or not vote["prompt"].strip():
            raise ScriptValidationError(f"{path}.prompt must be non-empty")
        candidates = vote.get("eligible_role_ids")
        self._strings(candidates, f"{path}.eligible_role_ids", nonempty=True)
        if not isinstance(candidates, list) or len(candidates) < 2:
            raise ScriptValidationError(f"{path}.eligible_role_ids must contain at least two roles")
        if len(candidates) != len(set(candidates)) or not set(candidates).issubset(role_ids):
            raise ScriptValidationError(f"{path}.eligible_role_ids contains invalid roles")

        if allow_penalty:
            penalty = vote.get("penalty")
            if penalty is None:
                return
            if not isinstance(penalty, dict):
                raise ScriptValidationError(f"{path}.penalty must be an object")
            for field in ("label", "description"):
                if not isinstance(penalty.get(field), str) or not penalty[field].strip():
                    raise ScriptValidationError(f"{path}.penalty.{field} must be non-empty")
            offset = penalty.get("target_stage_offset", 1)
            reduction = penalty.get("search_ap_reduction", 0)
            if not isinstance(offset, int) or isinstance(offset, bool) or offset < 1:
                raise ScriptValidationError(f"{path}.penalty.target_stage_offset must be >= 1")
            if not isinstance(reduction, int) or isinstance(reduction, bool) or reduction < 0:
                raise ScriptValidationError(f"{path}.penalty.search_ap_reduction must be >= 0")
            extra_task = penalty.get("extra_task", "")
            if not isinstance(extra_task, str):
                raise ScriptValidationError(f"{path}.penalty.extra_task must be a string")
            if "completion_checks" in penalty:
                if not extra_task.strip():
                    raise ScriptValidationError("penalty completion_checks requires extra_task")
                self._validate_task_checks(penalty["completion_checks"], role_ids)
            return

        for field in ("correct_verdict", "incorrect_verdict"):
            if not isinstance(vote.get(field), str) or not vote[field].strip():
                raise ScriptValidationError(f"{path}.{field} must be non-empty")
            try:
                for _, name, spec, conversion in Formatter().parse(vote[field]):
                    if name is not None and (name != "selected_role_name" or spec or conversion):
                        raise ValueError("only {selected_role_name} is supported")
                vote[field].format(selected_role_name="角色")
            except (ValueError, KeyError, IndexError, AttributeError) as exc:
                raise ScriptValidationError(f"{path}.{field} has an invalid template: {exc}") from exc
        if vote.get("reveal_truth_on_correct", True) is not True:
            raise ScriptValidationError(f"{path}.reveal_truth_on_correct must be true")

    @staticmethod
    def _validate_task_checks(checks: Any, role_ids: set[str]) -> None:
        try:
            validate_task_checks(checks, role_ids)
        except ValueError as exc:
            raise ScriptValidationError(str(exc)) from exc
