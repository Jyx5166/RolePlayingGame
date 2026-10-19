"""Book unknown historical test usage; this module never contacts a provider."""
from __future__ import annotations

import hashlib
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

from backend.verification.blind_budget import MoneyRequestLedger, Pricing


INCIDENT_ID = "unguarded-tests-20261015"
SLOTS = 20  # Coarser than the independently audited <=17 dispatch bound.
PERIOD = ("2026-10-15T15:19:27.447+00:00", "2026-10-15T15:20:38.312+00:00")
PRICE_SHA256 = "27f0f34ee9d9f036ea36d1c24ec9fcacb5203b771e65e87ca362c4d55f0879bd"


def reconcile(ledger_path: Path, price_path: Path, incident_path: Path) -> dict:
    snapshot = price_path.read_bytes()
    if hashlib.sha256(snapshot).hexdigest() != PRICE_SHA256:
        raise ValueError("Expected independently reviewed official pricing snapshot")
    start, end = (datetime.fromisoformat(value).astimezone(timezone(timedelta(hours=8))) for value in PERIOD)
    if start.date() != end.date() or not (18 <= start.hour <= end.hour <= 23):
        raise ValueError("Incident window is not wholly within verified offpeak hours")
    incident = json.loads(incident_path.read_text(encoding="utf-8"))
    if incident["request_count_evidence"]["maximum_possible_unguarded_requests"] > SLOTS:
        raise ValueError("Reservation count does not cover audited dispatch bound")
    old = json.loads(ledger_path.read_text(encoding="utf-8"))
    baseline_path = ledger_path.with_name("requests-220calls.json")
    if not baseline_path.exists():
        if len(old["calls"]) != 220 or hashlib.sha256(ledger_path.read_bytes()).hexdigest() != incident["ledger_baseline"]["sha256"]:
            raise ValueError("Historical 220-call baseline differs")
        baseline_path.write_bytes(ledger_path.read_bytes())
    baseline = json.loads(baseline_path.read_text(encoding="utf-8"))
    if old["calls"][:220] != baseline["calls"]:
        raise ValueError("Historical calls changed")
    ledger = MoneyRequestLedger(ledger_path, Pricing("9", "27", old["pricing"]["source"], "2026-10-14", "deepseek-v4-pro"), resume=True)
    existing = [row for row in ledger.calls if row.get("incident_id") == INCIDENT_ID]
    if existing and (len(existing) != SLOTS or any(row.get("status") != "external_unknown" for row in existing)):
        raise ValueError("Partial reconciliation requires explicit audit")
    period_price = Pricing("4.5", "13.5", old["pricing"]["source"], "2026-10-15", "deepseek-v4-pro")
    reservation = str(period_price.cost(23000, 8192))
    if not existing:
        for _ in range(SLOTS):
            row = ledger.reserve(input_limit=23000, output_limit=8192, context={"purpose": INCIDENT_ID, "actor": "unknown"},
                                 model="deepseek-v4-pro", transport="external_untracked_unknown", estimated_input_tokens=23000)
            row.update(incident_id=INCIDENT_ID, retrospective=True, external_unguarded=True,
                       accounting_placeholder=True, actual_dispatch_count_unknown=True,
                       dispatch_window_utc=list(PERIOD), period_pricing=period_price.as_dict(),
                       pricing_snapshot_sha256=PRICE_SHA256, incident_report=str(incident_path),
                       reserved_cny=reservation, accounted_upper_cny=reservation)
            ledger.finish(row, status="external_unknown", usage=None, metadata={"provider_invoked": None}, latency_ms=0)
    result = {"incident_id": INCIDENT_ID, "accounting_placeholder_count": SLOTS,
              "actual_incident_count_known": False, "actual_incident_usage_known": False,
              "incident_upper_cny": str(period_price.cost(23000, 8192) * SLOTS),
              "historical_220_rows_unchanged": ledger.calls[:220] == baseline["calls"],
              "new_request_pricing_unchanged": ledger.pricing.as_dict() == old["pricing"], **ledger.summary()}
    ledger_path.with_name("incident-reconciliation-20261015.json").write_text(json.dumps(result, indent=2), encoding="utf-8")
    return result


if __name__ == "__main__":
    root = Path(__file__).resolve().parents[2]
    folder = root / "backend/data/verification/blind-five-20261014-live"
    print(json.dumps(reconcile(folder / "requests.json", root / "backend/reports/deepseek-pricing-20261015.json",
                               folder / "untracked-test-incident-20261015.json"), indent=2))
