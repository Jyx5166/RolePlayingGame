from __future__ import annotations

import json
import uuid
from typing import Any

from .base import BaseLLM
from .tools import ToolModelReply, parse_native_message, parse_json_reply


class EchoLLM(BaseLLM):
    provider = "echo"
    model = "echo"
    supports_native_tools = True

    async def chat_tools(self, messages: list[dict[str, Any]], definitions: list[dict[str, Any]],
                         *, transport: str = "native_tools") -> ToolModelReply:
        self.last_provider_invoked = True
        names = {tool["function"]["name"] for tool in definitions}
        data: dict[str, Any] = {}
        for message in messages:
            content = message.get("content") or ""
            if content.startswith(("[DM_DIRECTOR_DATA]\n", "[ROLE_TOOL_TURN]\n")):
                data = json.JSONDecoder().raw_decode(content.split("\n", 1)[1])[0]
        previous = [message for message in messages if message["role"] == "tool"]
        name, arguments = "", {}
        controls = {"reply_dialogue": "content", "cast_role_vote": "target_role_id", "decide_phase_end": "decision",
                    "decide_invitation": "decision", "review_speech": "decision"}
        matched = names.intersection(controls)
        if matched:
            name = sorted(matched)[0]
            arguments = {controls[name]: await self.chat(messages)}
        elif 'present_script_section' in names and data.get('hosting_section') and not previous:
            name,arguments = 'present_script_section',{'section_id':data['hosting_section']}
        elif "select_actor" in names and not previous:
            name, arguments = "select_actor", {"role_id": data["recommended_role_id"]}
        elif "speak_public" in names and data.get('response_required'):
            name, arguments = 'speak_public', {'content':'我听到你的询问了。我会说明自己亲自确认的情况，不替其他人作证。'}
        elif "search_scene" in names and data.get("search_targets") and not any(
            call.get('function',{}).get('name')=='search_scene' for message in messages for call in message.get('tool_calls',[])):
            name, arguments = "search_scene", {"target_id": data["search_targets"][0]["id"]}
        elif not previous or (len(previous) == 1 and data.get("public_allowed")):
            if data.get("public_allowed") and data.get("candidate_role_ids"):
                name, arguments = "public_exchange", {"target_role_id": data["candidate_role_ids"][0], "content": "请说明你亲自确认的时间线，我们再核对彼此掌握的证据。"}
            elif data.get("private_candidates"):
                name, arguments = "private_exchange", {"target_role_id": data["private_candidates"][0], "content": "你是否愿意私下核对当时亲自观察到的情况？"}
        raw_calls = [{"id": "echo_" + uuid.uuid4().hex, "type": "function",
                     "function": {"name": name, "arguments": json.dumps(arguments, ensure_ascii=False)}}] if name else []
        message = {"role": "assistant", "content": None if raw_calls else "本回合行动结束。", "tool_calls": raw_calls}
        if transport == "validated_action_json":
            return parse_json_reply(json.dumps({"content": message["content"] or "", "tool_calls":
                [{"name": name, "arguments": arguments}] if name else []}, ensure_ascii=False))
        return parse_native_message(message)
    async def chat(self, messages: list[dict[str, str]]) -> str:
        self.last_provider_invoked = True
        system = messages[0]["content"] if messages else ""
        role_name = "角色"
        for message in messages:
            if message["content"].startswith("[ROLE_MEMORY_DATA]\n"):
                records = json.loads(message["content"].split("\n", 1)[1])
                for record in records:
                    if record["kind"] == "role_profile":
                        role_name = json.loads(record["content"])["profile"].get("role_name") or role_name
        for line in system.splitlines():
            if line.startswith("角色名称："):
                role_name = line.split("：", 1)[1].strip()
                break
            if line.startswith("角色："):
                role_name = line.split("：", 1)[1].split("（", 1)[0].strip()
                break

        latest_user = ""
        for message in reversed(messages):
            if message["role"] == "user":
                latest_user = message["content"]
                break

        if "[AUTONOMOUS_DECISION]" in latest_user:
            target_role_id = ""
            target_name = "在场的人"
            channel = "public"
            for line in latest_user.splitlines():
                if line.startswith("轮转建议目标ID："):
                    target_role_id = line.split("：", 1)[1].strip()
                if line.startswith("轮转建议目标名称："):
                    target_name = line.split("：", 1)[1].strip()
                if line.startswith("轮转建议频道："):
                    channel = line.split("：", 1)[1].strip()
            return json.dumps(
                {
                    "action": "communicate",
                    "target_role_id": target_role_id,
                    "channel": channel,
                    "content": (
                        f"{role_name}看向{target_name}问道："
                        "你掌握的时间线里，哪一处最值得我们重新核对？"
                    ),
                    "notebook_entry": (
                        f"需要核对{target_name}掌握的时间线，"
                        "再判断其证词是否与当前线索冲突。"
                    ),
                },
                ensure_ascii=False,
            )
        if "[AUTONOMOUS_RESPONSE]" in latest_user:
            return f"{role_name}回答：我会说明自己确认的部分，但暂时不会替别人下结论。"
        if "[STAGE_VOTE]" in latest_user:
            candidates: list[str] = []
            for line in latest_user.splitlines():
                if line.startswith("- role_id="):
                    candidates.append(
                        line.split("=", 1)[1].split("；", 1)[0].strip()
                    )
            return candidates[1] if len(candidates) > 1 else candidates[0] if candidates else ""
        if "[INVESTIGATION_END_VOTE]" in latest_user:
            return "APPROVE"
        if "[WHISPER_INVITATION]" in latest_user:
            return "ACCEPT"
        if "[SEMANTIC_BOUNDARY_REVIEW]" in latest_user:
            return "ALLOW"
        if latest_user:
            return f"{role_name}沉吟片刻，说：我听见了你的话。眼下我只能根据自己知道的情况回应。"
        return f"{role_name}保持观察，没有贸然下结论。"
