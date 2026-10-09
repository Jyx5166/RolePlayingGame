from __future__ import annotations

import json

from .base import BaseLLM


class EchoLLM(BaseLLM):
    provider = "echo"
    model = "echo"
    async def chat(self, messages: list[dict[str, str]]) -> str:
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
