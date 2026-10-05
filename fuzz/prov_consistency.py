"""Scallop provenance consistency: the same program under many provenances must (a) never panic/hang,
(b) for monotone programs derive the same SET of tuples as `unit`, (c) keep tags in [0,1] for probabilistic ones."""
import collections, json, os, re, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from extract_scl_seeds import run_scli
from mutate_scl import parse_output, NONMONO

HERE = os.path.dirname(os.path.abspath(__file__))
SEEDS = os.path.join(HERE, "..", "results", "seeds", "scallop_seeds.json")
OUT = os.path.join(HERE, "..", "results", "prov_consistency.jsonl")
CONFIGS = [("bool", 3), ("proofs", 3), ("tropical", 3), ("realtropical", 3), ("minmaxprob", 3), ("addmultprob", 3),
           ("topkproofs", 3), ("topkproofs", 1000), ("topbottomkclauses", 3)]
PROB = {"minmaxprob", "addmultprob", "topkproofs", "topbottomkclauses"}

def support(rels):
    return {(r, t) for r, d in rels.items() for t in d if not r.startswith("adt#")}

def main():
    seeds = [s for s in json.load(open(SEEDS)) if s["baseline"]["rc"] == 0]
    stats = collections.Counter(); rows = []
    for s in seeds:
        prog = s["program"]
        base = run_scli(prog, "unit", 3)
        if base["rc"] != 0:
            continue
        base_sup = support(parse_output(base["out"]))
        monotone = not NONMONO.search(prog) and "::" not in prog        # plain monotone Datalog: all provenances agree on the support
        for prov, k in CONFIGS:
            r = run_scli(prog, prov, k, timeout=20)
            stats["runs"] += 1
            row = {"seed": s["id"], "test": s["test"], "file": s["file"], "prov": prov, "k": k, "findings": []}
            if r["rc"] == -9:
                row["findings"].append(("timeout", r["err"]))
            elif r["rc"] != 0:
                err = r["err"]
                if "panicked" in err or "Runtime Error" in err or "Segmentation" in err or r["rc"] < 0:
                    row["findings"].append(("panic", err.strip().splitlines()[-1][:140] if err.strip() else f"rc={r['rc']}"))
                else:
                    stats["clean_error"] += 1
            else:
                out = parse_output(r["out"])
                if monotone:
                    sup = support(out)
                    if sup != base_sup:
                        diff = sorted(map(str, sup ^ base_sup))[:3]
                        row["findings"].append(("support_differs_from_unit", f"{len(base_sup)} tuples under unit vs {len(sup)}; e.g. {diff}"))
                if prov in PROB:
                    for rel, d in out.items():
                        for t, tag in d.items():
                            try:
                                v = float(tag)
                            except (TypeError, ValueError):
                                continue
                            if v != v or v < -1e-12 or v > 1 + 1e-9:
                                row["findings"].append(("tag_out_of_range", f"{rel}({t}) = {v}"))
            if row["findings"]:
                rows.append(row)
                for c, _ in row["findings"]:
                    stats[c] += 1
    with open(OUT, "w") as fo:
        for r in rows:
            fo.write(json.dumps(r) + "\n")
    print(dict(stats))
    byprov = collections.Counter((r["prov"], r["k"], c) for r in rows for c, _ in r["findings"])
    for k, n in sorted(byprov.items()): print(f"  {k}: {n}")

if __name__ == "__main__":
    main()
