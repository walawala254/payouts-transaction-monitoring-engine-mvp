"""Manual performance check for the documented 100,000-row upload target."""

import time
import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from transaction_monitor import build_alert_cases, evaluate, load_rules, normalize_transactions


def main(rows: int = 100_000) -> None:
    raw = pd.DataFrame({
        "transaction id": [f"tx-{index}" for index in range(rows)],
        "merchant": ["Load Test Merchant"] * rows,
        "mid": ["LOAD-MID"] * rows,
        "transaction date": pd.date_range("2026-01-01", periods=rows, freq="min"),
        "transaction type": ["payment"] * rows,
        "status": ["approved"] * rows,
        "amount": [100.0] * rows,
        "merchant amount": [95.0] * rows,
        "currency": ["USD"] * rows,
        "card brand": ["visa"] * rows,
        "card number": [f"411111{index % 20_000:010d}" for index in range(rows)],
        "payer email": [f"user-{index % 20_000}@example.com" for index in range(rows)],
        "payer phone": [f"+2547{index % 20_000:08d}" for index in range(rows)],
        "payer country": ["KE"] * rows,
        "geoip country": ["KE"] * rows,
    })
    tx = normalize_transactions(raw)
    started = time.perf_counter()
    evaluated, hits = evaluate(tx, load_rules("rules.yaml"))
    cases = build_alert_cases(evaluated, hits)
    elapsed = time.perf_counter() - started
    print({
        "rows": len(evaluated),
        "rule_hits": len(hits),
        "investigation_alerts": len(cases),
        "seconds": round(elapsed, 2),
        "rows_per_second": round(rows / elapsed),
    })


if __name__ == "__main__":
    main(int(sys.argv[1]) if len(sys.argv) > 1 else 100_000)
