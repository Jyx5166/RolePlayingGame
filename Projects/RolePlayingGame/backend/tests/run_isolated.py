"""Run backend regression tests without initializing the normal application data directory."""

from __future__ import annotations

import os
import argparse
import json
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--report", type=Path)
    args = parser.parse_args()
    project = Path(__file__).resolve().parents[2]
    sys.path.insert(0, str(project))
    sys.path.insert(0, str(project / "backend" / "app"))
    with tempfile.TemporaryDirectory(prefix="rpg-regression-") as data_dir:
        with patch.dict(os.environ, {"AI_MURDER_MYSTERY_DATA_DIR": data_dir, "LLM_PROVIDER": "echo"}):
            suite = unittest.defaultTestLoader.discover(str(project / "backend" / "tests"))
            started = time.perf_counter()
            result = unittest.TextTestRunner(verbosity=2).run(suite)
            elapsed = time.perf_counter() - started
    if args.report:
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(json.dumps({"tests": result.testsRun, "passed": result.wasSuccessful(),
            "failures": [test.id() for test, _ in result.failures],
            "errors": [test.id() for test, _ in result.errors], "skipped": len(result.skipped),
            "duration_seconds": round(elapsed, 3), "provider": "echo", "isolated_database": True,
            "paid_requests": 0}, ensure_ascii=False, indent=2), encoding="utf-8")
    return 0 if result.wasSuccessful() else 1


if __name__ == "__main__":
    raise SystemExit(main())
