"""Shared driver for the fuzz_*.py scripts.

Flow (baseline first, then mutate, as agreed):
  1. run DeepProbLog's original tests through the plugin with no mutation  -> baseline outcome per test
  2. run them again once per RNG seed with one kind of input mutation
  3. classify every (test, seed) against the baseline and save to result/

Classification
  preserving kinds (reorder, duplicate_rule, rename, engine_swap): the answer must not change, so the
  test's own assert must still pass.   fail -> metamorphic_violation, other exception -> exception
  probability: the hard-coded expected value no longer applies, so an AssertionError is expected
  (expected_value_changed), a KeyError on a now-absent answer is answer_missing (reported, not a finding).
  Findings are: exception, timeout, range_violation.
"""
import argparse
import collections
import difflib
import json
import os
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
RESULT = os.path.join(HERE, "result")
DPL = os.path.join(HERE, "..", "..", "frameworks", "deepproblog")

PRESERVING = {"reorder", "duplicate_rule", "rename", "engine_swap"}
FINDINGS = {"metamorphic_violation", "exception", "timeout", "range_violation", "process_crash"}


def swipl_env():

    env = dict(os.environ)
    if env.get("LIBSWIPL_PATH") and env.get("SWI_HOME_DIR"):
        return env
    try:
        out = subprocess.run(["swipl", "--dump-runtime-variables"], capture_output=True, text=True, check=True).stdout
    except (OSError, subprocess.CalledProcessError):
        return env
    rt = {k: v.strip('"') for k, v in (l.rstrip(";").split("=", 1) for l in out.splitlines() if "=" in l)}
    lib = os.path.join(rt["PLLIBDIR"], "libswipl." + ("dylib" if sys.platform == "darwin" else "so"))
    if os.path.exists(lib):
        env["LIBSWIPL_PATH"], env["SWI_HOME_DIR"] = lib, rt["PLBASE"]
    return env


def run_pytest(kind, seed, out_path, python, tests, timeout, per_test):
    """`tests` is a path or a list of pytest node ids."""
    env = swipl_env()
    env.update(DPL_MUT_KIND=kind, DPL_MUT_SEED=str(seed), DPL_MUT_OUT=out_path, DPL_MUT_TMO=str(per_test))
    env["PYTHONPATH"] = HERE + os.pathsep + env.get("PYTHONPATH", "")
    targets = [tests] if isinstance(tests, str) else list(tests)
    cmd = [python, "-m", "pytest", *targets, "-q", "-p", "dpl_mutation_plugin", "-p", "no:cacheprovider"]
    try:
        proc = subprocess.run(cmd, cwd=DPL, env=env, capture_output=True, text=True, timeout=timeout)
        return proc.returncode, proc.stdout[-1500:]
    except subprocess.TimeoutExpired:
        return -9, f"WHOLE RUN TIMEOUT>{timeout}s"


def _seen(path, kind, seed):
    out = set()
    for line in open(path):
        r = json.loads(line)
        if r["kind"] == kind and r["seed"] == seed:
            out.add(r["test"])
    return out


def run_seed(kind, seed, expected, raw, a):
    """Run the whole suite; if the interpreter dies (SWI-Prolog can kill the process), isolate the test
    that was running when it died, record it as a crash, and carry on with the tests not yet observed."""
    code, tail = run_pytest(kind, seed, raw, a.python, a.tests, a.run_timeout, a.per_test_timeout)
    crashes = 0
    missing = [t for t in expected if t not in _seen(raw, kind, seed)]
    while missing and crashes < len(expected):
        first = missing[0]
        c2, t2 = run_pytest(kind, seed, raw, a.python, [first], a.run_timeout, a.per_test_timeout)
        if first not in _seen(raw, kind, seed):
            crashes += 1
            with open(raw, "a") as f:
                f.write(json.dumps({"kind": kind, "seed": seed, "test": first, "outcome": "crash", "when": "call",
                                    "exc_type": "ProcessDied", "exc_msg": f"pytest exited with code {c2} and no result: {t2[-200:]!r}",
                                    "applied": True, "mutations": ["(process died before the mutation could be recorded)"],
                                    "range_violations": [], "secs": 0}) + "\n")
        missing = [t for t in expected if t not in _seen(raw, kind, seed)]
        if missing and len(missing) > 1:
            run_pytest(kind, seed, raw, a.python, missing, a.run_timeout, a.per_test_timeout)
            missing = [t for t in expected if t not in _seen(raw, kind, seed)]
    return code, crashes


def classify(kind, rec, base):
    """Return a category string for one mutated test run."""
    if rec["outcome"] == "crash":
        return "process_crash"
    if not rec["applied"]:
        return "not_applicable"            # nothing to mutate in this test's program / engine
    if base is None or base["outcome"] != "passed":
        return "baseline_not_passing"
    if rec["range_violations"]:
        return "range_violation"
    if rec["outcome"] == "passed":
        return "unchanged" if kind in PRESERVING else "still_passes"
    if rec["outcome"] == "skipped":
        return "skipped"
    if (rec["exc_msg"] or "").startswith("TIMEOUT"):
        return "timeout"
    if rec["exc_type"] in ("AssertionError", "KeyError"):
        if kind in PRESERVING:
            return "metamorphic_violation"
        return "expected_value_changed" if rec["exc_type"] == "AssertionError" else "answer_missing"
    return "exception"


def show_runs(runs):
    """Print what each mutated run actually passed to Model: the changed lines of the program, before -> after."""
    print("\n--- values passed to Model (before -> after) ---")
    for r in runs:
        if not r.get("programs"):
            continue
        print(f"\nseed {r['seed']}  {r['test'].split('tests/')[-1]}  [{r['category']}]  {'; '.join(r['mutations'])}")
        for p in r["programs"]:
            before = [l.rstrip() for l in p["before"].splitlines() if l.strip()]
            after = [l.rstrip() for l in p["after"].splitlines() if l.strip()]
            diff = [l for l in difflib.unified_diff(before, after, lineterm="", n=0)
                    if not l.startswith(("---", "+++", "@@"))]
            if kind_is_reorder(r):
                print("   order before:", [l.strip() for l in p["before"].strip().splitlines() if l.strip() and not l.strip().startswith("%")])
                print("   order after: ", [l.strip() for l in p["after"].strip().splitlines() if l.strip()])
            else:
                for l in diff:
                    print("   " + l)


def kind_is_reorder(r):
    return r["kind"] == "reorder"


def main(kind, description):
    ap = argparse.ArgumentParser(description=description)
    ap.add_argument("--python", default=sys.executable, help="interpreter that has deepproblog's dependencies")
    ap.add_argument("--tests", default="src/deepproblog/tests", help="path inside frameworks/deepproblog")
    ap.add_argument("--seeds", type=int, default=10, help="number of mutated runs (different RNG seeds)")
    ap.add_argument("--first-seed", type=int, default=1)
    ap.add_argument("--per-test-timeout", type=int, default=20)
    ap.add_argument("--run-timeout", type=int, default=600)
    ap.add_argument("--show", action="store_true", help="print the program before/after mutation for every mutated run")
    a = ap.parse_args()

    os.makedirs(RESULT, exist_ok=True)
    raw = os.path.join(RESULT, f"fuzz_{kind}_raw.jsonl")
    open(raw, "w").close()

    t0 = time.time()
    print(f"[{kind}] baseline run (no mutation)", flush=True)
    code, tail = run_pytest("none", 0, raw, a.python, a.tests, a.run_timeout, a.per_test_timeout)
    baseline = {}
    for line in open(raw):
        r = json.loads(line)
        baseline[r["test"]] = r
    n_pass = sum(1 for r in baseline.values() if r["outcome"] == "passed")
    print(f"[{kind}] baseline: {n_pass}/{len(baseline)} tests pass (pytest exit {code})", flush=True)
    if not baseline:
        print(tail)
        sys.exit("baseline produced no records; check the environment")

    seeds = range(a.first_seed, a.first_seed + a.seeds)
    expected = [t for t in baseline]
    for s in seeds:
        code, crashes = run_seed(kind, s, expected, raw, a)
        print(f"[{kind}] seed {s}: pytest exit {code}, interpreter crashes isolated: {crashes}", flush=True)

    runs, counts, per_test = [], collections.Counter(), collections.defaultdict(collections.Counter)
    for line in open(raw):
        r = json.loads(line)
        if r["kind"] == "none":
            continue
        cat = classify(kind, r, baseline.get(r["test"]))
        r["category"] = cat
        runs.append(r)
        counts[cat] += 1
        per_test[r["test"]][cat] += 1

    if a.show:
        show_runs(runs)

    findings = [r for r in runs if r["category"] in FINDINGS]
    summary = {"kind": kind, "description": description, "seeds": list(seeds), "secs": round(time.time() - t0, 1),
               "baseline": {"tests": len(baseline), "passed": n_pass},
               "category_counts": dict(counts),
               "per_test": {t: dict(c) for t, c in sorted(per_test.items())},
               "findings": findings}
    with open(os.path.join(RESULT, f"fuzz_{kind}.json"), "w") as f:
        json.dump(summary, f, indent=1)

    print(f"\n[{kind}] done in {summary['secs']}s. categories: {dict(counts)}")
    print(f"[{kind}] {len(findings)} finding(s); details in {os.path.join(RESULT, f'fuzz_{kind}.json')}")
    for r in findings[:10]:
        print(f"  {r['category']}: {r['test']} seed={r['seed']} {r['mutations']} -> {r['exc_type']}: {(r['exc_msg'] or '')[:100]} {r['range_violations'][:1]}")
