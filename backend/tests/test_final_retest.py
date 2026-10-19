from __future__ import annotations

import json
import sqlite3
import tempfile
import unittest
from contextlib import closing
from pathlib import Path

from backend.verification.final_retest import clone_database, final_proposal


class FinalRetestSafety(unittest.TestCase):
    def test_proposal_never_fixes_vote_or_unavailable_evidence(self):
        raw = json.dumps({"vote_role_id": "doctor", "evidence_ids": ["clock"], "explanation": "independent inference"})
        result, wrapped = final_proposal("```json\n" + raw + "\n```", {"doctor", "lawyer"}, {"clock"})
        self.assertEqual(result["vote_role_id"], "doctor")
        self.assertTrue(wrapped)
        for invalid in (raw.replace("doctor", "oracle_culprit"), raw.replace("clock", "future_clue"), "intro " + raw):
            with self.subTest(invalid=invalid), self.assertRaises((ValueError, json.JSONDecodeError)):
                final_proposal(invalid, {"doctor", "lawyer"}, {"clock"})

    def test_fixture_copy_preserves_source_and_refuses_overwrite(self):
        with tempfile.TemporaryDirectory() as folder:
            source, copy = Path(folder) / "source.db", Path(folder) / "copy.db"
            with closing(sqlite3.connect(source)) as connection, connection:
                connection.execute("CREATE TABLE fixture(value TEXT)")
                connection.execute("INSERT INTO fixture VALUES ('historical')")
            before = source.read_bytes()
            clone_database(source, copy)
            with closing(sqlite3.connect(copy)) as connection, connection:
                self.assertEqual(connection.execute("SELECT value FROM fixture").fetchone()[0], "historical")
                connection.execute("UPDATE fixture SET value='retest'")
            self.assertEqual(source.read_bytes(), before)
            with self.assertRaises(ValueError):
                clone_database(source, copy)
