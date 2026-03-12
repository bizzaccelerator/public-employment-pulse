"""
run_tests_vacantes.py
---------------------
Kestra test runner for the vacantes pipeline.

Executes the pytest suite (test_vacantes.py), captures every result, and
writes two output files consumed by downstream Kestra tasks:

    test_results.json  – structured JSON summary (read by notify_test_results)
    test_report.txt    – human-readable pytest output (sent as email attachment)

Exit codes
----------
    0  all tests passed
    1  one or more tests failed (or pytest itself errored)
"""

from __future__ import annotations

import json
import subprocess
import sys
from datetime import datetime, timezone


# ---------------------------------------------------------------------------
# Run pytest with JSON report plugin
# ---------------------------------------------------------------------------
PYTEST_CMD = [
    sys.executable, "-m", "pytest",
    "test_vacantes.py",
    "-v",
    "--tb=short",
    "--json-report",
    "--json-report-file=.pytest_report.json",
    "--json-report-indent=2",
]

print("Running: " + " ".join(PYTEST_CMD))
proc = subprocess.run(PYTEST_CMD, capture_output=True, text=True)

# Capture full stdout/stderr for the .txt report
full_output = proc.stdout + ("\n" + proc.stderr if proc.stderr.strip() else "")

# ---------------------------------------------------------------------------
# Write human-readable report
# ---------------------------------------------------------------------------
with open("test_report.txt", "w") as fh:
    fh.write(full_output)

print(full_output)

# ---------------------------------------------------------------------------
# Parse pytest-json-report output and build a Kestra-friendly summary
# ---------------------------------------------------------------------------
try:
    with open(".pytest_report.json") as fh:
        raw = json.load(fh)

    tests: list[dict] = []
    for item in raw.get("tests", []):
        outcome = item.get("outcome", "unknown")  # "passed" | "failed" | "error"
        call    = item.get("call", {})
        detail  = call.get("longrepr", "") if outcome != "passed" else ""

        tests.append({
            "name":   item.get("nodeid", "unknown"),
            "passed": outcome == "passed",
            "detail": detail,
        })

    summary = raw.get("summary", {})
    total   = summary.get("total",   len(tests))
    passed  = summary.get("passed",  sum(1 for t in tests if t["passed"]))
    failed  = summary.get("failed",  0) + summary.get("error", 0)

except (FileNotFoundError, json.JSONDecodeError, KeyError) as exc:
    # Fallback: derive counts from the subprocess return code alone
    print(f"[WARN] Could not parse pytest JSON report: {exc}")
    tests   = []
    total   = 0
    passed  = 0
    failed  = 1 if proc.returncode != 0 else 0

all_passed = proc.returncode == 0

result_summary = {
    "run_at":    datetime.now(timezone.utc).isoformat(),
    "all_passed": all_passed,
    "total":     total,
    "passed":    passed,
    "failed":    failed,
    "tests":     tests,
}

# ---------------------------------------------------------------------------
# Write structured JSON summary
# ---------------------------------------------------------------------------
with open("test_results.json", "w") as fh:
    json.dump(result_summary, fh, indent=2)

print(
    f"\n{'='*60}\n"
    f"Test run complete  |  total={total}  passed={passed}  failed={failed}\n"
    f"{'='*60}"
)

sys.exit(0 if all_passed else 1)