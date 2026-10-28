from __future__ import annotations

import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from typing import get_type_hints


ROOT = Path(__file__).resolve().parents[2]
APP_DIR = ROOT / "backend" / "app"


class AgentModuleImportsTest(unittest.TestCase):
    def test_cold_imports_and_legacy_exports_share_implementations(self):
        # A suite that has already imported agent can hide a new package cycle.
        # Exercise each public entry first in its own interpreter instead.
        code = """
import importlib
import sys

importlib.import_module(sys.argv[1])
from agent import AgentInstance, AgentPool
from agent.archive import MemoryArchive as LegacyArchive, extract_summary as legacy_summary
from agent.memory import PreparedInput as LegacyInput, prepare_input as legacy_prepare, terms as legacy_terms
from memory.archive import MemoryArchive, extract_summary
from memory.selection import PreparedInput, prepare_input, terms
from runtime.workflow import GameWorkflow as LegacyWorkflow
from runtime.workflow import ActorState as LegacyActorState, DirectorState as LegacyDirectorState
from workflow import GameWorkflow
from workflow.state import ActorState, DirectorState

assert LegacyArchive is MemoryArchive
assert legacy_summary is extract_summary
assert LegacyInput is PreparedInput
assert legacy_prepare is prepare_input
assert legacy_terms is terms
assert LegacyWorkflow is GameWorkflow
assert LegacyActorState is ActorState
assert LegacyDirectorState is DirectorState
pool = AgentPool()
from llm.echo import EchoLLM
actor = pool.create('import_probe', 'Import probe', EchoLLM())
assert isinstance(actor, AgentInstance)
"""
        for first_module in (
            "agent", "memory.selection", "memory.archive", "workflow.actor_graph",
            "workflow.director_graph", "workflow", "agent.memory", "agent.archive",
            "runtime.workflow", "game_service", "main",
        ):
            with self.subTest(first_module=first_module):
                with tempfile.TemporaryDirectory(prefix="rpg-imports-") as data_dir:
                    environment = {
                        **os.environ,
                        "PYTHONPATH": str(APP_DIR),
                        "PYTHONIOENCODING": "utf-8",
                        "AI_MURDER_MYSTERY_DATA_DIR": data_dir,
                        "LLM_PROVIDER": "echo",
                    }
                    result = subprocess.run(
                        [sys.executable, "-c", code, first_module],
                        cwd=ROOT, env=environment, capture_output=True,
                        text=True, encoding="utf-8", timeout=30,
                    )
                    self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_memory_public_type_hints_resolve(self):
        from agent.context import AgentContext
        from agent.memory import PreparedInput, prepare_input

        self.assertIs(get_type_hints(PreparedInput)["context"], AgentContext)
        hints = get_type_hints(prepare_input)
        self.assertIs(hints["context"], AgentContext)
        self.assertIs(hints["return"], PreparedInput)


if __name__ == "__main__":
    unittest.main()
