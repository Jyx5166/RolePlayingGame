from __future__ import annotations

import contextlib
import io
import json
import os
import stat
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "app"))

from storage import AppStore
from backend.verification.accounts import (
    new_verification_account,
    save_verification_account,
    verification_session,
)


class VerificationAccountsTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.directory = Path(self.temporary.name)
        self.store = AppStore(self.directory / "app.db")

    def test_generated_accounts_are_distinct_and_usable(self) -> None:
        first = new_verification_account("preview" * 6)
        second = new_verification_account("preview")
        self.assertNotEqual(first["username"], second["username"])
        self.assertNotEqual(first["password"], second["password"])
        self.assertLessEqual(len(first["username"]), 32)
        session = self.store.register(**first)
        self.assertEqual(self.store.login(**first)["user"]["id"], session["user"]["id"])

    def test_seed_rerun_reuses_the_local_account_without_printing_credentials(self) -> None:
        output = io.StringIO()
        with contextlib.redirect_stdout(output), contextlib.redirect_stderr(output):
            created = verification_session(self.store, self.directory, prefix="preview")
            resumed = verification_session(
                self.store, self.directory, prefix="preview", require_existing=True,
            )
        self.assertEqual(created["user"]["id"], resumed["user"]["id"])
        account = json.loads((self.directory / "qa-access.json").read_text(encoding="utf-8"))
        self.assertEqual(self.store.login(**account)["user"]["id"], created["user"]["id"])
        self.assertNotIn(account["password"], output.getvalue())
        self.assertNotIn(account["username"], output.getvalue())
        if os.name != "nt":
            self.assertEqual(stat.S_IMODE((self.directory / "qa-access.json").stat().st_mode), 0o600)

    def test_append_requires_an_existing_account_export(self) -> None:
        with self.assertRaisesRegex(ValueError, "generate the fixtures first"):
            verification_session(self.store, self.directory, prefix="preview", require_existing=True)
        self.assertFalse((self.directory / "qa-access.json").exists())

    def test_account_export_requires_a_git_ignored_filename(self) -> None:
        with self.assertRaisesRegex(ValueError, "ignored account export filename"):
            save_verification_account(self.directory / "public.json", new_verification_account("preview"))
        self.assertFalse((self.directory / "public.json").exists())

    def test_invalid_local_export_does_not_create_an_account(self) -> None:
        (self.directory / "qa-access.json").write_text("{}", encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "Invalid local verification account export"):
            verification_session(self.store, self.directory, prefix="preview")


if __name__ == "__main__":
    unittest.main()
