"""Offline review helpers. Oracle data must never be passed to game actors.

These checks establish exact/provenance violations, not semantic quality. Matching
the truth is not itself a leak: a player may infer it from visible evidence.
"""
from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Iterable, Mapping
from typing import Any


def _strings(value: Any) -> str:
    return value if isinstance(value, str) else json.dumps(value, ensure_ascii=False)


def _sentences(text: str) -> list[str]:
    return [part.strip() for part in re.split(r"(?<=[。！？.!?\n])", text) if part.strip()]


def _fragments(text: str) -> list[str]:
    return [part for part in _sentences(text) if len(re.sub(r"\s", "", part)) >= 12]


def _blocks(script: Mapping[str, Any]) -> list[dict[str, Any]]:
    result = {}
    for role in script["roles"]:
        for stage_key, knowledge in role.get("stage_knowledge", {}).items():
            for block in knowledge.get("blocks", []):
                identifier = block.get("block_id") or hashlib.sha256(block["content"].encode()).hexdigest()[:16]
                key = (identifier, block["content"])
                result[key] = {**block, "id": identifier, "stage_key": stage_key}
    return list(result.values())


def _clues(script: Mapping[str, Any]) -> list[dict[str, Any]]:
    return [{**clue, "unlock_stage": target["unlock_stage"]}
            for target in script.get("mechanics_config", {}).get("search", {}).get("search_targets", [])
            for clue in target.get("clues", [])]


def _allowed_block(block: Mapping[str, Any], actor: str, stage: int) -> bool:
    return block["unlock_stage"] <= stage and (
        block["visibility"] == "public" or
        block["visibility"] == "self_only" and block["owner_role"] == actor)


def _messages(snapshot: Mapping[str, Any]) -> list[dict[str, Any]]:
    context = snapshot.get("context") or snapshot
    messages = snapshot.get("wire_messages") or context.get("wire_messages") or snapshot.get("messages") or context.get("messages") or []
    result = [dict(item) for item in messages if isinstance(item, Mapping)]
    system = context.get("system_prompt")
    if system and not any(item.get("role") == "system" for item in result):
        result.insert(0, {"role": "system", "content": system})
    return result


def _json(value: Any) -> Any:
    if not isinstance(value, str):
        return value
    text = value.removeprefix("[ROLE_MEMORY_DATA]\n").strip()
    try:
        return json.loads(text)
    except (ValueError, TypeError):
        return None


def _text_values(value: Any) -> Iterable[str]:
    """Normalize nested JSON quotations so escaped wire text is also checked."""
    if isinstance(value, str):
        yield value
        parsed = _json(value)
        if isinstance(parsed, (Mapping, list)):
            yield from _text_values(parsed)
    elif isinstance(value, Mapping):
        for child in value.values():
            yield from _text_values(child)
    elif isinstance(value, list):
        for child in value:
            yield from _text_values(child)


def _hosting_known(source_stage: int, stage: int, phase: str | None) -> bool:
    # Missing phase preserves earlier offline fixtures; live captures have phase.
    return source_stage < stage or source_stage == stage and (
        phase is None or phase in {"dm_hosting", "final", "finale", "replay"})


def _flow_catalog(script: Mapping[str, Any], stage: int, phase: str | None) -> tuple[list[str], list[dict[str, Any]]]:
    allowed, forbidden = [], []
    source_names = {"public_briefing": "dm-public-briefing", "public_tasks": "dm-public-tasks", "dm_hosting": "dm-hosting"}
    for stage_key, flow in script.get("stage_flow", {}).items():
        source_stage = int(stage_key.split("_")[-1])
        for field, name in source_names.items():
            known = source_stage <= stage and (field != "dm_hosting" or _hosting_known(source_stage, stage, phase))
            for text in _text_values(flow.get(field, "")):
                if known:
                    allowed.append(text)
                elif text:
                    forbidden.append({"id": f"{name}:{source_stage}", "content": text,
                                      "reason": "premature current-stage hosting" if source_stage == stage else "future stage-flow information",
                                      "public_receipt_only": field == "dm_hosting" and source_stage == stage})
    return allowed, forbidden


def _records(value: Any) -> Iterable[Mapping[str, Any]]:
    """Include archive indices and read_memory payloads, whose IDs have provenance."""
    if isinstance(value, Mapping):
        if "source_key" in value or "scope" in value:
            yield value
        for key, child in value.items():
            if key == "content" and value.get("kind") == "archive_index":
                yield from _records(_json(child))
            elif isinstance(child, (Mapping, list)):
                yield from _records(child)
    elif isinstance(value, list):
        for child in value:
            yield from _records(child)


def _truth_paths(value: Any, path: str = "") -> Iterable[str]:
    if isinstance(value, Mapping):
        for key, child in value.items():
            here = f"{path}.{key}".strip(".")
            if key in {"truth", "full_truth", "full_story", "evidence_chain", "complete_timeline", "role_arcs", "culprit_role_id"}:
                yield here
            elif isinstance(child, (Mapping, list)):
                yield from _truth_paths(child, here)
            elif key in {"content", "raw_content"} and value.get("kind") not in {"testimony", "belief"}:
                parsed = _json(child)
                if isinstance(parsed, (Mapping, list)):
                    yield from _truth_paths(parsed, here)
    elif isinstance(value, list):
        for index, child in enumerate(value):
            yield from _truth_paths(child, f"{path}[{index}]")


def audit_input(script: Mapping[str, Any], snapshot: Mapping[str, Any], *,
                authorized_clue_ids: Iterable[str] | None = None,
                authorized_texts: Iterable[str] = (),
                authorized_public_texts: Iterable[str] = ()) -> dict[str, Any]:
    """Inspect actual input plus source scopes. Caller supplies visible receipts.

    snapshot: actor_role_id/role_id, stage, messages/wire_messages, optional
    source_items/context/runtime_scope. actor_kind='dm' excludes legitimate DM
    full-script inputs. authorized_texts are already delivered public/private
    disclosures; these do not become verified facts merely by being visible.
    None clue IDs means receipt coverage is unavailable, not zero obtained clues.
    Current-stage hosting needs its phase or a public receipt, not a private one.
    CLEAR only means these limited deterministic checks found no violation.
    """
    context = snapshot.get("context") or snapshot
    scope = snapshot.get("runtime_scope") or context.get("runtime_scope") or {}
    actor_kind = snapshot.get("actor_kind") or scope.get("actor_kind", "role")
    if actor_kind == "dm":
        return {"status": "EXCLUDED_DM", "findings": [], "coverage": {"reason": "DM legitimately reads the full script"}}
    actor = str(snapshot.get("actor_role_id") or snapshot.get("role_id") or scope.get("actor_role_id") or context.get("role_id") or "")
    stage = snapshot.get("stage", context.get("stage"))
    phase = snapshot.get("phase", context.get("phase"))
    if actor not in {role["role_id"] for role in script["roles"]} or not isinstance(stage, int) or isinstance(stage, bool) or stage < 1:
        raise ValueError("An input snapshot needs a valid actor role and current stage")
    messages = _messages(snapshot)
    findings: list[dict[str, Any]] = []

    def add(code: str, source: str, reason: str, span: str = "") -> None:
        item = {"category": "input_failure", "code": code, "source": source, "reason": reason, "span": span}
        if item not in findings:
            findings.append(item)

    structured = [snapshot.get("source_items", context.get("source_items", []))]
    for index, message in enumerate(messages):
        text = _strings(message.get("content", ""))
        if text.startswith("[ROLE_MEMORY_DATA]") or message.get("role") == "tool":
            parsed = _json(text)
            if parsed is not None:
                structured.append(parsed)
            elif text.startswith("[ROLE_MEMORY_DATA]"):
                add("unreadable_memory", f"message:{index}", "ROLE_MEMORY_DATA is not valid JSON")
        # A serialized script in a system prompt is a structural disclosure.
        elif message.get("source_type") not in {"public_history", "private_history"}:
            parsed = _json(text)
            if parsed is not None:
                structured.append(parsed)
    records = [item for payload in structured for item in _records(payload)]
    records.extend(item for item in messages if "scope" in item)
    for payload in structured:
        for path in _truth_paths(payload):
            add("oracle_truth_structure", path, "Truth fields are structurally present in role/player input")
    known_blocks = {block["id"]: block for block in _blocks(script)}
    visible_texts = list(authorized_texts)
    public_texts = list(authorized_public_texts)
    for payload in structured:
        if isinstance(payload, Mapping):
            public_texts.extend(str(item.get("content", "")) for item in payload.get("visible_state", {}).get("public_dialogue", []))
    for item in records:
        if item.get("scope") == "public" and (item.get("kind") == "testimony" or item.get("source_type") == "public_history"):
            public_texts.append(str(item.get("content", "")))
    for item in records:
        source = str(item.get("source_key", "unknown"))
        item_scope = item.get("scope")
        recipients = item.get("recipients", [])
        if item_scope == "dm_only":
            add("dm_only_source", source, "DM-only source entered an actor input")
        if item_scope in {"role_private", "participant_private"} and actor not in recipients:
            add("private_recipient", source, "Actor is not an authorized private recipient")
        if item_scope == "role_private" and recipients != [actor] and tuple(recipients) != (actor,):
            add("role_private_recipients", source, "Role-private source is not confined to this actor")
        if item_scope == "role_private" and item.get("owner_role_id", actor) != actor:
            add("private_owner", source, "Role-private record belongs to a different actor")
        item_stage = item.get("stage")
        if isinstance(item_stage, int) and item_stage > stage:
            add("future_source", source, "A future-stage source entered actual input")
        flow_source = re.match(r"dm-(hosting|public-briefing|public-tasks):(\d+)(?:$|:)", source)
        flow_stage = int(flow_source[2]) if flow_source else item_stage
        is_hosting = bool(flow_source and flow_source[1] == "hosting") or item.get("source_type") == "dm_hosting"
        if flow_source and flow_stage > stage:
            add("future_flow_source", source, "Stage-flow source key names a future stage, regardless of row metadata")
        if is_hosting and isinstance(flow_stage, int) and flow_stage <= stage and not _hosting_known(flow_stage, stage, phase):
            content = str(item.get("content", item.get("summary", ""))).strip()
            if not content or not any(content in text for text in public_texts):
                add("premature_hosting_source", source, "Current-stage hosting appeared before its phase without a public receipt", content)
        if source.startswith("knowledge:"):
            block = known_blocks.get(source.rsplit(":", 1)[-1])
            if block is not None and not _allowed_block(block, actor, stage):
                add("unauthorized_knowledge_source", source, "Knowledge provenance is future, other-role, or DM-only")
        if source.startswith(("truth:", "dm-truth:")) or item.get("kind") == "dm_knowledge":
            add("oracle_source", source, "Oracle/DM knowledge provenance entered actor input")
        if item.get("kind") in {"testimony", "belief"} and item_scope != "dm_only" and (item_scope == "public" or actor in recipients):
            visible_texts.append(str(item.get("content", "")))
        if item.get("source_type") in {"public_history", "private_history"} and (item_scope == "public" or actor in recipients):
            visible_texts.append(str(item.get("content", "")))
    allowed = [script.get("story_background", "")]
    allowed.extend(block["content"] for block in _blocks(script) if _allowed_block(block, actor, stage))
    allowed.extend(str(role.get("hidden_goal", "")) for role in script["roles"] if role["role_id"] == actor)
    flow_allowed, flow_forbidden = _flow_catalog(script, stage, phase)
    allowed.extend(flow_allowed)
    clues = _clues(script)
    receipt_ids = set(authorized_clue_ids or ())
    allowed.extend(clue["content"] for clue in clues if clue["id"] in receipt_ids and clue["unlock_stage"] <= stage)
    forbidden = [{"id": block["id"], "content": block["content"], "reason": "future/other-role/DM knowledge"}
                 for block in _blocks(script) if not _allowed_block(block, actor, stage)]
    forbidden.extend({"id": "role-goal:" + role["role_id"], "content": str(role.get("hidden_goal", "")), "reason": "other-role hidden goal"}
                     for role in script["roles"] if role["role_id"] != actor and role.get("hidden_goal"))
    forbidden.extend(flow_forbidden)
    forbidden.extend({"id": clue["id"], "content": clue["content"], "reason": "unreceived/future search clue"}
                     for clue in clues if clue["unlock_stage"] > stage or authorized_clue_ids is not None and clue["id"] not in receipt_ids)
    truth = script.get("truth", {})
    forbidden.extend({"id": "truth:" + key, "content": _strings(truth[key]), "reason": "oracle truth wording"}
                     for key in ("full_story", "complete_timeline", "role_arcs", "evidence_chain") if truth.get(key))
    raw = "\n".join(text for message in messages for text in _text_values(message.get("content", "")))
    for item in forbidden:
        receipts = public_texts if item.get("public_receipt_only") else visible_texts + public_texts
        for fragment in _fragments(item["content"]):
            if fragment in raw and not any(fragment in text for text in allowed + receipts):
                add("forbidden_exact_content", item["id"], item["reason"] + "; exact unique wording in actual input", fragment)
        identifier = item["id"]
        # Public role IDs, including the culprit's ID, are deliberately never scanned.
        if re.search(r"(?<![\w])" + re.escape(identifier) + r"(?![\w])", raw) and not any(identifier in text for text in receipts) and not (
                item.get("public_receipt_only") and any(item["content"] in text for text in public_texts)):
            add("forbidden_source_identifier", identifier, item["reason"] + "; unique source identifier in actual input", identifier)
    return {"status": "FAIL" if findings else "CLEAR", "findings": findings,
            "coverage": {"messages": len(messages), "source_records": len(records), "search_receipts_available": authorized_clue_ids is not None,
                         "hosting_phase_available": phase is not None,
                         "limitation": "Exact and provenance checks cannot prove semantic isolation or quality"}}


def review_output(script: Mapping[str, Any], output: str, snapshot: Mapping[str, Any], *,
                  authorized_clue_ids: Iterable[str] = (), authorized_texts: Iterable[str] = (),
                  authorized_public_texts: Iterable[str] = ()) -> dict[str, Any]:
    """Export every sentence for review; candidate labels are not factual verdicts."""
    authorized_clue_ids = tuple(authorized_clue_ids)
    authorized_texts = tuple(authorized_texts)
    authorized_public_texts = tuple(authorized_public_texts)
    context = snapshot.get("context") or snapshot
    scope = snapshot.get("runtime_scope") or context.get("runtime_scope") or {}
    actor = snapshot.get("actor_role_id") or snapshot.get("role_id") or scope.get("actor_role_id") or context.get("role_id")
    stage = snapshot.get("stage", context.get("stage"))
    audit = audit_input(script, snapshot, authorized_clue_ids=authorized_clue_ids, authorized_texts=authorized_texts,
                        authorized_public_texts=authorized_public_texts)
    raw = "\n".join(text for message in _messages(snapshot) for text in _text_values(message.get("content", "")))
    visible_ids = set(authorized_clue_ids)
    truth = script.get("truth", {})
    hidden = [block["content"] for block in _blocks(script) if not _allowed_block(block, actor, stage)]
    hidden.extend(str(role.get("hidden_goal", "")) for role in script["roles"] if role["role_id"] != actor)
    hidden.extend(item["content"] for item in _flow_catalog(script, stage, snapshot.get("phase", context.get("phase")))[1])
    hidden.extend(_strings(truth.get(key, "")) for key in ("full_story", "complete_timeline", "role_arcs"))
    candidates = []
    for sentence in _sentences(output):
        hidden_matches = [fragment for text in hidden for fragment in _fragments(text) if fragment in sentence]
        supports = [step for step in truth.get("evidence_chain", []) if step.get("conclusion", "") in sentence and step.get("conclusion")]
        evidenced = [step for step in supports if set(step.get("clue_ids", [])) <= visible_ids]
        repeated_leak = [finding for finding in audit["findings"] if finding.get("span") and finding["span"] in sentence]
        if repeated_leak:
            category, reason = "input_failure", "Repeated a span already identified as an input boundary violation"
        elif hidden_matches and not any(fragment in raw or any(fragment in text for text in authorized_texts + authorized_public_texts) for fragment in hidden_matches):
            category = "inference_candidate" if evidenced else "unsupported_fact_candidate"
            reason = "Matches hidden wording; visible clues may support a deduction, which needs semantic review" if evidenced else "Matches unavailable wording; could still be an inference, so this is not an automatic leak verdict"
        elif sentence in raw:
            category, reason = "visible_source_restatement", "Exact wording exists in actor input; check whether its source was fact, testimony, or belief"
        else:
            category, reason = "review_candidate", "No exact sentence grounding; assess facts, inference, testimony, and role consistency manually"
        candidates.append({"span": sentence, "category": category, "reason": reason,
                           "visible_evidence_chains": evidenced, "hidden_exact_matches": hidden_matches})
    role = next(role for role in script["roles"] if role["role_id"] == actor)
    task = script.get("stage_flow", {}).get(f"stage_{stage}", {}).get("personal_tasks", {}).get(actor, "")
    return {"status": "REVIEW_REQUIRED", "candidates": candidates, "input_audit": audit,
            "roleplay_anchors": {key: role.get(key, "") for key in ("role_name", "public_identity", "personality", "hidden_goal")},
            "current_task": task, "limitation": "No keyword-based roleplay score; all output spans require human assessment"}


def check_ending(script: Mapping[str, Any], final_decision: Mapping[str, Any], replay: Mapping[str, Any] | None = None, *,
                 reveal_truth_on_failure: bool, branch: str = "blind") -> dict[str, Any]:
    """Validate observed physical outcome without generating or steering a vote."""
    if branch not in {"blind", "forced_wrong_mechanical"}:
        raise ValueError("Label the ending as blind or forced_wrong_mechanical")
    final_stage = script["script_meta"]["total_stages"]
    config = script["stage_flow"][f"stage_{final_stage}"]["resolution"]["final_decision"]
    selected = final_decision.get("selected_role_id")
    roles = {role["role_id"]: role for role in script["roles"]}
    if selected not in config["eligible_role_ids"]:
        return {"status": "FAIL", "branch": branch, "findings": ["Final selection is absent or ineligible"]}
    correct = selected == script["truth"]["culprit_role_id"]
    revealed = correct or reveal_truth_on_failure
    verdict = config["correct_verdict" if correct else "incorrect_verdict"].format(selected_role_name=roles[selected]["role_name"])
    findings = []
    if final_decision.get("correct") is not correct:
        findings.append("Correctness flag contradicts the observed selection")
    if final_decision.get("truth_revealed") is not revealed:
        findings.append("Truth reveal flag contradicts this game's lifecycle policy")
    if not str(final_decision.get("outcome_text", "")).startswith(verdict):
        findings.append("Verdict does not match the engine's configured branch")
    if branch == "forced_wrong_mechanical" and correct:
        findings.append("A forced-wrong mechanical branch selected the culprit")
    if replay is not None:
        truth = script["truth"]
        expected = {"full_story": truth.get("full_story", "") if revealed else final_decision.get("outcome_text", ""),
                    "timeline": truth.get("complete_timeline", {}) if revealed else {},
                    "role_arcs": truth.get("role_arcs", {}) if revealed else {}, "truth_revealed": revealed}
        findings.extend(f"Replay {key} contradicts expected reveal policy" for key, value in expected.items() if replay.get(key) != value)
    return {"status": "FAIL" if findings else "PASS", "branch": branch, "findings": findings,
            "selected_role_id": selected, "expected_correct": correct, "expected_truth_revealed": revealed,
            "evidence_boundary": "Mechanical ending check; does not validate blind inference or roleplay quality"}
