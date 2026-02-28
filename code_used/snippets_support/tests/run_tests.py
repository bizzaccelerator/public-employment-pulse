"""
run_tests.py
============
Thin orchestrator invoked by the Kestra 'run_data_quality_tests' task.

Responsibilities:
  1. Run pytest on test_registro_hv.py using subprocess.
  2. Parse pytest's JSON report (--json-report plugin) into the two
     output files that downstream Kestra tasks consume:
       - test_results.json  machine-readable summary for the email template
       - test_report.txt    human-readable log attached to the email
  3. Exit with the same code pytest returned so Kestra marks the task
     correctly (0 = pass, 1 = failures found).

Why a separate orchestrator instead of calling pytest directly in
Kestra's 'commands'?
  - Kestra's outputFiles contract requires the files to exist AFTER the
    command completes, even when pytest exits non-zero.
  - Generating test_results.json here (rather than relying solely on
    --json-report) lets us shape the data exactly as the Jinja email
    template expects it.
"""

import subprocess
import sys
import json
import os
from datetime import datetime, timezone


PYTEST_JSON = "pytest_raw.json"
OUTPUT_JSON = "test_results.json"
OUTPUT_TXT  = "test_report.txt"
TEST_FILE   = "test_registro_hv.py"


def run_pytest() -> int:
    """
    Invoke pytest as a subprocess and return its exit code.

    Flags used:
      --tb=short          compact tracebacks — readable in email
      -v                  one line per test in stdout / test_report.txt
      --json-report       write machine-readable results to PYTEST_JSON
      --json-report-file  destination path for the JSON report
    """
    result = subprocess.run(
        [
            sys.executable, "-m", "pytest",
            TEST_FILE,
            "--tb=short",
            "-v",
            "--json-report",
            f"--json-report-file={PYTEST_JSON}",
        ],
        capture_output=False,   # let pytest stream to Kestra task log in real time
    )
    return result.returncode


def parse_pytest_json(exit_code: int) -> tuple[dict, str]:
    """
    Read pytest's raw JSON report and reshape it into:
      - summary dict  (written to test_results.json, read by Jinja template)
      - report text   (written to test_report.txt, attached to email)

    Falls back gracefully if the JSON file was not produced (e.g. pytest
    itself failed to start).
    """
    run_at = datetime.now(timezone.utc).isoformat()

    # --- Load raw pytest output ---
    if not os.path.exists(PYTEST_JSON):
        summary = {
            "run_at":     run_at,
            "total":      0,
            "passed":     0,
            "failed":     0,
            "all_passed": False,
            "tests":      [],
            "error":      "pytest JSON report not found — pytest may have failed to start",
        }
        report_text = (
            "ERROR: pytest did not produce a JSON report.\n"
            "Check the Kestra task log for details.\n"
        )
        return summary, report_text

    with open(PYTEST_JSON) as f:
        raw = json.load(f)

    # --- Extract per-test results ---
    tests = []
    for item in raw.get("tests", []):
        outcome  = item.get("outcome", "unknown")   # "passed" | "failed" | "error"
        passed   = outcome == "passed"
        # pytest uses nodeid like test_registro_hv.py::ClassName::test_method
        # Strip the filename prefix for a cleaner display name
        node_id  = item.get("nodeid", "")
        name     = node_id.replace(TEST_FILE + "::", "")

        detail = ""
        if not passed:
            call = item.get("call", {})
            detail = call.get("longrepr", "") or item.get("longrepr", "")

        tests.append({"name": name, "passed": passed, "detail": str(detail)})

    total  = len(tests)
    passed = sum(1 for t in tests if t["passed"])
    failed = total - passed

    summary = {
        "run_at":     run_at,
        "total":      total,
        "passed":     passed,
        "failed":     failed,
        "all_passed": failed == 0 and exit_code == 0,
        "tests":      tests,
    }

    # --- Build human-readable report ---
    sep = "=" * 62
    lines = [
        sep,
        "DATA QUALITY TEST REPORT",
        f"Run at : {run_at}",
        f"Total  : {total}   Passed : {passed}   Failed : {failed}",
        sep,
    ]

    if failed > 0:
        lines.append("\nFAILED TESTS")
        lines.append("-" * 40)
        for t in tests:
            if not t["passed"]:
                lines.append(f"  x  {t['name']}")
                if t["detail"]:
                    for line in t["detail"].strip().splitlines():
                        lines.append(f"       {line}")
        lines.append("")

    lines.append("ALL TESTS")
    lines.append("-" * 40)
    for t in tests:
        icon = "+" if t["passed"] else "x"
        lines.append(f"  {icon}  {t['name']}")

    lines.append("")
    lines.append(sep)
    if summary["all_passed"]:
        lines.append("RESULT: ALL TESTS PASSED")
    else:
        lines.append(f"RESULT: {failed} TEST(S) FAILED")
    lines.append(sep)

    return summary, "\n".join(lines)


def main():
    exit_code = run_pytest()

    summary, report_text = parse_pytest_json(exit_code)

    with open(OUTPUT_JSON, "w") as f:
        json.dump(summary, f, indent=2)

    with open(OUTPUT_TXT, "w") as f:
        f.write(report_text)

    # Print report to Kestra task log so it's visible in the UI
    print(report_text)

    sys.exit(exit_code)


if __name__ == "__main__":
    main()