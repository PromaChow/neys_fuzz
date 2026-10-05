"""Grammar fuzz of NeurASP's MVPP front end against clingo on plain ASP.
Programs are random mixes of ASP constructs and formatting; both systems must report the same answer sets."""
import collections, json, os, random, re, sys, tempfile, warnings
warnings.filterwarnings("ignore")
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "frameworks", "NeurASP"))
import clingo
from mvpp import MVPP

STATEMENTS = {   # name -> text (each defines atoms over a tiny vocabulary; all are valid ASP)
 "fact":            "a.",
 "fact_arg":        "p(1).",
 "range_fact":      "p(1..3).",
 "pool_fact":       "q(1;2).",
 "rule_not":        "c :- a, not b.",
 "rule_cmp":        "d(X) :- p(X), X > 1.",
 "rule_arith":      "e(X+1) :- p(X).",
 "choice_plain":    "{g(1); g(2)}.",
 "choice_bound":    "1 {h(1); h(2)} 1.",
 "choice_cond":     "0 {i(X): p(X)} 2.",
 "choice_lower":    "2 {j(1..3)}.",
 "choice_body":     "{k} :- a.",
 "count_body":      "m :- #count{X: p(X)} >= 2.",
 "sum_body":        "s :- #sum{X: p(X)} > 3.",
 "constraint":      ":- g(1), g(2).",
 "constraint_count": ":- #count{X: h(X)} != 1.",
 "disj_pipe":       "l | m2.",
 "disj_semicolon":  "n ; o.",
 "weak":            ":~ g(1). [1@1]",
 "show":            "#show c/0.",
 "const":           "#const n = 3.",
 "minimize":        "#minimize{1,X: g(X)}.",
 "negneg":          "r :- not not a.",
}
FORMATS = ["{s}", "  {s}", "{s} % trailing comment", "% a comment line\n{s}", "{s}\n", "%* block *% {s}", "\t{s}"]

def clingo_models(text):
    ctl = clingo.Control(["200", "--warn=none"]); ctl.add("base", [], text); ctl.ground([("base", [])])
    out = []; ctl.solve(on_model=lambda m: out.append(tuple(sorted(str(a) for a in m.symbols(atoms=True)))))
    return set(out)

def neurasp_models(path):
    return {tuple(sorted(m)) for m in MVPP(path).find_all_SM_under_obs("")}

def run_one(stmt_names, fmts):
    text = "\n".join(FORMATS[f].format(s=STATEMENTS[n]) for n, f in zip(stmt_names, fmts)) + "\n"
    try:
        ref = clingo_models(text)
    except BaseException:
        return None, text
    if len(ref) > 150:
        return None, text
    with tempfile.NamedTemporaryFile("w", suffix=".lp", delete=False) as f:
        f.write(text); path = f.name
    try:
        got = neurasp_models(path)
        verdict = "same" if got == ref else f"different ({len(ref)} vs {len(got)} answer sets)"
    except SystemExit:
        verdict = "SystemExit"
    except BaseException as e:
        verdict = type(e).__name__
    finally:
        os.unlink(path)
    return verdict, text

def shrink(names, fmts):
    cur_n, cur_f = list(names), list(fmts)
    def bad(n, f):
        v, _ = run_one(n, f); return v is not None and v != "same"
    changed = True
    while changed:
        changed = False
        for i in range(len(cur_n)):
            n2, f2 = cur_n[:i] + cur_n[i+1:], cur_f[:i] + cur_f[i+1:]
            if n2 and bad(n2, f2):
                cur_n, cur_f, changed = n2, f2, True; break
        if changed: continue
        for i in range(len(cur_f)):                       # also try the plainest formatting
            if cur_f[i] != 0:
                f2 = list(cur_f); f2[i] = 0
                if bad(cur_n, f2):
                    cur_f, changed = f2, True; break
    return cur_n, cur_f

def main(n=500, seed=0):
    rng = random.Random(seed); names = list(STATEMENTS)
    tally = collections.Counter(); minimal = collections.OrderedDict(); tested = 0
    for _ in range(n):
        k = rng.randint(2, 7)
        stm = rng.sample(names, k); fm = [rng.randrange(len(FORMATS)) for _ in stm]
        v, text = run_one(stm, fm)
        if v is None: continue
        tested += 1; tally[v.split(" (")[0]] += 1
        if v != "same":
            mn, mf = shrink(stm, fm)
            key = tuple(mn)
            if key not in minimal:
                vv, tt = run_one(mn, mf)
                minimal[key] = (vv, tt)
    print(f"{tested} valid programs tested | outcomes: {dict(tally)}")
    print(f"\n{len(minimal)} distinct minimal failing programs:")
    for key, (v, t) in minimal.items():
        print(f"  [{v}]  statements: {list(key)}\n      " + t.strip().replace("\n", "\n      "))
    json.dump([{"statements": list(k), "verdict": v, "program": t} for k, (v, t) in minimal.items()],
              open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "results", "neurasp_syntax_fuzz.json"), "w"), indent=1)

if __name__ == "__main__":
    main(*(int(a) for a in sys.argv[1:]))
