"""Short, coherent authoring responses; never contact a model provider in tests."""
from __future__ import annotations

from copy import deepcopy
import inspect
import json

from llm.base import BaseLLM
from test_authoring_validation import authoring_fixture, authoring_plan


def staged_authoring_fixture() -> tuple[dict, dict]:
    script = authoring_fixture()
    plan = authoring_plan()
    script["truth"]["complete_timeline"] = {"20:10": "前厅：交付原信。；修复室：领取修复材料。"}
    script["truth"]["role_arcs"] = {}
    plan.update({key: deepcopy(script[key]) for key in (
        "script_meta", "story_background", "mechanics_enabled", "mechanics_config", "truth"
    )})
    plan["hard_constraints"] = []
    plan["roles"] = []
    for role in script["roles"]:
        role_id = role["role_id"]
        plan["roles"].append({
            **{key: role[key] for key in ("role_id", "role_name", "human_playable", "public_identity")},
            "personality": "谨慎，只为亲眼见过的事情作证。",
            "hidden_goal": "查清遗信为何被拆封。",
            "private_history": f"{role_id}_PRIVATE_HISTORY：你曾独自保管过与旧宅有关的文件。",
            "known_event_ids": {"stage_1": ["delivery" if role_id == "qin" else "repair"], "stage_2": []},
            "knowledge_by_stage": {
                "stage_1": ["你因旧宅主人的来信而赴约。"],
                "stage_2": ["你注意到信封外侧的编号与旧档案相同。"],
            },
        })
    plan["stage_design"] = {
        key: {"title": stage["title"], "objective": "核对原件与证词。",
              "public_facts": [stage["public_briefing"]],
              "clue_ids": ["letter", "seal"] if key == "stage_1" else ["receipt"]}
        for key, stage in script["stage_flow"].items()
    }
    return script, plan


class FixtureAuthoringLLM(BaseLLM):
    """Dispatch the actual response schema, with injectable bounded failures.

    ``handler(payload, default_output)`` can replace a response or raise. An
    asynchronous handler can block a specific call to exercise cancellation.
    ``review_issues`` is a list of rounds, emitted by the public reviewer only.
    """

    provider = "fixture"
    model = "staged-authoring-fixture"

    def __init__(self, *, handler=None, review_issues=None, unknown_usage_at=()):
        self.script, self.plan = staged_authoring_fixture()
        self.handler = handler
        self.review_issues = review_issues or [[]]
        self.unknown_usage_at = set(unknown_usage_at)
        self.calls: list[dict] = []
        self.review_round = -1

    def response(self, payload: dict) -> dict:
        title = payload["output_schema"]["title"]
        if title == "StoryPlan":
            return deepcopy(self.plan)
        if title == "Opening":
            result = deepcopy(self.script["opening"])
            if "issues_to_fix" in payload:
                result["content"] += "众人决定先各自回想来到旧宅之前的经历。"
            return result
        if title == "RoleReading":
            role_id = payload["role_design"]["role_id"]
            role = next(role for role in self.script["roles"] if role["role_id"] == role_id)
            return {"stage_knowledge": deepcopy(role["stage_knowledge"])}
        if title == "StageFlow":
            return deepcopy(self.script["stage_flow"][payload["stage_key"]])
        if title == "SemanticReview":
            issues = []
            if "public_cast" in payload:
                self.review_round += 1
                issues = self.review_issues[min(self.review_round, len(self.review_issues) - 1)]
            return {"summary": "已检查当前范围的事件与信息边界。", "issues": deepcopy(issues)}
        raise AssertionError(f"Unexpected authoring response schema: {title}")

    async def chat(self, messages):
        payload = json.loads(messages[-1]["content"])
        self.calls.append(deepcopy(payload))
        self.last_provider_invoked = True
        self.last_finish_reason = "stop"
        if len(self.calls) not in self.unknown_usage_at:
            self.last_usage = {"prompt_tokens": 10, "completion_tokens": 20, "total_tokens": 30}
        output = self.response(payload)
        if self.handler is not None:
            output = self.handler(payload, output)
            if inspect.isawaitable(output):
                output = await output
        return output if isinstance(output, str) else json.dumps(output, ensure_ascii=False)


def review_error(path: str = "opening.content") -> dict:
    return {"severity": "error", "code": "contradiction", "message": "此处叙述与既定事件冲突，需要修订。", "path": path}
