"""Run LTNtorch's own (unmodified) test suite and save the outcome to ./result/.

Usage:  python fuzzing/ltn/run_ltn_tests.py [--python PATH] [--tests SUBPATH]

Writes into fuzzing/ltn/result/:
  ltn_tests.xml    pytest JUnit report
  ltn_tests.log    full pytest stdout/stderr
  ltn_tests.json   per-test outcomes + totals
"""
import argparse
import json
import os
import subprocess
import sys
import time
import xml.etree.ElementTree as ET

HERE = os.path.dirname(os.path.abspath(__file__))
RESULT = os.path.join(HERE, "result")
LTN = os.path.join(HERE, "../..", "frameworks", "LTNtorch")


def parse_junit(path):
    tests = []
    for case in ET.parse(path).getroot().iter("testcase"):
        outcome, detail = "passed", ""
        for tag in ("failure", "error", "skipped"):
            node = case.find(tag)
            if node is not None:
                outcome = "failed" if tag == "failure" else tag
                detail = (node.get("message") or "")[:300]
                break
        tests.append({"test": f"{case.get('classname')}::{case.get('name')}",
                      "outcome": outcome, "secs": float(case.get("time") or 0), "detail": detail})
    return tests


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--python", default=sys.executable, help="interpreter that has LTNtorch's dependencies")
    ap.add_argument("--tests", default="tests/tests.py", help="path inside frameworks/LTNtorch")
    a = ap.parse_args()

    os.makedirs(RESULT, exist_ok=True)
    xml = os.path.join(RESULT, "ltn_tests.xml")
    log = os.path.join(RESULT, "ltn_tests.log")
    cmd = [a.python, "-m", "pytest", a.tests, "-q", "-p", "no:cacheprovider", f"--junitxml={xml}"]
    env = dict(os.environ)
    env["PYTHONPATH"] = os.pathsep.join([os.path.abspath(LTN), env.get("PYTHONPATH", "")])   # so `import ltn` finds the checkout

    t0 = time.time()
    proc = subprocess.run(cmd, cwd=LTN, capture_output=True, text=True, env=env)
    secs = time.time() - t0
    with open(log, "w") as f:
        f.write("$ " + " ".join(cmd) + f"\n(cwd={os.path.abspath(LTN)})\n\n{proc.stdout}\n{proc.stderr}")

    summary = {"command": " ".join(cmd), "exit_code": proc.returncode, "secs": round(secs, 2)}
    if os.path.exists(xml):
        tests = parse_junit(xml)
        counts = {}
        for t in tests:
            counts[t["outcome"]] = counts.get(t["outcome"], 0) + 1
        summary.update(totals=counts, n_tests=len(tests), tests=tests)
    else:
        summary.update(totals=None, error="pytest produced no JUnit report; see ltn_tests.log")
    with open(os.path.join(RESULT, "ltn_tests.json"), "w") as f:
        json.dump(summary, f, indent=1)

    print(f"exit code {proc.returncode}, {secs:.1f}s, totals: {summary['totals']}")
    print(f"saved to {RESULT}")
    return proc.returncode


if __name__ == "__main__":
    sys.exit(main())
