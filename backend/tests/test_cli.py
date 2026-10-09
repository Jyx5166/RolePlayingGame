from __future__ import annotations

import os
import sys
import unittest
from pathlib import Path
from unittest import IsolatedAsyncioTestCase

BACKEND_ROOT = Path(__file__).resolve().parents[1]
os.environ["LLM_PROVIDER"] = "echo"
sys.path.insert(0, str(BACKEND_ROOT / "app"))

from cli import ParsedCommand, build_dm, format_blocks, handle_cli_command, parse_input


class CliParsingTest(unittest.TestCase):
    def test_plain_text_is_speech(self) -> None:
        self.assertEqual(parse_input("孙悟空，你为何来此？"), ParsedCommand("speech", "孙悟空，你为何来此？"))

    def test_search_command(self) -> None:
        self.assertEqual(parse_input("/search mountain_pass"), ParsedCommand("search", "mountain_pass"))
        self.assertEqual(parse_input("/s old_tablet"), ParsedCommand("search", "old_tablet"))

    def test_short_commands(self) -> None:
        self.assertEqual(parse_input("/a"), ParsedCommand("advance"))
        self.assertEqual(parse_input("/i"), ParsedCommand("info"))
        self.assertEqual(parse_input("/r"), ParsedCommand("roles"))
        self.assertEqual(parse_input("/q"), ParsedCommand("quit"))

    def test_format_blocks_handles_empty_info(self) -> None:
        self.assertIn("没有新的私人信息", format_blocks([]))


class CliCommandFlowTest(IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.dm = build_dm()
        await self.dm.init_game("flame_mountain", "red_boy", "narrative")

    async def test_cli_search_command(self) -> None:
        running, lines = await handle_cli_command(self.dm, ParsedCommand("search", "mountain_pass"))
        self.assertTrue(running)
        self.assertIn("搜证结果", lines[0])
        self.assertIn("山道火线", lines[0])

    async def test_cli_speech_command_triggers_ai(self) -> None:
        running, lines = await handle_cli_command(self.dm, ParsedCommand("speech", "孙悟空，你为何来此？"))
        self.assertTrue(running)
        self.assertEqual(len(lines), 2)
        self.assertIn("monkey_king", lines[1])


if __name__ == "__main__":
    unittest.main()
