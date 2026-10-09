from __future__ import annotations


class TurnManager:
    def __init__(self, role_names: dict[str, str], max_speakers: int = 2) -> None:
        self.role_names = role_names
        self.max_speakers = max_speakers

    async def determine_speakers(
        self,
        ai_role_ids: list[str],
        public_history: list[dict[str, str]],
        trigger: dict[str, str],
    ) -> list[str]:
        content = trigger.get("content", "")
        mentioned = self.mentioned_speakers(content, ai_role_ids)
        if mentioned:
            return mentioned[: self.max_speakers]

        if not ai_role_ids:
            return []
        return ai_role_ids[:1]

    def mentioned_speakers(self, content: str, ai_role_ids: list[str]) -> list[str]:
        result: list[str] = []
        lowered = content.lower()
        for role_id in ai_role_ids:
            role_name = self.role_names.get(role_id, "")
            if role_id.lower() in lowered or (role_name and role_name in content):
                result.append(role_id)
        return result

    def plan_autonomous_turn(
        self,
        *,
        turn_number: int,
        stage: int,
        ai_role_ids: list[str],
        human_role_id: str,
        allow_private: bool,
    ) -> dict[str, str | int] | None:
        if not ai_role_ids:
            return None

        actor_index = turn_number % len(ai_role_ids)
        actor_role_id = ai_role_ids[actor_index]
        ask_human = turn_number % (len(ai_role_ids) + 1) == 0
        if ask_human or len(ai_role_ids) == 1:
            target_role_id = human_role_id
        else:
            target_role_id = ai_role_ids[(actor_index + 1) % len(ai_role_ids)]

        channel = (
            "private"
            if allow_private
            and target_role_id != human_role_id
            and turn_number % 3 == 2
            else "public"
        )
        return {
            "turn_number": turn_number + 1,
            "stage": stage,
            "actor_role_id": actor_role_id,
            "target_role_id": target_role_id,
            "channel": channel,
        }
