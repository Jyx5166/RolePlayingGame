"""Render observed remediation results without model calls or evidence edits."""
from __future__ import annotations

import hashlib
import html
import json
from decimal import Decimal
from pathlib import Path

PROJECT = Path(__file__).resolve().parents[2]
ROOT = PROJECT / "backend/data/verification/final-retest-20261015-live"
PROBES = PROJECT / "backend/data/verification/source-probes-20261015-live"
DEST = PROJECT / "private-docs/verification/2026-10-15"


def load(path):
    return json.loads(path.read_text(encoding="utf-8"))


def main():
    report = load(ROOT / "report.json")
    ledger = load(PROJECT / "backend/data/verification/blind-five-20261014-live/requests.json")
    tests_path = PROJECT / "backend/reports/remediation-post-source-fix-final-20261015.json"
    tests = load(tests_path)
    reviews = {name: load(ROOT / name) for name in ("flow-review.json", "semantic-review.json", "fee-review.json")}
    flow = reviews["flow-review.json"]["summary"]
    if reviews["fee-review.json"]["snapshot"]["active_ledger_sha256"] != hashlib.sha256((PROJECT / "backend/data/verification/blind-five-20261014-live/requests.json").read_bytes()).hexdigest():
        raise ValueError("Fee review is not for the final ledger")
    probes = load(PROBES / "report.json") if (PROBES / "report.json").exists() else None
    probe_review = load(PROBES / "source-review.json") if (PROBES / "source-review.json").exists() else None
    placeholders = [row for row in ledger["calls"] if row.get("accounting_placeholder")]
    hold = sum((Decimal(row["accounted_upper_cny"]) for row in placeholders), Decimal(0))
    confirmed = [row for row in ledger["calls"] if not row.get("accounting_placeholder")]
    cases = [{"script_id": game["script_id"], "title": game["title"], "status": game["status"],
              "player_correct": game.get("blind_vote", {}).get("correct"),
              "ai_ballots": sum(ballot["voter_role_id"] != game["player_role_id"] for ballot in game.get("ending", {}).get("final_decision", {}).get("ballots", [])),
              "ending_check": game.get("ending_check"), "workflow_problems": game.get("workflow_problems"),
              "input_failures": game.get("input_failures"), "new_calls": game["paid_request_count"],
              "upper_cny": game["upper_cost_cny"]} for game in report["games"]]
    evidence_paths = [ROOT / "report.json", ROOT / "flow-review.json", ROOT / "semantic-review.json", ROOT / "fee-review.json", tests_path]
    if probes:
        evidence_paths.append(PROBES / "report.json")
    if probe_review:
        evidence_paths.append(PROBES / "source-review.json")
    main_calls = sum(case["new_calls"] for case in cases)
    probe_calls = sum(game["paid_request_count"] for game in probes["games"]) if probes else 0
    if main_calls != reviews["flow-review.json"]["input_isolation_review"]["actual_wire_inputs"] or flow["persisted_ai_ballots"] != sum(case["ai_ballots"] for case in cases):
        raise ValueError("Observed counts disagree with flow review")
    supplemental_status = ("已审阅，保留误拦与角色一致性警示" if probe_review.get("summary", {}).get("residual_caveats") else "已完成审阅") if probe_review else "待完成审阅"
    supplemental_text = f"补充公开回应试验调用{probe_calls}次；独立审阅状态：{html.escape(supplemental_status)}。" if probes else "补充公开回应试验尚未运行。"
    summary = {"client_date": "2026-10-15", "scope": "targeted final-stage regression from prior blind-game snapshots",
               "acceptance": {"flow": reviews["flow-review.json"]["status"],
                              "initial_content": "FAILED_TWO_COMMITTED_SOURCE_ERRORS",
                              "supplemental_source": supplemental_status,
                              "unconditional_roleplay_pass": False},
               "model": report["model"], "cases": cases, "full_backend_regression": tests,
               "original_database_unchanged": report["original_db_unchanged"],
               "fees": {"hard_cap_cny": "20", "confirmed_guarded_calls": len(confirmed),
                        "prior_confirmed_calls": 220, "five_case_final_retest_calls": main_calls,
                        "supplemental_public_probe_calls": probe_calls,
                        "unknown_incident_maximum_count_placeholders": len(placeholders),
                        "unknown_incident_full_reservation_cny": str(hold),
                        "known_usage_upper_cny": str(Decimal(ledger["accounted_upper_cny"]) - hold),
                        "cumulative_upper_cny": ledger["accounted_upper_cny"], "remaining_cny": ledger["remaining_cny"]},
               "reviews": reviews, "supplemental_probe_review": probe_review,
               "evidence_sha256": {str(path.relative_to(PROJECT)): hashlib.sha256(path.read_bytes()).hexdigest() for path in evidence_paths},
               "limitations": ["preserved prior player hypotheses; not a fresh full blind run", "one targeted public prompt per script",
                               "two content defects observed in initial retest remain in historical evidence", "source rules are narrow and do not prove universal absence of fabrication",
                               "no browser or WebSocket acceptance, no new wrong-ending sample", "unknown incident usage retained at full upper bound"]}
    DEST.mkdir(parents=True, exist_ok=True)
    (DEST / "blind-five-remediation.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    rows = "".join(f'<tr><td>{html.escape(case["title"])}</td><td>{"正确" if case["player_correct"] is True else "错误" if case["player_correct"] is False else "未产生"}</td><td>{case["ai_ballots"]}</td><td>{html.escape((case["ending_check"] or {}).get("status", "未产生"))}</td><td>{case["new_calls"]}</td><td>¥{case["upper_cny"]}</td></tr>' for case in cases)
    details = "".join(f'<details><summary>{html.escape(name)}</summary><pre>{html.escape(json.dumps(value, ensure_ascii=False, indent=2))}</pre></details>' for name, value in {**reviews, "supplemental_probe_review": probe_review}.items())
    document = f'''<!doctype html><html lang="zh-CN"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>五剧本修复与真实模型复验 · 2026-10-15</title><style>
body{{max-width:1100px;margin:36px auto;padding:0 24px;background:#0c1716;color:#e3e9e4;font:16px/1.8 system-ui,sans-serif}}h1{{font-size:28px;color:#e5c67e}}h2{{font-size:21px;margin-top:30px}}a{{color:#e5c67e}}table{{width:100%;border-collapse:collapse;font-size:14px}}td,th{{border:1px solid #40514a;padding:9px;text-align:left}}th{{background:#1a2b25}}.result{{background:#182c23;border-left:4px solid #d3b56f;padding:16px}}.finding{{background:#352622;border-left:4px solid #b7725e;padding:16px}}pre{{white-space:pre-wrap;overflow-wrap:anywhere;font-size:13px}}summary{{cursor:pointer;color:#e5c67e}}code{{overflow-wrap:anywhere}}</style><body>
<h1>五剧本修复与真实模型复验</h1><p>2026-10-15 · DeepSeek V4 Pro · 含剧透 · 所有付费调用共用原 ¥20 账本。</p>
<p class="result"><strong>最终阶段流程：{flow['persisted_endings']}/{len(cases)}局进入已持久化的结局复盘，已提交{flow['persisted_ai_ballots']}张AI票。流程审阅：{html.escape(reviews['flow-review.json']['status'])}。</strong><br><strong>首次内容审阅未通过，保留两处来源错误；补充试验：{html.escape(supplemental_status)}。</strong><br>财务审阅：{html.escape(reviews['fee-review.json']['status'])}。不能把终局通过等同于扮演质量完全通过。</p>
<h2>修复内容</h2><ul><li>同一幕的投票候选由同一个函数提供给玩家、AI提示、原生工具enum、决策验证和结算。剧本允许时可以投自己；未知或不合资格角色会拒绝，整批非法票不落盘。</li>
<li>必须回应时优先只开放speak_public；普通正文不能冒充执行。真实工具提交后才恢复其他工具，并在原有有限回合内处理拒绝；明确1–500字限制。</li>
<li>历史对话携带说话人和来源，以引用消息提供；角色记忆区分本人知识、他人证词及真实行动收据。增加身份及第一人称经历归属校验。</li>
<li>转交、持有及旧证词归属的来源检查以授权资料和真实收据为依据；旧的本人说法不会因重复而变成已验证事实。规则有明确语义覆盖范围。</li></ul>
<h2>五局真实复验</h2><table><tr><th>剧本</th><th>新玩家指认</th><th>已提交AI票</th><th>结局机械核验</th><th>新调用</th><th>费用上界</th></tr>{rows}</table>
<p>五局终幕重点复验共{main_calls}次新模型调用。独立流程审阅另外检查原生返回、工具收据、玩家实际事件、集体票决提交、数据库与快照的replay状态；不只检查模型输出和进程退出码。</p>
<h2>保留的失败与补修验证</h2><p class="finding">首轮真实复验中，陈澄仍增加无依据的“21:50交应急门钥匙”；孟岚仍将姜峤的印泥经历归到自己。两条都曾真实发布。它们没有泄露私人答案，但属于来源或身份归属错误。原始五局结果完整保留。</p>
<p>{supplemental_text}</p>
<p>补充试验仅检查公开发言，不算新的盲玩或结局样本。是否被拦截、是否在有限回合内生成合格回应，以及是否仍有问题，以页面底部的 supplemental_probe_review 为准。</p>
<p>补充旧宅试验还暴露一次归属校验误拦：相似的普通否认句被当成身份错用。角色随后改写并成功提交。对普通否认的最后修正通过本地回归，之后未再付费复验；角色防御性否认与自身记忆的一致性仍有警示，未将其包装成全面扮演通过。</p>
<h2>回归与证据边界</h2><p>最终完整后端回归：<strong>{tests['tests']}项，{'全部通过' if tests['passed'] else '存在失败'}</strong>，入口强制Echo及隔离数据库。新回归覆盖候选一致性、非法票不提交、工具未执行、身份误用、无来源交接、来源归属、防止本地付费配置进入测试。</p>
<p>复制上轮五个失败的最终场景，保留之前调查假设，并用针对历史错误的提示复查。重新生成最终玩家判断，但此前假设中已包含正确嫌疑，因此不能称作从第一幕重新盲玩。本轮未做浏览器/WS、多个种子或新的错误结局分支；进入的是预置剧本结局，没有新增结局后自由表演样本。原始数据库及剧本正文保持不变。</p>
<h2>费用及测试隔离失误</h2><p><strong>累计保守上界 ¥{ledger['accounted_upper_cny']}，剩余 ¥{ledger['remaining_cny']}，低于 ¥20。</strong>包括{len(confirmed)}次有账本记录的真实调用，以及一次测试隔离失误的未知用量预留 ¥{hold}。该预留按最多20次、每次完整23000输入/8192输出计入；20是上界占位数，不是已确认的调用次数。误调用的精确次数与用量无法恢复，未虚构用量或释放预留。</p>
<p>误调用完整时间窗位于北京时间23:19–23:20，按已核实的空闲缓存未命中费率4.5/13.5元每百万tokens留足上限；原220条记录保持不变。新调用继续按更高的9/27元单价逐次预留再发送，未知请求保留全额。参见<a href="https://api-docs.deepseek.com/zh-cn/quick_start/pricing/">官方价格说明</a>。测试夹具已补Echo强制配置与禁网回归。没有用账户余额差推算精确实扣。</p>
<h2>独立审阅与完整证据</h2><p><a href="blind-five-remediation.json">机器可读完整摘要</a> · <a href="../2026-10-14/blind-five-acceptance.html">上轮原始失败报告</a>。证据目录：<code>{html.escape(str(ROOT))}</code>；补充来源试验：<code>{html.escape(str(PROBES))}</code>。</p>{details}</body></html>'''
    (DEST / "blind-five-remediation.html").write_text(document, encoding="utf-8")
    print(json.dumps({"report": str(DEST / "blind-five-remediation.html"), "fees": summary["fees"]}, ensure_ascii=False))


if __name__ == "__main__":
    main()
