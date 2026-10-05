"""Run LNN's own tests (all 132: the 117 pytest collects plus the 15 functions named `test` that its config never collects)
under each mutation of the data they feed to Model.add_data(), then aggregate (see mutate_lnn_tests.py)."""
import collections
import json
import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.join(HERE, "..")
LNN = os.path.join(ROOT, "frameworks", "LNN")
OUTDIR = os.path.join(ROOT, "results", "lnn_test_mutation")
RUNS = ["none:0", "none:1", "boundary:1", "boundary:2", "boundary:3", "perturb:1", "perturb:2", "perturb:3", "complement:1", "reorder:1"]


def run_one(spec):
    out = os.path.join(OUTDIR, spec.replace(":", "_") + ".json")
    env = dict(os.environ, NESY_LNN_MUT=spec, NESY_LNN_OUT=out, PYTHONPATH=f"{LNN}:{HERE}")
    subprocess.run([sys.executable, "-m", "pytest", "tests", "-q", "-p", "mutate_lnn_tests", "-p", "no:cacheprovider",
                    "-o", "python_functions=test test_*", "-o", "addopts="], cwd=LNN, env=env, capture_output=True, text=True, timeout=1500)
    return json.load(open(out))


def main():
    os.makedirs(OUTDIR, exist_ok=True)
    results = {}
    for spec in RUNS:
        results[spec] = run_one(spec)
        c = collections.Counter(results[spec]["outcomes"].values())
        print(spec, dict(c), flush=True)
    base = results["none:0"]
    summary = {"runs": {}, "findings": []}
    for spec, r in results.items():
        c = collections.Counter(r["outcomes"].values())
        ev = collections.Counter(e["finding"] for e in r["events"])
        summary["runs"][spec] = {"tests": len(r["outcomes"]), "outcomes": dict(c), "findings": dict(ev)}
        for e in r["events"]:
            summary["findings"].append({"run": spec, **e})
    # order dependence: reorder run vs baseline, snapshot by snapshot; rows compared as sorted multisets (grounding order is
    # not meaningful) and only for tests whose two unmodified runs agree (some tests draw random numbers)
    def norm(snap):
        return {k: sorted(map(tuple, rows)) for k, rows in snap.items()}

    def same(a, b):
        return len(a) == len(b) and all(norm(x).keys() == norm(y).keys() and all(
            len(norm(x)[k]) == len(norm(y)[k]) and all(abs(p - q) <= 1e-6 for r1, r2 in zip(norm(x)[k], norm(y)[k]) for p, q in zip(r1, r2))
            for k in norm(x)) for x, y in zip(a, b))
    reo = results["reorder:1"]
    base2 = results["none:1"]
    deterministic = [t for t in base["snapshots"] if same(base["snapshots"][t], base2["snapshots"].get(t, []))]
    nondeterministic = [t for t in base["snapshots"] if t not in deterministic]
    diffs = []
    for test in deterministic:
        if not same(base["snapshots"][test], reo["snapshots"].get(test, [])):
            diffs.append((test, "bounds depend on the order of the entries given to add_data"))
    summary_extra = {"tests_with_snapshots": len(base["snapshots"]), "nondeterministic_tests": nondeterministic, "deterministic_tests": len(deterministic)}
    summary["order_dependence"] = [list(map(str, d)) for d in diffs]
    summary.update(summary_extra)
    json.dump(summary, open(os.path.join(OUTDIR, "summary.json"), "w"), indent=1)
    print("baseline outcomes:", dict(collections.Counter(base["outcomes"].values())))
    print("mutation runs:", {k: v["outcomes"] for k, v in summary["runs"].items() if k != "none:0"})
    print("findings by kind:", dict(collections.Counter(f["finding"] for f in summary["findings"])))
    print("tests with a snapshot:", summary_extra["tests_with_snapshots"], "| deterministic:", summary_extra["deterministic_tests"], "| order-dependent:", len(diffs))
    for dd in diffs[:10]:
        print("   order-dependent:", dd[0])
    seen = set()
    for f in summary["findings"]:
        key = (f["test"], f["finding"], str(f["detail"])[:60])
        if key not in seen and len(seen) < 25:
            seen.add(key); print("  ", f["run"], f["test"].split("/")[-1], f["finding"], str(f["detail"])[:140])


if __name__ == "__main__":
    main()
