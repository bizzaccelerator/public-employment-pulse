"""
run_tests.py — pytest orchestrator for orientacion_hv data-quality gate.

Kestra executes this script via the run_data_quality_tests task.  It:
  1. Runs pytest programmatically against both test files with the
     JSON-report plugin.
  2. Parses the JSON report into a compact summary (test_results.json)
     that the notify_test_results Kestra task reads via Jinja.
  3. Writes a human-readable plain-text log (test_report.txt) that is
     attached to the notification email.
  4. Exits with the pytest exit code so Kestra marks the task
     FAILED when tests fail.

TEST FILE EXECUTED
------------------
  test_orientacion_hv.py — unit tests for every public function

Only this file is uploaded as a Kestra namespace file.
test_integration_orientacion.py is kept for local development but is NOT
executed here because it is not available in the Kestra working directory.

OUTPUT FILES
------------
  pytest_raw.json    — full pytest JSON report (consumed by parse_report())
  test_results.json  — compact summary consumed by Kestra Jinja notify task
  test_report.txt    — human-readable report attached to notification email
"""

import json
import subprocess
import sys
from datetime import datetime, timezone


PYTEST_JSON = "pytest_raw.json"
OUTPUT_JSON = "test_results.json"
OUTPUT_TXT  = "test_report.txt"

# Only the unit test file is available as a Kestra namespace file.
TEST_FILES = [
    "test_orientacion_hv.py",
]


def run_pytest() -> int:
    """
    Invoke pytest on all test files and produce a JSON report.

    stdout/stderr are NOT captured (capture_output=False) so that Kestra's
    task log shows live pytest output during the run.

    Returns:
        pytest exit code:
            0  — all tests passed
            1  — some tests failed
            2  — pytest was interrupted
            3  — internal pytest error
            4  — command-line usage error
            5  — no tests were collected
    """
    result = subprocess.run(
        [
            sys.executable, "-m", "pytest",
            *TEST_FILES,
            "-v",
            "--json-report",
            f"--json-report-file={PYTEST_JSON}",
            "--tb=short",
        ],
        capture_output=False,
    )
    return result.returncode


def parse_report(exit_code: int) -> dict:
    """
    Read the raw pytest JSON report and build the compact summary that
    the notify_test_results Kestra task consumes via Jinja.

    The compact summary has this shape:
    {
        "all_passed": bool,
        "total":      int,
        "passed":     int,
        "failed":     int,
        "run_at":     "YYYY-MM-DD HH:MM:SS UTC",
        "tests": [
            {
                "name":   str,   # pytest node id
                "passed": bool,
                "detail": str,   # first 800 chars of failure longrepr, or ""
            },
            ...
        ]
    }

    Args:
        exit_code: Return code from run_pytest().

    Returns:
        The compact summary dict.

    Raises:
        FileNotFoundError: If pytest_raw.json was not written (e.g. pytest
            crashed before producing any output).
    """
    with open(PYTEST_JSON) as f:
        raw = json.load(f)

    tests = []
    for t in raw.get("tests", []):
        passed = t["outcome"] == "passed"

        detail = ""
        if not passed:
            # longrepr can live under "call", "setup", or "teardown"
            for phase in ("call", "setup", "teardown"):
                longrepr = t.get(phase, {}).get("longrepr", "")
                if longrepr:
                    detail = str(longrepr)[:800]
                    break

        tests.append({
            "name":   t["nodeid"],
            "passed": passed,
            "detail": detail,
        })

    summary = raw.get("summary", {})
    total   = summary.get("total",  len(tests))
    passed  = summary.get("passed", sum(1 for t in tests if t["passed"]))
    # Count both "failed" and "error" outcomes as failures for Kestra.
    failed  = summary.get("failed", 0) + summary.get("error", 0)

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

    The format is designed to be legible both in email attachments and in
    Kestra's task log viewer.

    Args:
        summary: Dict produced by parse_report().
    """
    sep  = "=" * 62
    dash = "-" * 42

    header_status = "ALL PASSED ✓" if summary["all_passed"] else "FAILURES DETECTED ✗"

    lines = [
        sep,
        "  orientacion_hv — Data Quality Test Report",
        f"  Run at : {summary['run_at']}",
        f"  Result : {header_status}",
        f"  Total  : {summary['total']}   "
        f"Passed: {summary['passed']}   Failed: {summary['failed']}",
        sep,
    ]

    if not summary["all_passed"]:
        lines += ["", "FAILED TESTS", dash]
        for t in summary["tests"]:
            if not t["passed"]:
                lines.append(f"\n  ✗  {t['name']}")
                if t["detail"]:
                    for line in t["detail"].splitlines():
                        lines.append(f"       {line}")

    lines += ["", "ALL TESTS", dash]
    for t in summary["tests"]:
        icon = "✓" if t["passed"] else "✗"
        lines.append(f"  {icon}  {t['name']}")

    lines.append("")   # trailing newline

    with open(OUTPUT_TXT, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))


def main() -> None:
    """
    Orchestrate the full test run:
      1. Run pytest → collect exit code.
      2. Parse the raw JSON report → build compact summary.
      3. Write test_results.json (consumed by Kestra Jinja).
      4. Write test_report.txt (attached to notification email).
      5. Print a brief console summary.
      6. Exit with pytest's exit code (non-zero = Kestra marks task FAILED).
    """
    exit_code = run_pytest()

    try:
        summary = parse_report(exit_code)
    except FileNotFoundError:
        # pytest crashed before writing the JSON report (e.g. import error in
        # a test file).  Write a minimal failure summary so Kestra still gets
        # a valid JSON file and the notify task does not itself crash.
        summary = {
            "all_passed": False,
            "total":      0,
            "passed":     0,
            "failed":     1,
            "run_at":     datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC"),
            "tests":      [{
                "name":   "pytest_startup",
                "passed": False,
                "detail": (
                    f"pytest did not produce {PYTEST_JSON}. "
                    "Check for import errors in the test files. "
                    f"pytest exit code: {exit_code}"
                ),
            }],
        }

    with open(OUTPUT_JSON, "w", encoding="utf-8") as f:
        json.dump(summary, f, indent=2, ensure_ascii=False)

    write_text_report(summary)

    sep = "=" * 62
    print(f"\n{sep}")
    print(
        f"Tests: {summary['total']} total, "
        f"{summary['passed']} passed, "
        f"{summary['failed']} failed"
    )
    print(f"Result: {'ALL PASSED' if summary['all_passed'] else 'FAILURES DETECTED'}")
    print(sep)

    sys.exit(exit_code)


if __name__ == "__main__":
    main()