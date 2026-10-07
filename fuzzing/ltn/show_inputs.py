"""Show, for every mutated operator call, what LTNtorch's tests fed in, what the fuzzer fed instead, and what came out.

Usage (from nesy-fuzz/):
  python fuzzing/ltn/show_inputs.py                          # every kind, seeds 1-3, test_Connective + test_Quantifier
  python fuzzing/ltn/show_inputs.py --kinds values permute --seeds 2 --first-seed 5
  python fuzzing/ltn/show_inputs.py --kinds float64 --test test_Connective --max-calls 20

For each run it prints:
  seed / kind / test / pass-fail of the test's own asserts
  and, per mutated operator call:
    original input        the values the test passed to the operator (first 8 elements, plus element count)
    fuzzed input          the values the fuzzer passed instead
    output, original      the operator's result when the ORIGINAL input is fed again (an unmutated call)
    output, fuzzed        the operator's result on the FUZZED input (permute: shuffled back, float64: cast back)
Everything is also saved to fuzzing/ltn/result/inputs_<kind>.json.
"""
import argparse
import json
import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
RESULT = os.path.join(HERE, "result")
LTN = os.path.abspath(os.path.join(HERE, "..", "..", "frameworks", "LTNtorch"))
KINDS = ["values", "permute", "swap", "stable", "float64"]


def fmt(v):
    if isinstance(v, dict) and "first" in v:
        more = f" ... ({v['n']} values)" if v["n"] > len(v["first"]) else ""
        return "[" + ", ".join(f"{x:.6g}" for x in v["first"]) + "]" + more
    return str(v)


def run(kind, seed, test, python, out_path):
    env = dict(os.environ)
    env.update(LTN_MUT_KIND=kind, LTN_MUT_SEED=str(seed), LTN_MUT_OUT=out_path, LTN_MUT_TRACE="1")
    env["PYTHONPATH"] = os.pathsep.join([HERE, LTN, env.get("PYTHONPATH", "")])
    subprocess.run([python, "-W", "ignore", "-m", "pytest", f"tests/tests.py::{test}", "-q", "-p", "ltn_mutation_plugin",
                    "-p", "no:cacheprovider"], cwd=LTN, env=env, capture_output=True, text=True)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--kinds", nargs="+", default=KINDS, choices=KINDS)
    ap.add_argument("--seeds", type=int, default=3, help="number of seeds")
    ap.add_argument("--first-seed", type=int, default=1)
    ap.add_argument("--test", nargs="+", default=["test_Connective", "test_Quantifier"],
                    help="the only tests that call fuzzy operators")
    ap.add_argument("--max-calls", type=int, default=4, help="calls printed per run (all are saved to the json)")
    ap.add_argument("--python", default=sys.executable)
    a = ap.parse_args()

    os.makedirs(RESULT, exist_ok=True)
    for kind in a.kinds:
        tmp = os.path.join(RESULT, f"_inputs_{kind}.jsonl")
        open(tmp, "w").close()
        for seed in range(a.first_seed, a.first_seed + a.seeds):
            for t in a.test:
                run(kind, seed, t, a.python, tmp)
        runs = [json.loads(l) for l in open(tmp)]
        os.remove(tmp)
        print(f"\n{'=' * 100}\nKIND {kind}   seeds {a.first_seed}..{a.first_seed + a.seeds - 1}\n{'=' * 100}")
        for r in runs:
            name = r["test"].split("::")[-1]
            verdict = r["outcome"] + (f" ({r['exc_type']})" if r["exc_type"] else "")
            print(f"\nseed {r['seed']}  {name}  ->  test {verdict};  {len(r['trace'])} operator call(s) mutated of {r['n_calls']}")
            for c in r["trace"][:a.max_calls]:
                print(f"  call #{c['call']}  {c['op']}  [{c['mutation'].split(': ', 1)[-1]}]" + (f"  {c['extra']}" if c["extra"] else ""))
                for i, (o, f) in enumerate(zip(c["original_input"], c["fuzzed_input"])):
                    print(f"     original input {i}: {fmt(o)}")
                    print(f"     fuzzed input   {i}: {fmt(f)}")
                print(f"     output, original input: {fmt(c['output_original_input'])}")
                print(f"     output, fuzzed input:   {fmt(c['output_fuzzed_input'])}")
            if len(r["trace"]) > a.max_calls:
                print(f"  ... {len(r['trace']) - a.max_calls} more call(s) (see the json)")
        with open(os.path.join(RESULT, f"inputs_{kind}.json"), "w") as f:
            json.dump(runs, f, indent=1)
        print(f"\nsaved {os.path.join(RESULT, f'inputs_{kind}.json')}")


if __name__ == "__main__":
    main()
