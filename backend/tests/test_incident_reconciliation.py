from __future__ import annotations

import json
import hashlib
import tempfile
import unittest
from decimal import Decimal
from pathlib import Path
from unittest.mock import patch

from backend.verification.reconcile_test_incident import reconcile
from backend.verification.blind_budget import Pricing


class IncidentReconciliationTests(unittest.TestCase):
    def test_unknown_hold_is_idempotent_and_preserves_original_calls_and_new_rates(self):
        with tempfile.TemporaryDirectory() as directory:
            ledger = Path(directory) / "requests.json"
            price = Path(directory) / "official-price-test-snapshot.json"
            price.write_text('test snapshot', encoding="utf-8")
            ledger.write_text(json.dumps({"pricing": Pricing("9", "27", "https://example.invalid/pricing", "2026-10-14", "deepseek-v4-pro").as_dict(),
                "max_cny": "20", "request_limit": 300,
                "calls": [{"number": number, "status": "completed", "accounted_upper_cny": "0.009", "unit_test_fixture": True} for number in range(1, 221)]}), encoding="utf-8")
            original_calls = json.loads(ledger.read_text(encoding="utf-8"))["calls"]
            incident = Path(directory) / "incident.json"
            incident.write_text(json.dumps({"request_count_evidence": {"maximum_possible_unguarded_requests": 17},
                "ledger_baseline": {"sha256": hashlib.sha256(ledger.read_bytes()).hexdigest()}}), encoding="utf-8")
            with patch("backend.verification.reconcile_test_incident.PRICE_SHA256", hashlib.sha256(price.read_bytes()).hexdigest()):
                first = reconcile(ledger, price, incident)
            saved = json.loads(ledger.read_text(encoding="utf-8"))
            self.assertEqual(Decimal(first["accounted_upper_cny"]), Decimal("6.261840"))
            self.assertEqual(Decimal(first["incident_upper_cny"]), Decimal("4.281840"))
            self.assertTrue(first["historical_220_rows_unchanged"])
            self.assertEqual(saved["pricing"]["input_cny_per_million"], "9")
            self.assertEqual(len(saved["calls"]), 240)
            self.assertEqual(saved["calls"][:220], original_calls)
            self.assertTrue(all(row["usage"] is None and row["accounting_placeholder"] for row in saved["calls"][220:]))
            with patch("backend.verification.reconcile_test_incident.PRICE_SHA256", hashlib.sha256(price.read_bytes()).hexdigest()):
                again = reconcile(ledger, price, incident)
            self.assertEqual(again["accounted_upper_cny"], first["accounted_upper_cny"])
            self.assertEqual(json.loads(ledger.read_text(encoding="utf-8"))["calls"], saved["calls"])

    def test_unverified_price_or_peak_window_is_rejected_before_ledger_mutation(self):
        with tempfile.TemporaryDirectory() as directory:
            price = Path(directory) / "price.json"
            price.write_text('test snapshot', encoding="utf-8")
            missing = Path(directory) / "must-not-be-created.json"
            with self.assertRaisesRegex(ValueError, "pricing snapshot"):
                reconcile(missing, price, Path("unused.json"))
            with patch("backend.verification.reconcile_test_incident.PRICE_SHA256", hashlib.sha256(price.read_bytes()).hexdigest()), patch("backend.verification.reconcile_test_incident.PERIOD", ("2026-10-15T01:20:00+00:00", "2026-10-15T01:21:00+00:00")):
                with self.assertRaisesRegex(ValueError, "offpeak"):
                    reconcile(missing, price, Path("unused.json"))
            self.assertFalse(missing.exists())
