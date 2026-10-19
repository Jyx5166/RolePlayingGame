from __future__ import annotations

from dataclasses import dataclass
from difflib import SequenceMatcher
import re
from typing import Any, Literal


@dataclass(frozen=True)
class ValidationResult:
    passed: bool
    message: str | None = None
    category: Literal["ok", "hard_constraint", "role_attribution", "unsupported_personal_action"] = "ok"


class SpeechValidator:
    def __init__(self, script: dict[str, Any]) -> None:
        self._hard_constraints = script.get("hard_constraints", [])
        self._role_names = {role["role_id"]: role["role_name"] for role in script.get("roles", [])}

    def validate_human_speech(self, role_id: str, stage: int, content: str) -> ValidationResult:
        result = self._check_hard_constraints(role_id, stage, content)
        if result.passed:
            return result
        return ValidationResult(True, result.message, "hard_constraint")

    def validate_ai_speech(self, role_id: str, stage: int, content: str) -> ValidationResult:
        return self._check_hard_constraints(role_id, stage, content)

    def validate_role_attribution(self, role_id: str, stage: int, content: str,
                                  records: list[dict[str, Any]]) -> ValidationResult:
        """Reject explicit identity swaps and narrow provenance contradictions.

        This is not a general truth detector. Denials, concealment, hypotheses
        and distorted testimony are still allowed; invented affirmative
        transfer/possession events require an authorized personal source.
        """
        for other_id, name in self._role_names.items():
            if other_id == role_id:
                continue
            escaped = re.escape(name)
            if re.search(rf"^\s*{escaped}\s*[:：]|(?:^|[，。！？\n])\s*(?:我是|我叫|本人是|本人叫){escaped}(?:[，。！？\s]|$)", content):
                return ValidationResult(False, "发言使用了其他角色的身份；请以当前角色回应或明确引用原话。", "role_attribution")

        visible = [record for record in records if int(record.get("stage", 1)) <= stage]
        own_sources = []
        own_name = self._role_names.get(role_id, role_id)
        for record in visible:
            kind = record.get("kind")
            own_perspective = record.get("first_person_role_id", record.get("owner_role_id") if kind == "role_knowledge" else "") == role_id
            if kind == "role_knowledge" and own_perspective and record.get("epistemic_status") != "role_objective":
                own_sources.append(record["content"])
            elif kind in {"observed_action", "verified_action"} and record.get("event_verified") is True and record.get("actor_role_id") == role_id:
                own_sources.append(record["content"])
            elif kind == "search_fact" and record.get("owner_role_id") == role_id:
                if own_perspective:
                    own_sources.append(record["content"])
                else:
                    # Holding the clue does not make its narrator the holder.
                    # Neutral scene evidence must explicitly name this actor.
                    for sentence in re.split(r"[。！？\n]", record["content"]):
                        if re.search(re.escape(own_name) + r"(?:本人)?(?:把|将|持有|保管|拿着|交给|递给|转交)", sentence):
                            own_sources.append(sentence)
        own_text = self._normalize("\n".join(own_sources).replace("你", "我"))
        own_action_receipts = {record["content"] for record in visible
                               if record.get("kind") in {"observed_action", "verified_action"}
                               and record.get("event_verified") is True and record.get("actor_role_id") == role_id}
        for record in visible:
            speaker = record.get("speaker_role_id") or record.get("actor_role_id")
            if record.get("kind") != "testimony" or not speaker or speaker in {role_id, "unknown"}:
                continue
            name = str(record.get("speaker_role_name") or record.get("actor_role_name") or self._role_names.get(speaker, ""))
            for fragment in self._personal_fragments(record["content"]):
                if fragment in own_text:
                    continue
                for sentence in re.split(r"[。！？\n]", content):
                    if re.search(r"不是来自|不来自|不属于|并非|无法确认|不能确认|不确定|可能|也许|假如|如果|假设", sentence):
                        continue
                    copied = fragment in self._normalize(sentence) or any(
                        abs(len(fragment) - len(candidate)) <= 4 and SequenceMatcher(None, fragment, candidate).ratio() >= 0.9
                        for candidate in self._personal_fragments(sentence))
                    if copied and not self._attributed(sentence, name):
                        return ValidationResult(False, "发言把其他角色的第一人称原话归给了自己；请注明说话人或改为自己的已知经历。", "role_attribution")
            for sentence in re.split(r"[。！？；\n]", content):
                if (not self._attributed(sentence, name)
                        and self._same_personal_property(record["content"], sentence)
                        and not any(self._same_personal_property(source.replace("你", "我"), sentence) for source in own_sources)):
                    return ValidationResult(False, "发言把其他角色的个人物品或身体痕迹归给了自己；旧的本人证词不能代替自身授权来源。", "role_attribution")

        # Changing a preamble from 'confirmed' to 'experienced' does not turn an
        # unsupported past transfer into a sourced event. Prior self testimony
        # is deliberately excluded from own_sources.
        names = "|".join(re.escape(name) for name in self._role_names.values())
        if names:
            transfers = re.finditer(rf"(?:把|将)([^，。；！？\n]{{1,18}}?)(?:交给|递给|转交给|借给|还给|归还给)(?:了)?({names})", content)
            for match in transfers:
                prefix = re.split(r"[。！？\n]", content[:match.start()])[-1]
                if not self._affirmative_own_action(prefix, role_id):
                    continue
                obj, target = map(self._normalize, match.groups())
                supported = False
                for source in own_sources:
                    text = source.replace("你", "我")
                    relation = re.search(re.escape(obj) + r".{0,12}(?:交给|递给|转交给|借给|还给|归还给)了?" + re.escape(target), self._normalize(text))
                    if relation and (source in own_action_receipts or self._affirmative_own_action(self._normalize(text)[:relation.start()], role_id)):
                        supported = True
                        break
                if not supported:
                    return ValidationResult(False, "没有自身授权来源支持这项已发生的转交动作；旧的本人证词不能作为依据，请注明实际来源或保留未知。", "unsupported_personal_action")
        for match in re.finditer(r"我(?:一直|当时|确实|亲自)*(?:持有|保管|拿着)([^，。；！？\n]{1,18})", content):
            prefix = re.split(r"[。！？\n]", content[:match.start()])[-1] + "我"
            if self._affirmative_own_action(prefix, role_id) and self._normalize(match.group(1)) not in own_text:
                return ValidationResult(False, "没有自身授权来源支持这项已发生的持有动作。", "unsupported_personal_action")
        return ValidationResult(True)

    def _affirmative_own_action(self, prefix: str, role_id: str) -> bool:
        if self._attributed(prefix, ""):
            return False
        clause = re.split(r"[，；]", prefix)[-1]
        if re.search(r"(?:没|未|不曾|并非|不是|是否|有没有|可能|也许|假如|如果|假设|倘若|打算|计划|准备|将会|明天|稍后|可以谎称|无法确认|不能确认|不确定)", clause):
            return False
        subjects = [(match.start(), "self") for match in re.finditer(r"我", prefix)]
        for identifier, name in self._role_names.items():
            subjects.extend((match.start(), "self" if identifier == role_id else "other") for match in re.finditer(re.escape(name), prefix))
        clause_offset = len(prefix) - len(clause)
        subjects.extend((clause_offset + match.start(), "other") for match in re.finditer(r"(?:他|她|对方|别人|某人)", clause))
        return bool(subjects and max(subjects)[1] == "self")

    @classmethod
    def _same_personal_property(cls, source: str, candidate: str) -> bool:
        def spans(text: str):
            for sentence in re.split(r"[。！？；\n]", text):
                for match in re.finditer(r"我(?:的)?([\u4e00-\u9fff]{2})", sentence):
                    anchor = match.group(1)
                    if anchor in {"亲自", "本人", "确实", "当时", "当晚", "曾经", "可以", "不会", "看到", "听到", "没有", "只能", "打算", "认为"}:
                        continue
                    content = sentence[match.start():match.start()+120]
                    if cls._generic_stance(content):
                        continue
                    if re.search(r"可能|也许|不确定|无法确认|如果|假设|打算|计划", content):
                        continue
                    if not any(not re.search(r"不是|并非|不$", content[max(0, relation.start()-3):relation.start()])
                               for relation in re.finditer(r"是|来自|源于", content)):
                        continue
                    normalized = cls._normalize(content).replace("的", "")
                    yield anchor, {normalized[index:index+2] for index in range(len(normalized)-1)}
        for anchor, tokens in spans(source):
            for other_anchor, other_tokens in spans(candidate):
                overlap = len(tokens & other_tokens)
                if anchor == other_anchor and overlap >= 7 and overlap / max(1, min(len(tokens), len(other_tokens))) >= 0.4:
                    return True
        return False

    @staticmethod
    def _normalize(content: str) -> str:
        return re.sub(r"[^\w\u4e00-\u9fff]", "", content).replace("我的", "我")

    @classmethod
    def _personal_fragments(cls, content: str) -> list[str]:
        fragments = []
        for clause in re.split(r"[，,；;。！？\n]", content):
            match = re.search(r"我.{11,70}", clause)
            if not match or cls._generic_stance(match.group()) or re.search(
                    r"我.{0,12}(?:没|未|不曾|从未|并非|不是|不确定|无法确认|不能确认|不知道|不清楚)", match.group()):
                continue
            fragments.append(cls._normalize(match.group()))
        return fragments

    @staticmethod
    def _generic_stance(content: str) -> bool:
        return bool(re.match(r"我(?:会|将|想|愿|准备|打算|只能|只愿|只说明|认为|觉得|推测|建议|能|可以|不(?:知道|清楚|确定|认为|会|能)|(?:没|没有|未)(?:亲眼|亲自)?(?:看到|看见|听到|听见|证实|确认))", content))

    def _attributed(self, sentence: str, name: str) -> bool:
        if name:
            return bool(re.search(re.escape(name) + r".{0,6}(?:说|称|表示|提到|证词|原话|承认|[:：][“「\"])", sentence))
        return bool(re.search(r"(?:他|她|对方)(?:说|称|声称)|据[^，。；！？]{1,15}所说", sentence)
                    or any(re.search(re.escape(speaker) + r".{0,6}(?:说|称|表示|提到|证词|原话|承认)", sentence)
                           for speaker in self._role_names.values()))

    def _check_hard_constraints(self, role_id: str, stage: int, content: str) -> ValidationResult:
        normalized = content.lower()
        for constraint in self._hard_constraints:
            target_role = constraint.get("role_id", "*")
            if target_role not in ("*", role_id):
                continue
            until_stage = int(constraint.get("until_stage", 0))
            if stage >= until_stage:
                continue
            for keyword in constraint.get("keywords", []):
                if str(keyword).lower() in normalized:
                    return ValidationResult(
                        False,
                        constraint.get("message", "发言包含当前阶段不应知道的信息。"),
                        "hard_constraint",
                    )
        return ValidationResult(True)
