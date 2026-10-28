from __future__ import annotations

import json
import re
from dataclasses import dataclass, replace
from typing import TYPE_CHECKING, Any

from agent.context import AgentContext, ContextMessage, ContextScope
from llm.budget import ContextBudget, ContextBudgetError

if TYPE_CHECKING:
    from memory.archive import MemoryArchive
    from runtime.contracts import RuntimeScope
    from workflow_config import WorkflowSettings


PROMPT_VERSION = "role-context-v3"


def terms(text: str) -> set[str]:
    words = set(re.findall(r"[a-z0-9_]+", text.lower()))
    for part in re.findall(r"[\u4e00-\u9fff]+", text):
        words.update(part[index:index + 2] for index in range(len(part) - 1))
    return words


@dataclass(frozen=True)
class PreparedInput:
    context: AgentContext
    system_prompt: str
    selection: dict[str, Any]

    def messages(self) -> list[dict[str, str]]:
        return [{"role": "system", "content": self.system_prompt}, *self.context.to_llm_messages()]

    def audit(self) -> dict[str, Any]:
        return {**self.context.to_audit_record(self.system_prompt),
                "prompt_version": PROMPT_VERSION, "memory_selection": self.selection}


def prepare_input(context: AgentContext, system: str, records: list[dict[str, Any]], budget: ContextBudget) -> PreparedInput:
    instructions = [message for message in context.messages if message.source_type not in {"public_history", "private_history"}]
    history = [message for message in context.messages if message not in instructions]
    query = terms(" ".join(message.content for message in instructions))
    eligible = [record for record in records if record["owner_role_id"] == context.role_id
                and 1 <= record["stage"] <= context.stage
                and (record["scope"] == "public" or context.role_id in record["recipients"])]
    required = [record for record in eligible if record.get("required")]
    optional = [record for record in eligible if not record.get("required")]
    kind_priority = {"role_knowledge": 8, "search_fact": 8, "dm_fact": 7, "testimony": 3, "belief": 1}
    optional.sort(key=lambda record: (
        len(query & terms(record["content"])) * 100 + kind_priority.get(record["kind"], 0),
        record["stage"], record.get("sequence", 0),
    ), reverse=True)
    selected = list(required)
    selected_history: list[ContextMessage] = []

    def build() -> AgentContext:
        content = "[ROLE_MEMORY_DATA]\n" + json.dumps(selected, ensure_ascii=False, separators=(",", ":"))
        memory = ContextMessage("user", content, ContextScope.ROLE_PRIVATE, "role_memory",
                                f"role-memory:{context.role_id}:{context.stage}", (context.role_id,))
        return AgentContext(context.role_id, context.stage, context.channel, context.purpose,
                            (memory, *selected_history, *instructions), runtime_scope=context.runtime_scope)

    used = budget.validate([{"role": "system", "content": system}, *build().to_llm_messages()])
    for record in optional:
        cost = len(json.dumps(record, ensure_ascii=False, separators=(",", ":")).encode("utf-8")) + (1 if selected else 0)
        if used + cost <= budget.input_limit:
            selected.append(record)
            used += cost
    for message in reversed(history):
        cost = len(message.to_llm_message()["content"].encode("utf-8")) + 16
        if used + cost <= budget.input_limit:
            selected_history.insert(0, message)
            used += cost
    final = build()
    estimated = budget.validate([{"role": "system", "content": system}, *final.to_llm_messages()])
    selected_keys = {record["source_key"] for record in selected}
    selection = {
        "selected_source_keys": [record["source_key"] for record in selected],
        "omitted_source_keys": [record["source_key"] for record in eligible if record["source_key"] not in selected_keys],
        "omitted_dialogue_keys": [message.source_key for message in history if message not in selected_history],
        "estimated_input_tokens": estimated, "estimator": "conservative_utf8_bytes",
        "input_limit": budget.input_limit, "output_limit": budget.output_limit,
        "context_window": budget.context_window, "safety_margin": budget.safety_margin,
        "content_truncated": False,
    }
    return PreparedInput(final, system, selection)


def prepare_role_input(
    context: AgentContext,
    system: str,
    records: list[dict[str, Any]],
    budget: ContextBudget,
    *,
    archive: MemoryArchive | None,
    scope: RuntimeScope | None,
    settings: WorkflowSettings | None,
    reserved_tokens: int = 0,
) -> PreparedInput:
    """Select bounded role input while retaining originals in the scoped archive."""
    if reserved_tokens >= budget.input_limit:
        raise ContextBudgetError("本回合工具续接已占满输入预算，原文已保存；请结束本回合")
    budget = replace(budget, input_limit=budget.input_limit-reserved_tokens)
    original_source_keys = [record['source_key'] for record in records]
    archived = archive is not None and settings.context_strategy == "archive_retrieval"
    if archived:
        from memory.archive import extract_summary

        query = " ".join(message.content for message in context.messages[-3:])
        ranked = sorted(records, key=lambda row: (bool(row.get('required')), len(terms(query)&terms(row['content'])), row.get('sequence', 0)), reverse=True)
        selected = ranked[:settings.memory_index_items]
        for record in selected:
            content = record['content']
            if record['kind']=='role_profile' and len(content.encode('utf-8'))>1800:
                profile=json.loads(content)
                def compact(value):
                    if isinstance(value,dict):return {key:(item if key=='role_id' else compact(item)) for key,item in value.items()}
                    if isinstance(value,list):return [compact(item) for item in value]
                    return extract_summary(value,100) if isinstance(value,str) and len(value)>120 else value
                record.update(content=json.dumps(compact(profile),ensure_ascii=False),representation='extractive_partial',original_chars=len(content))
            # Keep compact, mandatory identity/tasks verbatim. Large facts are explicitly indexed.
            if record['kind']!='role_profile' and (len(content.encode('utf-8')) > 900 or not record.get('required')):
                record.update(content=extract_summary(content), representation='extractive_partial', original_chars=len(content))
            record['required'] = record['kind'] in {'role_profile','personal_task'}
        records = selected
        index = archive.index(scope, context.stage, query, settings.memory_index_items)
        records.append({'source_key':'archive-index','owner_role_id':context.role_id,'kind':'archive_index','stage':context.stage,
                        'scope':'role_private','recipients':[context.role_id], 'required':True,
                        'content':json.dumps(index,ensure_ascii=False)})
    prepared = prepare_input(context, system, records, budget)
    prepared.selection.update(context_strategy='archive_retrieval' if archived else 'legacy_bounded',
                              originals_retained=True, reserved_tokens=reserved_tokens)
    if archived:
        selected = set(prepared.selection['selected_source_keys'])
        prepared.selection['omitted_source_keys'] = [key for key in original_source_keys if key not in selected]
    return prepared
