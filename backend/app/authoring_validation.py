"""Deterministic authoring review, separate from legacy import acceptance.

This report checks structural promises and mechanically reachable information.
It cannot establish whether a mystery is logically unique or enjoyable to play.
No model calls, file writes, or mutation of the supplied documents occur here.
"""
from __future__ import annotations

import re
from datetime import datetime, timezone
from typing import Any

from dm.permission import PermissionMatrix
from loader.script_loader import ScriptLoader, ScriptValidationError


def _text(value: Any) -> str:
    return value.strip() if isinstance(value, str) else ""


def _normalized(value: str) -> str:
    return re.sub(r"[\W_]+", "", value.casefold())


def _placeholder(value: str) -> bool:
    return bool(re.fullmatch(r"(?:todo|tbd|placeholder|待补充|待填写|待生成|待完善|暂无|略|无)[.。…!！\s]*", value, re.I))


class _Report:
    def __init__(self) -> None:
        self.checks: list[dict[str, Any]] = []

    def add(self, code: str, label: str, status: str, message: str, path: str | None = None) -> None:
        item = {"code": code, "label": label, "status": status, "message": message}
        if path is not None:
            item["path"] = path
        self.checks.append(item)

    def result(self) -> dict[str, Any]:
        errors = [item["message"] for item in self.checks if item["status"] == "failed"]
        return {"passed": not errors, "checks": self.checks, "errors": errors,
                "warnings": [item["message"] for item in self.checks if item["status"] == "warning"]}


def inspect_authoring(script: dict, plan: dict | None = None) -> dict:
    """Return an authoring report; ``passed`` does not imply semantic approval.

    Optional plan contracts:
      timeline_events: [{event_id, time: HH:MM or ISO datetime, role_ids, location, event}]
      clue_links: [{clue_id, requires_clue_ids, available_stage, conclusion}]
    A missing plan is a warning, not an invented successful timeline audit.
    """
    report = _Report()
    try:
        # Reuse the runtime's schema, owner/unlock boundaries, reference and
        # individual clue AP checks rather than maintaining a competing loader.
        ScriptLoader(".").validate(script)
    except (ScriptValidationError, TypeError, KeyError, AttributeError) as exc:
        report.add("schema_contract", "运行契约", "failed", str(exc), "script")
        return report.result()
    report.add("schema_contract", "运行契约", "passed", "结构、权限、幕次和引用通过现有 ScriptLoader 校验。")
    _opening_and_roles(script, report, strict=plan is not None)
    clue_index = _clue_index(script)
    _evidence(script, clue_index, report)
    _public_disclosure(script, report)
    if plan is None:
        report.add("authoring_plan", "创作规划", "warning", "未提供结构化创作规划，未核验事件冲突与线索依赖。")
    elif not isinstance(plan, dict):
        report.add("authoring_plan", "创作规划", "failed", "创作规划必须是对象。", "plan")
    else:
        if any(clue.get('exclusivity','shared') != 'shared'
               for target in script.get('mechanics_config',{}).get('search',{}).get('search_targets',[])
               for clue in target.get('clues',[])):
            report.add('shared_authoring_clues','线索独立获取','failed',
                       '分幕作者校验只支持共享线索，独占线索的团队获取路径尚未验证。','mechanics_config.search')
        if "roles" in plan:
            original_ids = {role.get("role_id") for role in plan["roles"]}
            current_ids = {role["role_id"] for role in script["roles"]}
            changed = (original_ids != current_ids or
                       plan.get("script_meta",{}).get("total_stages") != script["script_meta"]["total_stages"] or
                       plan.get("truth",{}).get("culprit_role_id") != script["truth"].get("culprit_role_id"))
            report.add("canonical_design", "固定故事设计", "failed" if changed else "passed",
                       "修订不能改变固定的角色、幕数或真凶；需要新设计时请重新创作。" if changed else "角色、幕数和真凶与固定设计一致。", "plan")
        _timeline(plan.get("timeline_events"), script, report)
        _clue_links(plan.get("clue_links"), script, clue_index, report)
    report.add("semantic_review", "语义审阅边界", "warning",
               "以上为确定性检查；尚未证明证据可唯一推理、叙事无矛盾或真人读本体验合格。")
    return report.result()


def _opening_and_roles(script: dict, report: _Report, *, strict: bool) -> None:
    opening = script.get("opening") or {}
    content = _text(opening.get("content"))
    first = _text(script.get("stage_flow", {}).get("stage_1", {}).get("public_briefing"))
    if not content or not _text(opening.get("title")):
        report.add("opening_independent", "独立开幕", "failed" if strict else "warning", "需要独立开幕标题和正文；旧版导入可保留原流程。", "opening")
    elif _normalized(content) == _normalized(first):
        report.add("opening_independent", "独立开幕", "failed", "开幕正文与第一幕通报重复，应分别介绍背景和当幕事件。", "opening.content")
    else:
        report.add("opening_independent", "独立开幕", "passed", "独立开幕存在，且没有与第一幕通报全文复制。")
    permission = PermissionMatrix(script)
    for index, role in enumerate(script["roles"]):
        if not strict and not role["human_playable"]:
            continue
        for stage in range(1, script["script_meta"]["total_stages"] + 1):
            readable = [block for block in permission.current_stage_blocks(role["role_id"], stage)
                        if block["visibility"] == "self_only" and _text(block["content"])]
            path = f"roles.{index}.stage_knowledge.stage_{stage}"
            report.add("role_readability", "角色分幕读本", "passed" if readable else "failed" if strict else "warning",
                       f"{role['role_id']} 第 {stage} 幕" + ("有可读的私人剧本。" if readable else "没有当幕可读的私人剧本。"), path)


def _stage_ap(script: dict, stage: int) -> int:
    flow = script.get("stage_flow", {})
    if "search" not in script.get("mechanics_enabled", []):
        return 0
    if flow and "search" not in flow[f"stage_{stage}"]["investigation"]["enabled_actions"]:
        return 0
    ap = script.get("mechanics_config", {}).get("search", {}).get("ap_per_stage", [1])
    return ap[min(stage - 1, len(ap) - 1)]


def _clue_index(script: dict) -> dict[str, dict[str, Any]]:
    total = script["script_meta"]["total_stages"]
    clues = {}
    for target in script.get("mechanics_config", {}).get("search", {}).get("search_targets", []):
        unlock = target.get("unlock_stage", 1)
        for position, clue in enumerate(target.get("clues", []), 1):
            spent = 0
            earliest = None
            for stage in range(unlock, total + 1):
                spent += _stage_ap(script, stage)
                if spent >= position:
                    earliest = stage
                    break
            clues[clue["id"]] = {"target": target["id"], "position": position, "unlock": unlock, "earliest": earliest}
    return clues


def _evidence(script: dict, clues: dict, report: _Report) -> None:
    chain = script["truth"].get("evidence_chain", [])
    if not chain:
        report.add("evidence_chain", "证据推理链", "failed" if "deduction" in script["script_meta"]["supported_skills"] else "warning",
                   "未提供可核验的证据推理链。", "truth.evidence_chain")
        return
    fingerprints = set()
    required: dict[str, dict[str, Any]] = {}
    for index, step in enumerate(chain):
        path = f"truth.evidence_chain.{index}"
        conclusion, reasoning = _text(step["conclusion"]), _text(step["reasoning"])
        fingerprint = (_normalized(conclusion), tuple(sorted(step["clue_ids"])), _normalized(reasoning))
        duplicate = fingerprint in fingerprints
        fingerprints.add(fingerprint)
        empty = _placeholder(reasoning) or _placeholder(conclusion) or _normalized(reasoning) == _normalized(conclusion)
        report.add("evidence_chain", "证据推理链", "failed" if duplicate or empty else "passed",
                   f"证据链第 {index + 1} 步" + ("重复。" if duplicate else "缺少有效推理说明。" if empty else "包含结论、线索引用与推理说明。"), path)
        for clue_id in step["clue_ids"]:
            clue = clues[clue_id]  # Existing loader has checked references and final reachability.
            previous = required.get(clue["target"])
            if previous is None or previous["position"] < clue["position"]:
                required[clue["target"]] = clue
    # A necessary collective lower bound: reaching the deepest needed clue in
    # each target costs at least its prefix length. Do not claim this proves an
    # executable team strategy, especially for shared/exclusive combinations.
    total = script["script_meta"]["total_stages"]
    for start in sorted({clue["unlock"] for clue in required.values()}):
        needed = sum(clue["position"] for clue in required.values() if clue["unlock"] >= start)
        capacity = len(script["roles"]) * sum(_stage_ap(script, stage) for stage in range(start, total + 1))
        report.add("evidence_ap_budget", "关键线索行动预算", "failed" if needed > capacity else "passed",
                   f"第 {start} 幕起解锁的关键线索至少需要 {needed} 次搜证，团队理论预算为 {capacity} 次。", "truth.evidence_chain")


def _public_disclosure(script: dict, report: _Report) -> None:
    culprit = script["truth"].get("culprit_role_id")
    names = [role[key] for role in script["roles"] if role["role_id"] == culprit for key in ("role_id", "role_name")]
    surfaces = [("story_background", script["story_background"])]
    if script.get("opening"):
        surfaces.append(("opening.content", script["opening"]["content"]))
    for key, stage in script.get("stage_flow", {}).items():
        surfaces.append((f"stage_flow.{key}.public_briefing", stage["public_briefing"]))
        surfaces.append((f"stage_flow.{key}.dm_hosting", stage["dm_hosting"]))
        surfaces.extend((f"stage_flow.{key}.public_tasks.{index}", task) for index, task in enumerate(stage.get("public_tasks", [])))
    truth = _normalized(script["truth"]["full_story"])
    failures = 0
    for path, text in surfaces:
        reasons = []
        if re.search(r"\bculprit_role_id\b|\btruth\s*[.:：]\s*(?:full_story|evidence_chain)", text):
            reasons.append("包含私密真相字段标记")
        if len(truth) >= 40 and truth in _normalized(text):
            reasons.append("复制了完整真相正文")
        for name in names:
            escaped = re.escape(name)
            pattern = rf"(?:凶手|真凶|杀人者)\s*(?:就是|正是|是)\s*[「“\"']?{escaped}|{escaped}\s*(?:就|才)?是\s*(?:本案的)?(?:真凶|凶手|杀人者)"
            for match in re.finditer(pattern, text):
                # Accusations, hypotheses and questions are legitimate public
                # dialogue, not reliable evidence that the narrator leaks truth.
                start = max((text.rfind(mark, 0, match.start()) for mark in "。！？!?\n"), default=-1) + 1
                ends = [offset for mark in "。！？!?\n" if (offset := text.find(mark, match.end())) >= 0]
                end = min(ends) + 1 if ends else len(text)
                context = text[start:end]
                if re.search(r"怀疑|猜测|传言|声称|有人说|认为|是否|假如|如果|[？?]", context):
                    report.add("public_disclosure", "公开信息隔离", "warning", "公开文本含凶手指认语句，但处于猜测或引述语境，请人工复核。", path)
                else:
                    reasons.append("直接宣布真实凶手身份")
        if reasons:
            failures += 1
            report.add("public_disclosure", "公开信息隔离", "failed", "公开文本" + "、".join(dict.fromkeys(reasons)) + "。", path)
    if not failures:
        report.add("public_disclosure", "公开信息隔离", "passed", "未发现显式真相字段、完整真相复制或直接公布真实凶手的标记；不等同于语义防剧透证明。")


def _time_key(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    if re.fullmatch(r"(?:[01]\d|2[0-3]):[0-5]\d", value):
        return "clock:" + value
    if not re.fullmatch(r"\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}(?::\d{2}(?:\.\d+)?)?(?:Z|[+-]\d{2}:\d{2})?", value):
        return None
    try:
        time = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return "datetime:" + (time.astimezone(timezone.utc) if time.tzinfo else time).isoformat()


def _timeline(events: Any, script: dict, report: _Report) -> None:
    if events is None:
        report.add("timeline_plan", "结构化时间线", "warning", "未提供 timeline_events，未核验事件时空冲突。")
        return
    if not isinstance(events, list) or not events:
        report.add("timeline_plan", "结构化时间线", "failed", "timeline_events 必须是非空事件列表。", "plan.timeline_events")
        return
    role_ids = {role["role_id"] for role in script["roles"]}
    seen, positions = set(), {}
    for index, event in enumerate(events):
        path = f"plan.timeline_events.{index}"
        if not isinstance(event, dict):
            report.add("timeline_plan", "结构化时间线", "failed", "事件必须是对象。", path)
            continue
        event_id, location = _text(event.get("event_id")), _text(event.get("location"))
        roles, time = event.get("role_ids"), _time_key(event.get("time"))
        problems = []
        if not event_id or event_id in seen:
            problems.append("event_id 为空或重复")
        seen.add(event_id)
        if time is None:
            problems.append("time 必须是有效 HH:MM 或 ISO 日期时间")
        if not location or not _text(event.get("event")):
            problems.append("location 和 event 必须为非空文本")
        if not isinstance(roles, list) or any(not isinstance(role, str) or role not in role_ids for role in roles):
            problems.append("role_ids 必须仅引用已有角色")
        elif time is not None and location:
            for role in roles:
                key = (time, role)
                normalized_location = " ".join(location.casefold().split())
                if key in positions and positions[key] != normalized_location:
                    problems.append(f"{role} 同一时间出现在不同地点")
                positions[key] = normalized_location
        report.add("timeline_plan", "结构化时间线", "failed" if problems else "passed",
                   "；".join(problems) if problems else f"事件 {event_id} 的引用、格式和同时刻位置一致。", path)


def _clue_links(links: Any, script: dict, clues: dict, report: _Report) -> None:
    if links is None:
        report.add("clue_dependencies", "线索依赖", "warning", "未提供 clue_links，未核验线索依赖。")
        return
    if not isinstance(links, list) or not links:
        report.add("clue_dependencies", "线索依赖", "failed", "clue_links 必须是非空列表。", "plan.clue_links")
        return
    total = script["script_meta"]["total_stages"]
    nodes = {}
    for index, link in enumerate(links):
        path = f"plan.clue_links.{index}"
        if not isinstance(link, dict):
            report.add("clue_dependencies", "线索依赖", "failed", "线索依赖必须是对象。", path)
            continue
        clue_id, stage = link.get("clue_id"), link.get("available_stage")
        dependencies, conclusion = link.get("requires_clue_ids"), _text(link.get("conclusion"))
        problems = []
        if not isinstance(clue_id, str) or clue_id not in clues:
            problems.append("clue_id 不存在")
        elif clue_id in nodes:
            problems.append("clue_id 重复")
        if type(stage) is not int or not 1 <= stage <= total:
            problems.append("available_stage 超出幕次范围")
        elif isinstance(clue_id, str) and clue_id in clues and stage != clues[clue_id]["earliest"]:
            problems.append("声明的 available_stage 与线索实际最早可取得的幕次不一致")
        if not isinstance(dependencies, list) or any(not isinstance(dep, str) or dep not in clues for dep in dependencies):
            problems.append("requires_clue_ids 引用不存在的线索")
        elif len(dependencies) != len(set(dependencies)):
            problems.append("requires_clue_ids 重复引用")
        if not conclusion or _placeholder(conclusion):
            problems.append("conclusion 缺少推理结论")
        if not problems:
            nodes[clue_id] = {"stage": stage, "dependencies": dependencies, "path": path}
        report.add("clue_dependencies", "线索依赖", "failed" if problems else "passed",
                   "；".join(problems) if problems else f"{clue_id} 的引用和取得幕次有效。", path)
    missing = set(clues) - set(nodes)
    if missing:
        report.add("clue_dependency_coverage", "线索依赖覆盖", "failed", "以下线索缺少有效的依赖设计：" + "、".join(sorted(missing)[:8]) + "。", "plan.clue_links")
    incoming = {clue_id: 0 for clue_id in nodes}
    dependents: dict[str, list[str]] = {clue_id: [] for clue_id in nodes}
    for clue_id, node in nodes.items():
        for dependency in node["dependencies"]:
            available = nodes[dependency]["stage"] if dependency in nodes else clues[dependency]["earliest"]
            if available is None or available > node["stage"]:
                report.add("clue_dependency_order", "线索依赖先后", "failed", f"{clue_id} 依赖尚不可取得的 {dependency}。", node["path"])
            if dependency in nodes:
                incoming[clue_id] += 1
                dependents[dependency].append(clue_id)
    ready = [clue_id for clue_id, count in incoming.items() if count == 0]
    ordered = 0
    while ready:
        clue_id = ready.pop()
        ordered += 1
        for dependent in dependents[clue_id]:
            incoming[dependent] -= 1
            if incoming[dependent] == 0:
                ready.append(dependent)
    if ordered != len(nodes):
        blocked = [clue_id for clue_id, count in incoming.items() if count]
        report.add("clue_dependency_cycle", "线索依赖环", "failed",
                   "线索依赖存在环，无法完成顺序核验：" + "、".join(blocked[:8]) + "。", "plan.clue_links")
