"""Deterministic input-boundary and long-archive baselines; no paid requests."""
from __future__ import annotations

import argparse
import asyncio
import json
import sys
import time
from pathlib import Path

PROJECT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT / "backend" / "app"))

from agent.context import AgentContextBroker
from agent.instance import AgentInstance
from llm.base import BaseLLM
from llm.budget import ContextBudget, estimate_tokens


class CaptureLLM(BaseLLM):
    async def chat(self, messages):
        self.messages = messages
        return "不知情的信息不能推断为事实。"


async def run():
    roles = ["doctor", "lawyer", "steward"]
    broker = AgentContextBroker(roles)
    samples = []
    for index in range(30):
        role = roles[index % len(roles)]
        stage = (index // 3) % 3 + 1
        llm = CaptureLLM()
        agent = AgentInstance(role, "Fixed policy", llm)
        agent.set_current_stage(stage)
        own = f"AUTHORIZED_{index}"
        excluded = [f"FOREIGN_{index}", f"FUTURE_{index}", f"DM_ONLY_{index}"]
        agent.inject_info([
            {"content": own, "unlock_stage": stage, "visibility": "self_only", "owner_role": role},
            {"content": excluded[0], "unlock_stage": stage, "visibility": "self_only", "owner_role": roles[(index + 1) % 3]},
            {"content": excluded[1], "unlock_stage": stage + 1, "visibility": "self_only", "owner_role": role},
            {"content": excluded[2], "unlock_stage": stage, "visibility": "dm_only", "owner_role": role},
        ], stage)
        agent.restore_runtime_state(json.loads(json.dumps(agent.export_runtime_state())))
        context = broker.build(role_id=role, stage=stage, channel="public", purpose="baseline", instruction="核对授权事实")
        await agent.respond(context)
        actual = json.dumps(llm.messages)
        samples.append({"role_id": role, "stage": stage, "authorized_present": own in actual,
                        "excluded_absent": all(marker not in actual for marker in excluded)})
    stress = []
    for count in (100, 1000, 10000):
        llm = CaptureLLM()
        llm.budget = ContextBudget(8192, 5000, 2048, 512)
        agent = AgentInstance("doctor", "Fixed policy", llm)
        agent.remember_private_exchange(1, "Lawyer", "received", "保险库编号 K-1937")
        for index in range(count):
            agent.remember_private_exchange(1, "Lawyer", "received", f"其他话题 {index} " + "x" * 80)
        context = broker.build(role_id="doctor", stage=1, channel="public", purpose="stress", instruction="回忆保险库编号")
        started = time.perf_counter()
        await agent.respond(context)
        stress.append({"archive_count": count + 1, "early_topic_recalled": "K-1937" in str(llm.messages),
                       "estimated_input_tokens": estimate_tokens(llm.messages), "input_limit": 5000,
                       "selection_ms": round((time.perf_counter() - started) * 1000, 2),
                       "selected_count": len(agent.last_prepared.selection["selected_source_keys"]),
                       "omitted_count": len(agent.last_prepared.selection["omitted_source_keys"])})
    return {"paid_requests": 0, "sample_count": len(samples), "samples": samples,
            "authorized_recall_count": sum(item["authorized_present"] for item in samples),
            "input_isolation_pass_count": sum(item["excluded_absent"] for item in samples),
            "stress": stress, "estimator": "conservative_utf8_bytes", "not_provider_tokenization": True}


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--report", type=Path)
    args = parser.parse_args()
    report = asyncio.run(run())
    if args.report:
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    passed = report["authorized_recall_count"] == 30 and report["input_isolation_pass_count"] == 30
    passed = passed and all(item["early_topic_recalled"] and item["estimated_input_tokens"] <= item["input_limit"] for item in report["stress"])
    raise SystemExit(0 if passed else 1)
