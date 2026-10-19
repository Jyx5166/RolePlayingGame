from __future__ import annotations
import json
from typing import Any
from dm.task_evaluator import evaluate_task_check
from mechanics.search import SearchMechanic
from domain.state import ScenePhase


class SettlementRules:
    def _stage_vote_candidate_ids(self) -> list[str]:
        """All voters use the script's candidates, including an eligible self."""
        state = self._require_state()
        resolution = self._stage_flow_config().get("resolution", {})
        config = resolution.get("final_decision" if state.current_stage_num >= state.total_stages else "vote")
        return list(config.get("eligible_role_ids", [])) if isinstance(config, dict) else []

    def prepare_stage_resolution(self) -> dict[str, Any] | None:
        state = self._require_state()
        stage = state.current_stage_num
        existing = state.stage_resolutions.get(stage)
        if existing is not None:
            return self.get_stage_resolution()

        config = self._stage_flow_config().get("resolution")
        if not isinstance(config, dict):
            return None
        permission = self._require_permission()
        metric = dict(config["metric"])
        role_results: list[dict[str, Any]] = []
        stage_counts = state.role_event_counts.get(stage, {})
        for role_id in permission.role_ids:
            counts = stage_counts.get(role_id, {})
            reasons: list[dict[str, Any]] = []
            delta = 0
            for rule in config.get("scoring_rules", []):
                count = sum(
                    int(counts.get(str(event_type), 0))
                    for event_type in rule.get("event_types", [])
                )
                points = min(
                    count * int(rule.get("points_per_event", 0)),
                    int(rule.get("max_points", 0)),
                )
                if count or points:
                    reasons.append(
                        {
                            "label": str(rule["label"]),
                            "count": count,
                            "points": points,
                        }
                    )
                delta += points
            adjustment = config.get("role_adjustments", {}).get(role_id)
            if isinstance(adjustment, dict):
                adjustment_points = int(adjustment.get("points", 0))
                delta += adjustment_points
                reasons.append(
                    {
                        "label": str(adjustment.get("reason", "剧情修正")),
                        "count": 1,
                        "points": adjustment_points,
                    }
                )
            previous = state.role_scores.get(role_id, int(metric.get("initial", 0)))
            total = previous + delta
            state.role_scores[role_id] = total
            role_results.append(
                {
                    "role_id": role_id,
                    "role_name": permission.role_name(role_id),
                    "controller": (
                        "human"
                        if role_id == state.human_player_role_id
                        else "agent"
                    ),
                    "delta": delta,
                    "total": total,
                    "reasons": reasons,
                    "task_results": self._role_task_results(role_id, stage),
                }
            )

        is_final = stage >= state.total_stages
        vote_config = (
            config.get("final_decision")
            if is_final
            else config.get("vote")
        )
        vote: dict[str, Any] | None = None
        if isinstance(vote_config, dict):
            candidates = [
                {
                    "role_id": role_id,
                    "role_name": permission.role_name(role_id),
                    "public_identity": permission.role_by_id(role_id)["public_identity"],
                }
                for role_id in self._stage_vote_candidate_ids()
            ]
            vote = {
                "kind": "final" if is_final else "stage",
                "prompt": str(vote_config["prompt"]),
                "eligible_roles": candidates,
                "pending": True,
                "tie_breaker": "role_id_order",
                "tie_breaker_label": "最高票平票时按角色 ID 升序确定",
                "ballots": [],
                "selected_role_id": None,
                "selected_role_name": None,
                "outcome_text": "",
                "correct": None,
                "truth_revealed": False,
                "penalty": (
                    dict(vote_config.get("penalty", {}))
                    if not is_final
                    else None
                ),
                "applied_penalty": None,
            }

        resolution = {
            "stage": stage,
            "title": str(config["title"]),
            "metric": {
                "key": str(metric["key"]),
                "label": str(metric["label"]),
                "unit": str(metric["unit"]),
            },
            "role_results": role_results,
            "vote": vote,
            "resolved": vote is None,
        }
        state.stage_resolutions[stage] = resolution
        if vote is None:
            self._finalize_resolution_records(resolution)
        return self.get_stage_resolution()

    def get_stage_resolution(self) -> dict[str, Any] | None:
        state = self._require_state()
        resolution = state.stage_resolutions.get(state.current_stage_num)
        if resolution is None:
            return None
        public = self._copy_payload(resolution)
        for result in public.get("role_results", []):
            if result.get("role_id") != state.human_player_role_id:
                result.pop("task_results", None)
        vote = public.get("vote")
        if isinstance(vote, dict):
            public["vote"] = {
                key: value for key, value in vote.items()
                if key in {
                    "kind", "prompt", "eligible_roles", "pending", "ballots", "tally",
                    "selected_role_id", "selected_role_name", "outcome_text", "correct",
                    "truth_revealed", "penalty", "applied_penalty",
                    "tie_breaker", "tie_breaker_label",
                }
            }
        return public

    def stage_resolution_pending(self) -> bool:
        resolution = self.get_stage_resolution()
        vote = resolution.get("vote") if resolution else None
        return bool(isinstance(vote, dict) and (
            vote.get("pending") or not resolution.get("resolved") or not str(vote.get("outcome_text", "")).strip()
        ))

    async def cast_stage_vote(self, target_role_id: str) -> dict[str, Any]:
        state = self._require_state()
        if state.scene_phase != ScenePhase.DM_HOSTING:
            raise ValueError("当前不是 DM 结算投票环节")
        resolution = state.stage_resolutions.get(state.current_stage_num)
        if resolution is None:
            self.prepare_stage_resolution()
            resolution = state.stage_resolutions.get(state.current_stage_num)
        if not isinstance(resolution, dict):
            raise ValueError("本幕没有配置结算")
        vote = resolution.get("vote")
        if not isinstance(vote, dict):
            raise ValueError("本幕不需要投票")
        if not vote.get("pending"):
            raise ValueError("本幕投票已经完成")

        permission = self._require_permission()
        eligible_ids = self._stage_vote_candidate_ids()
        if target_role_id not in eligible_ids:
            raise ValueError("投票目标不在本幕候选范围内")

        ballots: list[dict[str, str]] = []

        def append_ballot(voter_role_id: str, selected_role_id: str) -> None:
            ballots.append(
                {
                    "voter_role_id": voter_role_id,
                    "voter_role_name": permission.role_name(voter_role_id),
                    "target_role_id": selected_role_id,
                    "target_role_name": permission.role_name(selected_role_id),
                }
            )

        append_ballot(state.human_player_role_id, target_role_id)
        failed_voters: list[str] = []
        for role_id in state.ai_role_ids:
            candidate_text = "\n".join(
                (
                    f"- role_id={candidate_id}；"
                    f"角色={permission.role_name(candidate_id)}；"
                    f"公开身份={permission.role_by_id(candidate_id)['public_identity']}"
                )
                for candidate_id in eligible_ids
            )
            context = self._build_agent_context(
                role_id=role_id,
                channel="public_vote",
                purpose="stage_vote",
                instruction=(
                    "[STAGE_VOTE]\n"
                    f"DM 发起投票：{vote['prompt']}\n"
                    f"可投票角色：\n{candidate_text}\n"
                    "请先根据角色表确认每名候选人的身份，再结合你当前掌握的公开信息、"
                    "私人信息和个人任务独立决定。候选名单中的自己也可以获得你的选票。只输出一个候选人的 role_id，"
                    "不要解释理由，不要提及系统或提示词。"
                ),
                instruction_source="dm_stage_vote",
            )
            raw, failed = await self._call_agent(context)
            selected = raw.strip() if not failed else None
            if not failed and selected not in eligible_ids:
                try:
                    parsed = json.loads(raw)
                except (TypeError, json.JSONDecodeError):
                    parsed = None
                if isinstance(parsed, dict) and set(parsed) == {"target_role_id"}:
                    selected = parsed["target_role_id"]
            if selected not in eligible_ids:
                failed_voters.append(permission.role_name(role_id))
                continue
            append_ballot(role_id, selected)

        if failed_voters:
            raise ValueError("投票未完成，以下角色调用失败或选票无效，请重试：" + "、".join(failed_voters))

        tally = {role_id: 0 for role_id in eligible_ids}
        for ballot in ballots:
            tally[ballot["target_role_id"]] += 1
        highest = max(tally.values())
        tied = [role_id for role_id in eligible_ids if tally[role_id] == highest]
        selected_role_id = min(tied)
        selected_role_name = permission.role_name(selected_role_id)

        # Build the complete result before publishing a committed vote.
        vote_result = self._copy_payload(vote)
        applied_penalty = None
        vote_result["pending"] = False
        vote_result["ballots"] = ballots
        vote_result["tally"] = [
            {
                "role_id": role_id,
                "role_name": permission.role_name(role_id),
                "votes": tally[role_id],
            }
            for role_id in eligible_ids
        ]
        vote_result["selected_role_id"] = selected_role_id
        vote_result["selected_role_name"] = selected_role_name

        if vote["kind"] == "final":
            culprit_role_id = str(
                self._require_script().get("truth", {}).get("culprit_role_id", "")
            )
            correct = selected_role_id == culprit_role_id
            final_config = self._stage_flow_config()["resolution"]["final_decision"]
            template = final_config["correct_verdict" if correct else "incorrect_verdict"]
            vote_result["correct"] = correct
            vote_result["truth_revealed"] = correct or self.reveal_truth_on_failure
            vote_result["outcome_text"] = str(template).format(
                selected_role_name=selected_role_name,
            )
        else:
            applied_penalty = self._build_vote_penalty(
                selected_role_id,
                selected_role_name,
                vote.get("penalty"),
            )
            vote_result["applied_penalty"] = applied_penalty
            if applied_penalty is not None:
                vote_result["outcome_text"] = (
                    f"投票结果：{selected_role_name}被施加“"
                    f"{applied_penalty['label']}”。{applied_penalty['description']}"
                )
            else:
                vote_result["outcome_text"] = f"投票结果：{selected_role_name}获得最高票。"

        if len(tied) > 1:
            vote_result["outcome_text"] += "（最高票平票，按已公布的角色 ID 升序规则裁决。）"
        if not str(vote_result["outcome_text"]).strip():
            raise ValueError("结局内容为空，投票结果尚未提交")
        vote.clear()
        vote.update(vote_result)
        if applied_penalty is not None:
            state.penalties.append(applied_penalty)
        resolution["resolved"] = True
        for ballot in ballots:
            self._queue_activity(
                actor_role_id=ballot["voter_role_id"],
                target_role_id=ballot["target_role_id"],
                event_type=(
                    "final_vote"
                    if vote["kind"] == "final"
                    else "stage_vote"
                ),
                channel="public_vote",
                summary=(
                    f"{ballot['voter_role_name']}投票给"
                    f"{ballot['target_role_name']}"
                ),
                details={
                    "target_role_id": ballot["target_role_id"],
                    "vote_kind": vote["kind"],
                },
            )
        state.audit_log.append(
            {
                "type": "stage_resolution",
                "stage": state.current_stage_num,
                "resolution": self._copy_payload(resolution),
            }
        )
        result_event = self._build_observed_event(
            actor_role_id=selected_role_id,
            event_type=(
                "final_vote_result"
                if vote["kind"] == "final"
                else "stage_vote_result"
            ),
            channel="public",
            content=str(vote["outcome_text"]),
        )
        self._broadcast_observed_event(result_event)
        self._finalize_resolution_records(resolution)
        return self.get_stage_resolution()

    def restore_role_activity_counts(self, activities: list[dict[str, Any]]) -> None:
        state = self._require_state()
        state.role_event_counts.clear()
        for activity in activities:
            stage = int(activity.get("stage", 1))
            role_id = str(activity.get("actor_role_id", ""))
            event_type = str(activity.get("event_type", ""))
            if not role_id or not event_type:
                continue
            if event_type == "search" and not activity.get("details", {}).get("clue"):
                continue
            stage_counts = state.role_event_counts.setdefault(stage, {})
            role_counts = stage_counts.setdefault(role_id, {})
            role_counts[event_type] = role_counts.get(event_type, 0) + 1

    def restore_stage_resolutions(self, events: list[dict[str, Any]]) -> None:
        state = self._require_state()
        state.stage_resolutions.clear()
        state.role_scores.clear()
        state.penalties.clear()
        for event in events:
            if event.get("type") != "stage_resolution":
                continue
            payload = event.get("payload", {})
            resolution = payload.get("resolution", payload)
            if not isinstance(resolution, dict) or "stage" not in resolution:
                continue
            state.stage_resolutions[int(resolution["stage"])] = self._copy_payload(
                resolution
            )
        for stage in sorted(state.stage_resolutions):
            resolution = state.stage_resolutions[stage]
            for result in resolution.get("role_results", []):
                state.role_scores[str(result["role_id"])] = int(result["total"])
            vote = resolution.get("vote")
            penalty = vote.get("applied_penalty") if isinstance(vote, dict) else None
            if isinstance(penalty, dict):
                state.penalties.append(dict(penalty))
        if (
            state.scene_phase == ScenePhase.DM_HOSTING
            and state.current_stage_num not in state.stage_resolutions
        ):
            self.prepare_stage_resolution()
        self._apply_stage_penalties(state.current_stage_num)
        self._refresh_current_agent_objectives()

    def _build_vote_penalty(
        self,
        target_role_id: str,
        target_role_name: str,
        config: Any,
    ) -> dict[str, Any] | None:
        if not isinstance(config, dict) or not config:
            return None
        state = self._require_state()
        target_stage = state.current_stage_num + int(
            config.get("target_stage_offset", 1)
        )
        if target_stage > state.total_stages:
            return None
        return {
            "source_stage": state.current_stage_num,
            "target_stage": target_stage,
            "target_role_id": target_role_id,
            "target_role_name": target_role_name,
            "label": str(config["label"]),
            "description": str(config["description"]),
            "search_ap_reduction": int(config.get("search_ap_reduction", 0)),
            "extra_task": str(config.get("extra_task", "")).strip(),
            "completion_checks": self._copy_payload_list(config.get("completion_checks", [])),
        }

    def _apply_stage_penalties(self, stage: int) -> None:
        state = self._require_state()
        try:
            search = self.mechanic_registry.get("search")
        except KeyError:
            search = None
        for penalty in state.penalties:
            if int(penalty.get("target_stage", 0)) != stage:
                continue
            key = (
                f"{penalty.get('source_stage')}:{stage}:"
                f"{penalty.get('target_role_id')}:{penalty.get('label')}"
            )
            if key in state.applied_penalty_keys:
                continue
            reduction = int(penalty.get("search_ap_reduction", 0))
            if reduction > 0 and isinstance(search, SearchMechanic):
                search.reduce_ap(stage, str(penalty["target_role_id"]), reduction)
            state.applied_penalty_keys.add(key)

    def _role_penalties_for_stage(
        self,
        role_id: str,
        stage: int,
    ) -> list[dict[str, Any]]:
        state = self._require_state()
        return [
            dict(penalty)
            for penalty in state.penalties
            if str(penalty.get("target_role_id")) == role_id
            and int(penalty.get("target_stage", 0)) == stage
        ]

    def _task_with_penalties(self, role_id: str, task: str, stage: int) -> str:
        extras = [
            str(penalty.get("extra_task", "")).strip()
            for penalty in self._role_penalties_for_stage(role_id, stage)
            if str(penalty.get("extra_task", "")).strip()
        ]
        if not extras:
            return task
        return (
            f"{task}\n附加惩罚任务："
            + "；".join(extras)
        )

    def _role_task_results(self, role_id: str, stage: int) -> list[dict[str, Any]]:
        state = self._require_state()
        role = self._require_permission().role_by_id(role_id)
        config = self._require_script().get("stage_flow", {}).get(f"stage_{stage}", {})
        counts = state.role_event_counts.get(stage, {}).get(role_id, {})
        results = [{
            "kind": "narrative", "label": "个人叙事目标",
            "description": config.get("personal_tasks", {}).get(role_id) or role.get("hidden_goal") or "推进角色调查",
            "status": "manual_review",
        }]
        for check in config.get("personal_task_checks", {}).get(role_id, []):
            results.append({"kind": "quantified", **evaluate_task_check(
                check, role_id=role_id, stage=stage, counts=counts, audit_log=state.audit_log,
            )})
        for penalty in self._role_penalties_for_stage(role_id, stage):
            if not penalty.get("extra_task"):
                continue
            checks = [evaluate_task_check(check, role_id=role_id, stage=stage, counts=counts, audit_log=state.audit_log)
                      for check in penalty.get("completion_checks", [])]
            results.append({
                "kind": "penalty", "label": penalty["label"], "description": penalty["extra_task"],
                "status": ("completed" if all(check["status"] == "completed" for check in checks) else "failed") if checks else "manual_review",
                "checks": checks,
            })
        return results

    def _refresh_current_agent_objectives(self) -> None:
        state = self._require_state()
        permission = self._require_permission()
        for role_id in state.ai_role_ids:
            role = permission.role_by_id(role_id)
            self.agent_pool.set_objective(
                role_id,
                state.current_stage_num,
                self._task_with_penalties(
                    role_id,
                    self._script_personal_task(
                        self._require_script(),
                        role,
                        state.current_stage_num,
                    ),
                    state.current_stage_num,
                ),
            )

    def _finalize_resolution_records(self, resolution: dict[str, Any]) -> None:
        state = self._require_state()
        vote = resolution.get("vote")
        outcome = (
            str(vote.get("outcome_text", "")).strip()
            if isinstance(vote, dict)
            else ""
        )
        metric = resolution["metric"]
        result_by_role = {
            str(result["role_id"]): result
            for result in resolution.get("role_results", [])
        }
        for role_id in [
            state.human_player_role_id,
            *state.ai_role_ids,
        ]:
            result = result_by_role.get(role_id)
            if result is None:
                continue
            reasons = "；".join(
                (
                    f"{reason['label']} {reason['count']} 次，"
                    f"{int(reason['points']):+d}{metric['unit']}"
                )
                for reason in result.get("reasons", [])
            ) or "本幕没有产生可计分操作"
            content = (
                f"本幕变化：{int(result['delta']):+d}{metric['unit']}；"
                f"累计{metric['label']}：{result['total']}{metric['unit']}。"
                f"计分依据：{reasons}。"
                + (f"\nDM 结算：{outcome}" if outcome else "")
            )
            status_labels = {"completed": "已完成", "failed": "未完成", "manual_review": "需人工评审"}
            content += "\n任务判定：" + "；".join(
                f"{task['label']}：{status_labels[task['status']]}" for task in result.get("task_results", [])
            )
            self._queue_notebook(
                role_id=role_id,
                section="automatic",
                source_type="stage_resolution",
                source_key=f"stage-resolution:{resolution['stage']}:{role_id}",
                title=f"{resolution['title']} · 个人结果",
                content=content,
            )

    @staticmethod
    def _copy_payload(value: dict[str, Any]) -> dict[str, Any]:
        return json.loads(json.dumps(value, ensure_ascii=False))

    @staticmethod
    def _copy_payload_list(value: list[dict[str, Any]]) -> list[dict[str, Any]]:
        return json.loads(json.dumps(value, ensure_ascii=False))

    @staticmethod
    def _script_personal_task(
        script: dict[str, Any],
        role: dict[str, Any],
        stage: int,
    ) -> str:
        configured = (
            script.get("stage_flow", {})
            .get(f"stage_{stage}", {})
            .get("personal_tasks", {})
            .get(role["role_id"])
        )
        task = str(
            configured
            or role.get("hidden_goal")
            or "根据当前身份和已知信息推进调查。"
        )
        checks = script.get("stage_flow", {}).get(f"stage_{stage}", {}).get("personal_task_checks", {}).get(role["role_id"], [])
        return task + ("\n量化子目标：" + "；".join(check["label"] for check in checks) if checks else "")
