"""
run_tests.py — pytest orchestrator for orientacion_hv data-quality gate.

Kestra executes this script via the run_data_quality_tests task.  It:
  1. Runs pytest programmatically with the JSON-report plugin.
  2. Parses the JSON report into a compact summary (test_results.json)
     that the notify_test_results task reads via Jinja.
  3. Writes a human-readable plain-text log (test_report.txt) that is
     attached to the notification email.
  4. Exits with the pytest exit code so Kestra marks the task
     FAILED when tests fail.
"""

import json
import subprocess
import sys
from datetime import datetime, timezone


PYTEST_JSON = "pytest_raw.json"
OUTPUT_JSON = "test_results.json"
OUTPUT_TXT  = "test_report.txt"


def run_pytest() -> int:
    """
    Invoke pytest on test_orientacion_hv.py and produce a JSON report.

    Returns:
        pytest exit code (0 = all passed, non-zero = failures or errors).
    """
    result = subprocess.run(
        [
            sys.executable, "-m", "pytest",
            "test_orientacion_hv.py",
            "-v",
            f"--json-report",
            f"--json-report-file={PYTEST_JSON}",
            "--tb=short",
        ],
        capture_output=False,   # let stdout/stderr stream into Kestra logs
    )
    return result.returncode


def parse_report(exit_code: int) -> dict:
    """
    Read the raw pytest JSON report and build the compact summary that
    the notify_test_results Kestra task consumes via Jinja.

    Args:
        exit_code: Return code from run_pytest().

    Returns:
        A dict with keys: all_passed, total, passed, failed, run_at, tests.
    """
    with open(PYTEST_JSON) as f:
        raw = json.load(f)

    tests = []
    for t in raw.get("tests", []):
        passed = t["outcome"] == "passed"
        detail = ""
        if not passed:
            longrepr = t.get("call", {}).get("longrepr", "") or \
                       t.get("setup", {}).get("longrepr", "") or \
                       t.get("teardown", {}).get("longrepr", "")
            detail = str(longrepr)[:800]   # cap length for email safety

        tests.append({
            "name":   t["nodeid"],
            "passed": passed,
            "detail": detail,
        })

    summary  = raw.get("summary", {})
    total    = summary.get("total",   len(tests))
    passed   = summary.get("passed",  sum(1 for t in tests if t["passed"]))
    failed   = summary.get("failed",  0) + summary.get("error", 0)

    return {
        "all_passed": exit_code == 0,
        "total":      total,
        "passed":     passed,
        "failed":     failed,
        "run_at":     datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC"),
        "tests":      tests,
    }


def write_text_report(summary: dict) -> None:
    """
    Write a human-readable plain-text report to test_report.txt.

    Args:
        summary: Dict produced by parse_report().
    """
    lines = [
        "=" * 60,
        "  orientacion_hv — Data Quality Test Report",
        f"  Run at : {summary['run_at']}",
        f"  Result : {'ALL PASSED' if summary['all_passed'] else 'FAILURES DETECTED'}",
        f"  Total  : {summary['total']}   "
        f"Passed: {summary['passed']}   Failed: {summary['failed']}",
        "=" * 60,
    ]

    if not summary["all_passed"]:
        lines.append("\nFAILED TESTS\n" + "-" * 40)
        for t in summary["tests"]:
            if not t["passed"]:
                lines.append(f"\n  ✗  {t['name']}")
                if t["detail"]:
                    for line in t["detail"].splitlines():
                        lines.append(f"       {line}")

    lines.append("\nALL TESTS\n" + "-" * 40)
    for t in summary["tests"]:
        icon = "✓" if t["passed"] else "✗"
        lines.append(f"  {icon}  {t['name']}")

    with open(OUTPUT_TXT, "w") as f:
        f.write("\n".join(lines) + "\n")


def main():
    exit_code = run_pytest()

    summary = parse_report(exit_code)

    with open(OUTPUT_JSON, "w") as f:
        json.dump(summary, f, indent=2)

    write_text_report(summary)

    print(f"\n{'='*60}")
    print(f"Tests: {summary['total']} total, "
          f"{summary['passed']} passed, {summary['failed']} failed")
    print(f"{'='*60}")

    sys.exit(exit_code)


if __name__ == "__main__":
    main()