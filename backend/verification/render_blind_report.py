"""Render the completed, bounded acceptance evidence without model calls."""
from __future__ import annotations

import hashlib
import html
import json
from pathlib import Path

PROJECT = Path(__file__).resolve().parents[2]
ROOT = PROJECT / "backend/data/verification/blind-five-20261014-live"
DEST = PROJECT / "private-docs/verification/2026-10-14"


def read(name):
    return json.loads((ROOT / name).read_text(encoding="utf-8"))


def main():
    report = read("report.json")
    fees = read("fee-review.json")
    role = read("semantic-role-ending-review.json")
    isolation = read("attempt2/semantic-isolation-review.json")
    games = [game for game in report["games"] if game.get("attempt") == "attempt2"]
    assert len(games) == 5 and role["status"] == "complete_review_of_attempt2"
    assert fees["status"] == "PASS" and fees["snapshot"]["request_count"] == len(read("requests.json")["calls"])
    unchanged = all(hashlib.sha256(json.dumps(json.loads((PROJECT / "backend/resources/scripts" / (game["script_id"] + ".json")).read_text(encoding="utf-8")), sort_keys=True, ensure_ascii=False).encode()).hexdigest() == game["source_sha256"] for game in games)
    assert unchanged
    summary = {
        "client_date": "2026-10-14", "review_status": "complete", "acceptance": "FAILED_GAMEPLAY_RELIABILITY",
        "model": report["model"], "reasoning_effort": "none", "budget_cap_cny": "20",
        "metrics": role["summary"], "isolation": isolation["summary"], "fees": fees["fee"],
        "paid_calls": fees["snapshot"]["request_count"], "automatic_api_retries": 0,
        "script_sources_unchanged": unchanged, "production_data_changed": False,
        "cases": [{"script_id": game["script_id"], "title": game["title"], "human_correct": game["blind_vote"]["correct"],
                   "game_status": game["status"], "committed_ending": False, "formal_paid_calls": game["paid_request_count"],
                   "formal_upper_cost_cny": game["upper_cost_cny"], "protocol_interruptions": game.get("protocol_interruptions", []),
                   "source_sha256": game["source_sha256"]} for game in games],
        "protocol": {"initial_pilot": "23 calls retained; four unused-null parser failures and one stale action failure",
                     "formal": "one recommended nonculprit player per script, all acts, real native role responses and independent final proposals",
                     "continuation": "silent_theater same game: removed complete Markdown envelope only, reused paid JSON; original 24 captures and 193 ledger rows preserved",
                     "fixture": "isolated SQLite; autonomy disabled; timer extended to 3600s then controlled timeout; native/YAML limits retained",
                     "output_cap": "4096 instead of production 8192; blind player input cap 64000, production actor input cap 23000",
                     "not_covered": report["protocol"]["not_covered"]},
        "evidence_root": str(ROOT),
        "evidence": {name: hashlib.sha256((ROOT / name).read_bytes()).hexdigest() for name in (
            "requests.json", "report.json", "fee-review.json", "semantic-role-ending-review.json", "attempt2/semantic-isolation-review.json")},
    }
    DEST.mkdir(parents=True, exist_ok=True)
    (DEST / "blind-five-acceptance.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    cases = {case["script_id"]: case for case in role["cases"]}
    rows = []
    for game in games:
        case = cases[game["script_id"]]
        speech = case["actual_public_speeches"]
        rows.append(f'<tr><td>{html.escape(game["title"])}</td><td>正确</td><td>{speech["committed_turns"]}/{speech["native_role_turns"]}</td><td>未提交</td><td>{game["paid_request_count"]}</td><td>¥{float(game["upper_cost_cny"]):.3f}</td></tr>')
    fee = fees["fee"]
    document = f'''<!doctype html><html lang="zh-CN"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>五部新剧本真实模型盲玩验收 · 2026-10-14</title>
<style>body{{max-width:1060px;margin:40px auto;padding:0 24px;color:#263238;font:16px/1.7 system-ui,sans-serif}}h1{{font-size:28px}}h2{{font-size:21px;margin-top:32px}}table{{border-collapse:collapse;width:100%;font-size:14px}}th,td{{padding:10px;border:1px solid #d8dfe3;text-align:left}}th{{background:#f1f5f7}}.status{{padding:16px;border-left:5px solid #b64033;background:#fff2ef}}code{{background:#f3f5f6;padding:2px 5px;overflow-wrap:anywhere}}a{{color:#1565a0}}</style><body>
<h1>五部新剧本真实模型盲玩验收</h1><p>2026-10-14 · DeepSeek V4 Pro · reasoning_effort=none · 最终证据报告（含剧透）。</p>
<p class="status"><strong>整体验收未通过：本样本内五次盲选均正确，五局终局结算均未完成。</strong><br>线索支持此模型独立求解；原生动作遵循、身份一致性和投票结算仍不稳定。已经停止付费测试，保留全部失败，没有替模型更改指认或选票。</p>
<h2>逐剧本实测结果</h2><table><tr><th>剧本</th><th>盲玩家最终指认</th><th>实际公开发言/角色回合</th><th>集体结算/结局</th><th>正式调用</th><th>正式费用上界</th></tr>{''.join(rows)}</table>
<p>本表为正式五局的 197 次请求；首轮 23 次协议试验另计，合计 220 次。公开发言分母按真实调度的角色回合计算，一次人类公开命令可能触发多人回应。不能把“工具调用完成”或模型自述“已发言”当作玩家收到的事件。</p>
<h2>独立推理</h2><p>盲玩家仅收到自身角色资料、玩家可见手记、实际搜得线索和已发生的交流。最终五次论证均引用已取得的证据，并排除主要替代嫌疑：雨夜核对存活/签收时间与实物封存；列车重建袭击、锁封和伪造票据顺序；深海结合阀位、操作者日志和工具痕迹；旧宅结合连续画面与工具路径；剧院区分灯光命令与机械回放、核对身份认证和接触物证。</p>
<p>这支持五部当前证据能被本模型解出。它是同一模型、每部一名推荐非凶手角色的一次试验，且提示尽量完整搜证；不能据此宣称人类难度适中、自然玩家均能通关或剧情已达到商业水准。所有剧本原始内容哈希未变。</p>
<h2>提前泄漏与私聊隔离</h2><p>正式 197 份真实调用输入中，60 份 DM 输入按其合法完整剧本权限排除；137 份角色/盲玩家输入未发现确定越权。32 次 DM 实际发布段落与当前幕的预置公开段落一致。120 次非参与者输入及关联工具/公开事件未见私聊编号曝光。复核没有把“正确猜到凶手”视为泄漏。</p>
<p>来源、幕数、接收者、独有原文与私聊标记检查，加上实际发言的语义审阅，在本轮样本中未发现提前泄露未来幕或其他角色私密内容。此结论有限于已运行输入和交流，不是对所有提问方式的安全保证。角色主动说谎或公开自身秘密属于扮演行为，应与越权输入分开判断。</p>
<h2>已复现问题及修复优先级</h2>
<p><strong>P1 · 最终投票阻断（5/5局）。</strong>18 次 AI 最终决策中，12 次给出合法选票，5 名凶手均投自己，1 次未调用投票工具。五次自投都违反实际提示中的候选列表。工具 schema 只约束角色ID为字符串，<code>runtime/decisions.py:35</code>只检查目标在整局角色表中，故返回17条成功 proposal receipt；这些均明确 <code>gameplay_committed=false</code>。<code>domain/settlement.py:199</code>才排除本人并校验候选，任一票失败即回滚整局；五次集体票决均未提交，无法进入复盘。应统一工具、提示、决策校验和结算的合法候选，并明确认罪/弃权的规则。</p>
<p>凶手终幕任务允许承认作案，而投票禁止自投，存在设计张力；这可以解释行为倾向，但不能抹去模型违反明确候选列表的事实。陶闻在投票时复制任瑞的第一人称辩解，未生成工具选票。上述失败均非输出截断或缺少主持准备步骤。</p>
<p><strong>P2 · 公开动作未提交。</strong>30 个真实原生角色回合只发布23条发言，7次为 <code>PUBLIC_RESPONSE_MISSING</code>。一些模型输出普通正文并声称已公开，实际只调用 <code>read_memory</code>；另有9次 <code>speak_public</code>参数超过500字被拒。应在有限回合内优先提交必需动作，统一长度约束并清楚呈现未执行状态。原生工具续接/修改与自动HTTP重试是不同计数。</p>
<p><strong>P2 · 角色身份与证词归属。</strong>孟岚实际公开把姜峤已经发表的鞋底横纹、南档案房印泥污点说成自己的记忆；陶闻投票时冒用任瑞身份。信息在输入中已公开，因此属于模型未保持说话人归属，不是私人信息泄漏。应保留证词来源及角色身份，避免将他人第一人称陈述当成自身事实。</p>
<p><strong>P2 · 无来源行动细节。</strong>陈澄的实际发言增加“21:50把应急门钥匙交给陆潮”，未在本次实际输入中找到依据；其原知识记载的是送应急包。这应记录为来源无法核对的证词，不应升级为客观已发生行动。与此相比，沈雨、任瑞、沈珂对自身行为的掩盖有合法私人知识及角色目标来源，不能只因其说法与真相不同判为质量失败。</p>
<h2>结局评价的证据边界</h2><p>真实模型的正确/错误结局样本均为0。失败的是进入终局的流程；本轮无法评价结局文字、情绪收束和角色后续反应。五局 Echo 演练已完成，并验证现代游戏即使指认错误也会揭示完整预置真相；它仅证明机械行为，不能替代真实模型结局验收。</p>
<h2>费用与调用完整性</h2><p><strong>共220次付费请求，保守费用上界 ¥{float(fee['accounted_upper_cny']):.2f}，剩余预算 ¥{float(fee['remaining_cny']):.2f}。</strong>173次原生调用、47次盲玩家调用均有有效用量和一一对应的采集记录。输入1,130,038 tokens，输出58,110 tokens；按峰时缓存未命中输入¥9/百万、输出¥27/百万重算得到精确上界 ¥{fee['accounted_upper_cny']}，见<a href="https://api-docs.deepseek.com/zh-cn/quick_start/pricing/">官方价格页</a>。每次发送前预留完整上限，历史最大资金占用¥12.005442，始终低于¥20；无自动API重试、取消或长度截断。</p>
<p>账户余额观测减少¥4.43，可能包含延迟入账或其他账户调用，不能当作本批精确账单。费用审核以共享账本的保守上界为准。没有继续花完剩余额度，也没有对四个真实失败局重跑来制造通过结果。</p>
<h2>协议修正与实验限制</h2><p>首轮保留23次调用：四局因未使用的 <code>private_question:null</code>被验收器误拒，一局因模型选择已搜完地点中断。修正解析后重新试验，陈旧动作仍记录为拒绝。无声剧院第三幕模型将合法JSON包在完整Markdown代码块内；手动只移除外壳、复用原已付费正文并继续同一局。原24份采集前缀及原193条账本逐项保持一致，不重新询问该决策，不更改推理内容或票。</p>
<p>使用隔离SQLite测试库，未修改真实玩家数据或剧本正文。自治关闭；计时延至3600秒并用受控超时推进。保留原生工具和YAML回合限制；验收输出上限4096，原配置8192；盲玩家输入上限64000以容纳实际卷宗，生产角色上限23000。43项验收工具本地测试通过。未覆盖浏览器/WS租约、自然计时、长期后台自治与多模型多种子难度。</p>
<h2>可复查证据</h2><p>机器可读摘要：<a href="blind-five-acceptance.json">blind-five-acceptance.json</a>。完整证据目录：<code>{html.escape(str(ROOT))}</code>，包括 <code>requests.json</code>、<code>report.json</code>、<code>fee-review.json</code>、<code>semantic-role-ending-review.json</code>及<code>attempt2/semantic-isolation-review.json</code>。每案包含实际wire输入、可见模型输出、命令事件与工具receipt；推理隐藏字段仅保存哈希，不用于质量判定。</p>
</body></html>'''
    (DEST / "blind-five-acceptance.html").write_text(document, encoding="utf-8")
    print(json.dumps({"report": str(DEST / "blind-five-acceptance.html"), "calls": summary["paid_calls"],
                      "upper_cny": fee["accounted_upper_cny"], "acceptance": summary["acceptance"]}, ensure_ascii=False))


if __name__ == "__main__":
    main()
