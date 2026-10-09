from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Any, Literal

from agent.pool import AgentPool
from config import load_settings
from dm.engine import DMEngine, GamePhase
from llm.factory import LLMFactory
from loader.script_loader import ScriptLoader
from registry.mechanic_registry import MechanicRegistry
from registry.skill_registry import SkillRegistry
from skill.narrative import NarrativeSkill
from paths import scripts_dir


CommandType = Literal["speech", "search", "advance", "info", "roles", "help", "quit", "unknown"]


@dataclass(frozen=True)
class ParsedCommand:
    type: CommandType
    value: str = ""


def parse_input(raw: str) -> ParsedCommand:
    text = raw.strip()
    if not text:
        return ParsedCommand("unknown", "")
    if not text.startswith("/"):
        return ParsedCommand("speech", text)

    head, _, tail = text.partition(" ")
    command = head.lower()
    value = tail.strip()

    if command in ("/q", "/quit", "/exit"):
        return ParsedCommand("quit")
    if command in ("/h", "/help"):
        return ParsedCommand("help")
    if command in ("/i", "/info"):
        return ParsedCommand("info")
    if command in ("/r", "/roles"):
        return ParsedCommand("roles")
    if command in ("/a", "/advance"):
        return ParsedCommand("advance")
    if command in ("/s", "/search"):
        return ParsedCommand("search", value)
    return ParsedCommand("unknown", text)


def format_blocks(blocks: list[dict[str, Any]]) -> str:
    if not blocks:
        return "  （本阶段没有新的私人信息）"
    return "\n".join(f"  - [{block['type']}] {block['content']}" for block in blocks)


def format_roles(roles: list[dict[str, str]]) -> str:
    return "\n".join(f"  - {role['role_name']} ({role['role_id']}): {role['public_identity']}" for role in roles)


def help_text() -> str:
    return (
        "可用命令：\n"
        "  直接输入文字      作为角色发言\n"
        "  /search <目标ID>  搜证，例如 /search mountain_pass\n"
        "  /advance          推进到下一阶段；最终阶段后进入复盘\n"
        "  /info             查看当前阶段新信息\n"
        "  /roles            查看公开角色表\n"
        "  /help             查看帮助\n"
        "  /quit             退出"
    )


def build_dm() -> DMEngine:
    settings = load_settings()
    skill_registry = SkillRegistry()
    skill_registry.register(NarrativeSkill)
    return DMEngine(
        ScriptLoader(scripts_dir()),
        AgentPool(),
        LLMFactory(
            {
                "provider": settings.llm_provider,
                "model": settings.llm_model,
                "base_url": settings.llm_base_url,
                "api_key": settings.llm_api_key,
                "timeout": settings.llm_timeout_seconds,
                "context_window": settings.llm_context_window,
                "input_limit": settings.llm_input_limit,
                "output_limit": settings.llm_output_limit,
                "safety_margin": settings.llm_safety_margin,
                "reasoning_effort": settings.llm_reasoning_effort,
            }
        ),
        MechanicRegistry(),
        skill_registry,
    )


async def handle_cli_command(dm: DMEngine, parsed: ParsedCommand) -> tuple[bool, list[str]]:
    if parsed.type == "quit":
        return False, ["已退出。"]
    if parsed.type == "help":
        return True, [help_text()]
    if parsed.type == "roles":
        return True, ["公开角色：\n" + format_roles(dm.get_public_roles())]
    if parsed.type == "info":
        return True, ["当前阶段信息：\n" + format_blocks(dm.get_human_player_info())]
    if parsed.type == "search":
        if not parsed.value:
            return True, ["请提供搜证目标 ID，例如：/search mountain_pass"]
        result = await dm.handle_mechanic_action({"type": "search", "target_id": parsed.value})
        if result.get("clue"):
            clue = result["clue"]
            return True, [f"搜证结果：{clue['content']}\n剩余 AP：{result['remaining_ap']}"]
        return True, [f"搜证结果：{result.get('message', '没有发现线索')}"]
    if parsed.type == "advance":
        if dm.can_advance():
            state = await dm.advance_stage()
            return True, [
                f"进入第 {state.current_stage_num} 阶段。\n"
                "新信息：\n"
                + format_blocks(dm.get_human_player_info())
            ]
        replay = await dm.run_replay()
        return True, [
            "复盘：\n"
            f"{replay['full_story']}\n"
            f"时间线：{replay['timeline']}\n"
            f"角色弧线：{replay['role_arcs']}"
        ]
    if parsed.type == "speech":
        result = await dm.handle_human_speech(parsed.value)
        lines: list[str] = [f"你：{result['content']}"]
        if result.get("warning"):
            lines.append(f"DM 提示：{result['warning']}")
        for reply in await dm.schedule_ai_turns(result):
            lines.append(f"{reply['role_id']}：{reply['content']}")
        return True, lines
    return True, ["无法识别命令。输入 /help 查看可用命令。"]


async def run_cli() -> None:
    dm = build_dm()
    state = await dm.init_game("flame_mountain", "red_boy", "narrative")
    print("AI 剧本杀引擎 MVP")
    print(f"剧本：flame_mountain | 角色：red_boy | 阶段：{state.current_stage_num}/{state.total_stages}")
    print("\n公开角色：")
    print(format_roles(dm.get_public_roles()))
    print("\n当前阶段信息：")
    print(format_blocks(dm.get_human_player_info()))
    print("\n" + help_text())

    running = True
    while running:
        try:
            raw = input("\n> ")
        except (EOFError, KeyboardInterrupt):
            print("\n已退出。")
            return
        running, lines = await handle_cli_command(dm, parse_input(raw))
        for line in lines:
            print(line)
        if dm.state and dm.state.phase == GamePhase.REPLAY:
            running = False


if __name__ == "__main__":
    asyncio.run(run_cli())
