"""Differential fuzz: Scallop (unit provenance, native scli) vs clingo on deterministic Datalog with
joins, recursion, negation, comparisons, arithmetic and aggregates. Stratified programs have ONE answer set."""
import collections, json, os, random, re, sys, tempfile, warnings
warnings.filterwarnings("ignore")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import clingo
from extract_scl_seeds import run_scli
from mutate_scl import parse_output

# name -> (scallop text, clingo text, relations it defines)
T = {
 "join":      ("rel r1(x, y) = b(x, z), b(z, y)",                      "r1(X,Y) :- b(X,Z), b(Z,Y).",                 ["r1"]),
 "tc":        ("rel t(x, y) = b(x, y)\nrel t(x, y) = t(x, z), b(z, y)", "t(X,Y) :- b(X,Y).\nt(X,Y) :- t(X,Z), b(Z,Y).", ["t"]),
 "neg":       ("rel u(x) = a(x), not c(x)",                            "u(X) :- a(X), not c(X).",                    ["u"]),
 "neg_edge":  ("rel ne(x, y) = a(x), a(y), not b(x, y)",               "ne(X,Y) :- a(X), a(Y), not b(X,Y).",         ["ne"]),
 "cmp":       ("rel v(x) = a(x), x > 2",                               "v(X) :- a(X), X > 2.",                       ["v"]),
 "neq":       ("rel nq(x, y) = b(x, y), x != y",                       "nq(X,Y) :- b(X,Y), X != Y.",                 ["nq"]),
 "add":       ("rel w(x + y) = a(x), a(y)",                            "w(X+Y) :- a(X), a(Y).",                      ["w"]),
 "sub":       ("rel sb(x - y) = a(x), a(y)",                           "sb(X-Y) :- a(X), a(Y).",                     ["sb"]),
 "mul":       ("rel mu(x * y) = a(x), a(y)",                           "mu(X*Y) :- a(X), a(Y).",                     ["mu"]),
 "div":       ("rel dv(x / y) = a(x), a(y), y != 0",                   "dv(X/Y) :- a(X), a(Y), Y != 0.",             ["dv"]),
 "mod":       ("rel md(x % y) = a(x), a(y), y != 0",                   "md(X\\Y) :- a(X), a(Y), Y != 0.",            ["md"]),
 "neg_num":   ("rel ng(0 - x) = a(x)",                                 "ng(0-X) :- a(X).",                           ["ng"]),
 "count":     ("rel n(k) = k := count(x: a(x))",                       "n(K) :- K = #count{X: a(X)}.",               ["n"]),
 "sum":       ("rel sm(k) = k := sum(x: a(x))",                        "sm(K) :- K = #sum{X: a(X)}.",                ["sm"]),
 "min":       ("rel mn(k) = k := min(x: a(x))",                        "mn(K) :- K = #min{X: a(X)}, K != #sup.",     ["mn"]),
 "max":       ("rel mx(k) = k := max(x: a(x))",                        "mx(K) :- K = #max{X: a(X)}, K != #inf.",     ["mx"]),
 "count_grp": ("rel dg(x, k) = k := count(y: b(x, y))",                "dg(X,K) :- b(X,_), K = #count{Y: b(X,Y)}.",  ["dg"]),
 "sum_grp":   ("rel sg(x, k) = k := sum(y: b(x, y))",                  "sg(X,K) :- b(X,_), K = #sum{Y: b(X,Y)}.",    ["sg"]),
 "exists":    ("rel ex() = exists(x: a(x), x > 3)",                    "ex :- #count{X: a(X), X > 3} >= 1.",         ["ex"]),
 "forall":    ("rel fa() = forall(x: a(x) => c(x))",                   "fa :- #count{X: a(X), not c(X)} = 0.",       ["fa"]),
 "neg_agg":   ("rel nc(x) = a(x), not n_big(x)\nrel n_big(x) = a(x), x > 3", "nc(X) :- a(X), not n_big(X).\nn_big(X) :- a(X), X > 3.", ["nc", "n_big"]),
 "self_join": ("rel sj(x) = a(x), b(x, x)",                            "sj(X) :- a(X), b(X,X).",                     ["sj"]),
 "unify":     ("rel un(x) = b(x, 1)",                                  "un(X) :- b(X,1).",                           ["un"]),
 "const_head": ("rel k5(5) = a(1)",                                    "k5(5) :- a(1).",                             ["k5"]),
}

def edb(rng):
    a = sorted(rng.sample(range(0, 6), rng.randint(1, 5)))
    c = sorted(rng.sample(range(0, 6), rng.randint(1, 4)))
    b = sorted({(rng.randint(0, 4), rng.randint(0, 4)) for _ in range(rng.randint(1, 6))})
    return a, b, c

def texts(names, a, b, c):
    sc = f"rel a = {{{', '.join(map(str, a))}}}\nrel b = {{{', '.join(f'({x}, {y})' for x, y in b)}}}\nrel c = {{{', '.join(map(str, c))}}}\n"
    cl = "".join(f"a({x}). " for x in a) + "".join(f"b({x},{y}). " for x, y in b) + "".join(f"c({x}). " for x in c) + "\n"
    rels = []
    for n in names:
        sc += T[n][0] + "\n"; cl += T[n][1] + "\n"; rels += T[n][2]
    return sc, cl, rels

def clingo_sets(text, rels):
    ctl = clingo.Control(["0", "--warn=none"]); ctl.add("base", [], text); ctl.ground([("base", [])])
    models = []
    ctl.solve(on_model=lambda m: models.append([s for s in m.symbols(atoms=True)]))
    if len(models) != 1:
        return None
    out = {r: set() for r in rels}
    for s in models[0]:
        if s.name in out:
            out[s.name].add(", ".join(str(x) for x in s.arguments))
    return out

def compare(names, a, b, c):
    sc, cl, rels = texts(names, a, b, c)
    try:
        ref = clingo_sets(cl, rels)
    except BaseException:
        return None
    if ref is None:
        return None
    r = run_scli(sc, "unit", 3, timeout=20)
    if r["rc"] != 0:
        kind = "scallop_panic" if ("panicked" in r["err"] or r["rc"] < 0) else "scallop_compile_error"
        return kind, r["err"].strip().splitlines()[-1][:120] if r["err"].strip() else f"rc={r['rc']}", sc, ref
    got = parse_output(r["out"])
    diffs = []
    for rel in rels:
        g = set(got.get(rel, {}).keys())
        if g != ref[rel]:
            diffs.append(f"{rel}: clingo={sorted(ref[rel])[:5]} scallop={sorted(g)[:5]}")
    if diffs:
        return "different_result", "; ".join(diffs)[:300], sc, ref
    return "same", "", sc, ref

def shrink(names, a, b, c, kind):
    cur = list(names)
    ok = lambda n: n and (compare(n, a, b, c) or ("none",))[0] == kind
    ch = True
    while ch:
        ch = False
        for i in range(len(cur)):
            n2 = cur[:i] + cur[i+1:]
            if ok(n2):
                cur, ch = n2, True; break
    return cur

def main(n=400, seed=0):
    rng = random.Random(seed); names = [k for k in T if k not in ('div', 'mod')]   # div/mod: known guard bug, probed separately
    tally = collections.Counter(); minimal = collections.OrderedDict()
    for _ in range(n):
        st = rng.sample(names, rng.randint(1, 5)); a, b, c = edb(rng)
        res = compare(st, a, b, c)
        if res is None: continue
        tally[res[0]] += 1
        if res[0] != "same":
            m = shrink(st, a, b, c, res[0])
            key = (res[0], tuple(m))
            if key not in minimal:
                r2 = compare(m, a, b, c)
                minimal[key] = (r2[1], r2[2])
    print("outcomes:", dict(tally))
    print(f"\n{len(minimal)} distinct minimal failing programs:")
    for (kind, m), (detail, sc) in minimal.items():
        print(f"\n[{kind}] constructs {list(m)}\n   {detail}\n   " + sc.strip().replace("\n", "\n   "))
    json.dump([{"kind": k, "constructs": list(m), "detail": d, "scallop": s} for (k, m), (d, s) in minimal.items()],
              open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "results", "scallop_vs_clingo.json"), "w"), indent=1)

if __name__ == "__main__":
    main(*(int(a) for a in sys.argv[1:]))
