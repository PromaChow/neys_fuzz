"""Extract the Scallop programs (and the provenance they are tested under) from the original Rust tests."""
import glob
import json
import os
import re
import subprocess
import sys

ROOT = os.path.join(os.path.dirname(__file__), "..", "frameworks", "scallop")
SCLI = os.path.join(os.path.dirname(__file__), "..", ".cargo-target", "debug", "scli")
OUT = os.path.join(os.path.dirname(__file__), "..", "results", "seeds", "scallop_seeds.json")
PROV_MAP = {"unit": "unit", "boolean": "bool", "proofs": "proofs", "tropical": "tropical",
            "real_tropical": "realtropical", "min_max_prob": "minmaxprob", "add_mult_prob": "addmultprob",
            "top_k_proofs": "topkproofs", "top_bottom_k_clauses": "topbottomkclauses"}
RAW = re.compile(r'r(#+)"(.*?)"\1', re.S)
NONDET = re.compile(r"sample<|uniform<|categorical<|random|rand\(|\bhash\b|\$time|datetime|duration|\bnow\b")


def test_blocks(src):
    for m in re.finditer(r"#\[test\]\s*(?:#\[[^\]]*\]\s*)*fn\s+(\w+)\s*\(\)\s*\{", src):
        i, depth = m.end(), 1
        while i < len(src) and depth:
            depth += {"{": 1, "}": -1}.get(src[i], 0)
            i += 1
        yield m.group(1), src[m.end():i]


def provenance_of(body):
    m = re.search(r"([a-z_]+)::(\w+Provenance)", body)
    if m:
        return PROV_MAP.get(m.group(1)), m.group(1), None if "top_k" not in m.group(1) else (re.search(r"new\((\d+)", body).group(1) if re.search(r"new\((\d+)", body) else "3")
    return "unit", "unit(default)", None


def run_scli(program, prov, k=3, timeout=20, extra=()):
    import tempfile
    with tempfile.NamedTemporaryFile("w", suffix=".scl", delete=False) as f:
        f.write(program)
        path = f.name
    try:
        r = subprocess.run([SCLI, path, "-p", prov, "-k", str(k), "--output-all", *extra],
                           capture_output=True, text=True, timeout=timeout)
        return {"rc": r.returncode, "out": r.stdout, "err": r.stderr[-400:]}
    except subprocess.TimeoutExpired:
        return {"rc": -9, "out": "", "err": f"TIMEOUT>{timeout}s"}
    finally:
        os.unlink(path)


def main():
    seeds, skipped = [], {"no_program": 0, "negative_test": 0, "nondeterministic": 0, "unsupported_prov": 0}
    files = sorted(glob.glob(os.path.join(ROOT, "core", "tests", "**", "*.rs"), recursive=True))
    for fp in files:
        src = open(fp).read()
        for name, body in test_blocks(src):
            progs = [m.group(2) for m in RAW.finditer(body)]
            if not progs:
                skipped["no_program"] += 1
                continue
            if re.search(r"expect_\w*(failure|fail)\w*|should_panic|expect_compile_failure", body):
                skipped["negative_test"] += 1
                continue
            prov, prov_raw, k = provenance_of(body)
            if prov is None:
                skipped["unsupported_prov"] += 1
                continue
            for j, p in enumerate(progs):
                if NONDET.search(p):
                    skipped["nondeterministic"] += 1
                    continue
                seeds.append({"id": len(seeds), "file": os.path.relpath(fp, ROOT), "test": name, "idx": j,
                              "provenance": prov, "provenance_rust": prov_raw, "k": int(k or 3), "program": p})
    # baseline replay through scli
    ok = 0
    for s in seeds:
        r = run_scli(s["program"], s["provenance"], s["k"])
        s["baseline"] = {"rc": r["rc"], "out": r["out"], "err": r["err"]}
        ok += r["rc"] == 0
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    json.dump(seeds, open(OUT, "w"), indent=1)
    print(f"{len(seeds)} program seeds extracted from {len(files)} test files; replay through scli: {ok} ok, {len(seeds) - ok} failed")
    print("skipped:", skipped)
    import collections
    print("by provenance:", dict(collections.Counter(s["provenance"] for s in seeds)))
    print("probabilistic (contain '::'):", sum("::" in s["program"] for s in seeds))


if __name__ == "__main__":
    main()
