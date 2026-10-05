"""Mutate the inputs of Scallop's own Rust tests (programs extracted by extract_scl_seeds.py) and judge results.

Mutation operators (inputs of the tests):
  reorder       shuffle rel/query statements                              -> output must be identical
  dup_rule      duplicate a non-probabilistic rule                         -> identical (skipped for addmultprob)
  rename        consistently rename a relation                             -> identical up to the rename
  prob          replace a probability tag (boundary/perturb/complement)    -> no crash, tags in [0,1]
  monotone      raise one tag in a negation/aggregate-free program         -> no output tag may decrease
  prov_swap     run a probabilistic seed under other provenances           -> no crash, tags in [0,1]
  invalid_prob  tag outside [0,1] / disjunction summing above 1            -> should be rejected, not computed
Oracles are metamorphic/invariant based because the expected values of the original tests stop applying.
"""
import argparse
import collections
import json
import math
import os
import random
import re
import sys
import time

sys.path.insert(0, os.path.dirname(__file__))
from extract_scl_seeds import run_scli

HERE = os.path.dirname(__file__)
SEEDS = os.path.join(HERE, "..", "results", "seeds", "scallop_seeds.json")
TAG_RE = re.compile(r"(?P<n>\d*\.\d+(?:[eE]-?\d+)?|\d+(?:[eE]-?\d+)|\d+)\s*::")
BOUNDARY = [0.0, 1.0, 1e-9, 1.0 - 1e-9, 1e-5, 0.99999, 0.5]
KEYWORDS = re.compile(r"^(rel|type|const|query|import|@)\b")
NONMONO = re.compile(r"\bnot\b|\b(count|sum|prod|min|max|exists|forall|argmin|argmax|avg|enumerate|normalize|weighted_sum|sort|top)\b|\$|!=|;")
PROBABILISTIC = {"minmaxprob", "addmultprob", "topkproofs", "topbottomkclauses", "probproofs"}
IDEMPOTENT = {"unit", "bool", "proofs", "minmaxprob", "topkproofs", "tropical", "realtropical"}
RESERVED = {"count", "sum", "prod", "min", "max", "exists", "forall", "argmin", "argmax", "avg", "enumerate",
            "normalize", "weighted_sum", "sort", "top", "string_length", "hash", "abs", "floor", "ceil", "range"}


# ------------------------------------------------------------ text helpers
def split_statements(text):
    stmts, cur = [], []
    for line in text.strip("\n").splitlines():
        if not line.strip():
            continue
        if KEYWORDS.match(line.strip()) and cur and not cur[-1].strip().startswith("@"):
            stmts.append("\n".join(cur))
            cur = []
        cur.append(line)
    if cur:
        stmts.append("\n".join(cur))
    return stmts


def is_decl(s):
    return bool(re.match(r"\s*(type|const|import|@)", s))


def join(stmts):
    return "\n".join(stmts) + "\n"


def parse_output(out):
    """relation -> {tuple_string: tag_string}; handles both tagged and untagged tuples."""
    rels = {}
    for line in out.splitlines():
        m = re.match(r"^([A-Za-z_]\w*): \{(.*)\}\s*$", line)
        if not m:
            continue
        entries = []
        for t in re.finditer(r"(?:(?P<tag>[^,{}()\s:][^,{}()]*?)::)?\((?P<tup>[^()]*)\)", m.group(2)):
            tup = re.sub(r"entity\(0x[0-9a-fA-F]+\)|0x[0-9a-fA-F]+", "ENTITY", t.group("tup").strip())
            entries.append((tup, t.group("tag")))
        entries.sort(key=lambda e: (e[0], str(e[1])))
        d, seen = {}, collections.Counter()
        for tup, tag in entries:                 # masked handles can collide: keep each occurrence
            d[f"{tup}#{seen[tup]}" if "ENTITY" in tup else tup] = tag
            seen[tup] += 1
        rels[m.group(1)] = d
    return rels


def tags_equal(a, b):
    if a is None or b is None:
        return a == b
    try:
        x, y = float(a), float(b)
    except ValueError:
        return a == b
    return abs(x - y) <= 1e-9 + 1e-7 * max(abs(x), abs(y))


def compare_outputs(want, got, rename=None):
    if rename:
        old, new = rename
        want = {(new if k == old else k): v for k, v in want.items()}
    diffs = []
    for rel in sorted(set(want) | set(got)):
        a, b = want.get(rel, {}), got.get(rel, {})
        for t in sorted(set(a) | set(b)):
            if t not in a or t not in b:
                diffs.append(f"{rel}({t}): {'missing in mutant' if t not in b else 'new in mutant'}")
            elif not tags_equal(a[t], b[t]):
                diffs.append(f"{rel}({t}): seed tag {a[t]} vs mutant tag {b[t]}")
    return diffs


def tag_values(rels):
    vals = []
    for rel, d in rels.items():
        for t, tag in d.items():
            try:
                vals.append((rel, t, float(tag)))
            except (TypeError, ValueError):
                pass
    return vals


# ------------------------------------------------------------ mutation operators
def mutate_tag(stmts, rng, mode):
    cands = [(i, m) for i, s in enumerate(stmts) for m in TAG_RE.finditer(s)]
    if not cands:
        return None
    i, m = rng.choice(cands)
    old = float(m.group("n"))
    if mode == "up":                                   # monotone: only increase, no disjunction involved
        new = min(1.0, old + rng.choice([1e-6, 1e-3, 0.05, 0.3, 1.0 - old]))
        desc = f"raise tag {old!r} -> {new!r}"
    else:
        kind = rng.choice(["boundary", "boundary", "perturb", "complement"])
        new = rng.choice(BOUNDARY) if kind == "boundary" else (
            1.0 - old if kind == "complement" else min(max(old + rng.choice([-1, 1]) * rng.choice([1e-9, 1e-6, 1e-3, 0.1]), 0.0), 1.0))
        desc = f"tag {old!r} -> {new!r} ({kind})"
    s = stmts[i]
    siblings = [x for x in TAG_RE.finditer(s) if x is not m]
    scale = 1.0
    if ";" in s and siblings and mode != "up":         # annotated disjunction: keep the group sum <= 1
        rest = sum(float(x.group("n")) for x in siblings)
        budget = max(1.0 - new, 0.0)
        if rest > budget:
            scale = (budget / rest) if rest > 0 else 0.0
            desc += f" (rescaled {len(siblings)} sibling alternative(s))"
    out, last = [], 0
    for x in TAG_RE.finditer(s):
        out.append(s[last:x.start("n")])
        out.append(repr(float(new)) if x is m else (repr(float(x.group("n")) * scale) if scale != 1.0 else x.group("n")))
        last = x.end("n")
    out.append(s[last:])
    r = list(stmts)
    r[i] = "".join(out)
    return r, desc


def declared_names(stmts):
    names = set()
    for s in stmts:
        for m in re.finditer(r"^\s*(?:rel|type)\s+([a-z_]\w*)", s):
            names.add(m.group(1))
    return {n for n in names if n not in RESERVED}


def make_mutants(seed, rng, n):
    stmts = split_statements(seed["program"])
    prov = seed["provenance"]
    probabilistic = "::" in seed["program"] and prov in PROBABILISTIC
    monotone_ok = probabilistic and not NONMONO.search(seed["program"])
    ops = ["reorder", "dup_rule", "rename"]
    if probabilistic:
        ops += ["prob", "prob", "prob", "prov_swap", "invalid_prob", "invalid_prob"]
        if monotone_ok:
            ops += ["monotone", "monotone", "monotone"]
    ms = []
    for _ in range(n):
        op = rng.choice(ops)
        m = {"seed": seed["id"], "op": op, "provenance": prov, "k": seed["k"], "expect": "invariants"}
        if op == "reorder":
            decl = [s for s in stmts if is_decl(s)]
            body = [s for s in stmts if not is_decl(s)]
            if len(body) < 2:
                continue
            b2 = list(body)
            rng.shuffle(b2)
            if b2 == body:
                continue
            m.update(program=join(decl + b2), desc="shuffle rel/query statements", expect="same")
        elif op == "dup_rule":
            if prov == "addmultprob":
                continue
            rules = [i for i, s in enumerate(stmts) if re.match(r"\s*rel\s+\w+\s*\(.*\)\s*(=|:-)", s) and "::" not in s]
            if not rules:
                continue
            i = rng.choice(rules)
            m.update(program=join(stmts[:i + 1] + [stmts[i]] + stmts[i + 1:]), desc=f"duplicate rule #{i}", expect="same")
        elif op == "rename":
            names = sorted(declared_names(stmts))
            if not names:
                continue
            old = rng.choice(names)
            new = old + "_rn"
            sub = lambda s: re.sub(rf"(?<![A-Za-z0-9_]){re.escape(old)}(?![A-Za-z0-9_])", new, s)
            m.update(program=join([sub(s) for s in stmts]), desc=f"rename relation {old} -> {new}", expect="same", renamed=(old, new))
        elif op == "prob":
            r = mutate_tag(stmts, rng, "any")
            if r is None:
                continue
            m.update(program=join(r[0]), desc=r[1])
        elif op == "monotone":
            r = mutate_tag(stmts, rng, "up")
            if r is None:
                continue
            m.update(program=join(r[0]), desc=r[1], expect="monotone")
            if prov == "topkproofs":
                m["k"] = 1000                     # top-k truncation can legitimately break monotonicity; compare at large k
                m["compare_to_k1000"] = True
        elif op == "prov_swap":
            other = rng.choice([p for p in ["minmaxprob", "addmultprob", "topkproofs", "topbottomkclauses"] if p != prov])
            m.update(program=join(stmts), desc=f"provenance {prov} -> {other}", provenance=other, k=rng.choice([1, 3, 1000]))
        elif op == "invalid_prob":
            if rng.random() < 0.5:
                cands = [(i, x) for i, s in enumerate(stmts) for x in TAG_RE.finditer(s)]
                if not cands:
                    continue
                i, x = rng.choice(cands)
                bad = rng.choice(["1.5", "2.0"])
                s = stmts[i]
                r = list(stmts)
                r[i] = s[:x.start("n")] + bad + s[x.end("n"):]
                m.update(program=join(r), desc=f"tag {x.group('n')} -> {bad} (> 1)", expect="reject")
            else:
                ad = [i for i, s in enumerate(stmts) if ";" in s and len(TAG_RE.findall(s)) >= 2]
                if not ad:
                    continue
                i = rng.choice(ad)
                tags = list(TAG_RE.finditer(stmts[i]))
                x = tags[0]
                others = sum(float(t.group("n")) for t in tags[1:])
                new = round(max(1.0 - others, 0.0) + 0.3, 6)       # group sum becomes exactly 1.3
                r = list(stmts)
                r[i] = stmts[i][:x.start("n")] + repr(new) + stmts[i][x.end("n"):]
                m.update(program=join(r), desc=f"annotated disjunction made to sum to 1.3 (first alternative -> {new})", expect="reject")
        ms.append(m)
    return ms


# ------------------------------------------------------------ judging
def judge(m, seed, res, base_res_for_k1000=None):
    f = []
    rc, err = res["rc"], res["err"]
    if rc == -9:
        return [("timeout", err)]
    if rc != 0:
        kind = "panic" if "panicked" in err or "Runtime Error" in err else "compile_error"
        if m["expect"] in ("reject", "reject_if_sum_gt_1"):
            return [("rejected_as_expected", err.strip().splitlines()[-1][:100] if err.strip() else "rc!=0")]
        return [(f"{kind}_on_valid_mutant", err.strip().splitlines()[-1][:160] if err.strip() else f"rc={rc}")]
    got = parse_output(res["out"])
    vals = tag_values(got)
    prov = m["provenance"]
    if prov in PROBABILISTIC:
        for rel, t, v in vals:
            if math.isnan(v) or v < -1e-12 or v > 1 + 1e-9:
                f.append(("range_violation", f"{rel}({t}) tag {v!r}"))
    if m["expect"] in ("reject", "reject_if_sum_gt_1"):
        f.append(("accepted_invalid_probability", f"program accepted; outputs {dict(list(((r, t), v) for r, t, v in vals)[:3])}"))
    if m["expect"] == "same":
        want = parse_output(seed["baseline"]["out"])
        for d in compare_outputs(want, got, m.get("renamed"))[:4]:
            f.append(("metamorphic_violation", d))
    if m["expect"] == "monotone" and base_res_for_k1000 is not None:
        before = {(r, t): v for r, t, v in tag_values(parse_output(base_res_for_k1000["out"]))}
        after = {(r, t): v for r, t, v in vals}
        for key, v0 in before.items():
            v1 = after.get(key)
            if v1 is None or v1 < v0 - 1e-9:
                f.append(("monotonicity_violation", f"{key[0]}({key[1]}): {v0!r} -> {v1!r} after raising one input tag"))
    return f


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--unit-mutants", type=int, default=12)
    ap.add_argument("--prob-mutants", type=int, default=80)
    ap.add_argument("--rng", type=int, default=0)
    ap.add_argument("--out", default=os.path.join(HERE, "..", "results", "scl_mutation_results.jsonl"))
    a = ap.parse_args()
    rng = random.Random(a.rng)
    seeds = [s for s in json.load(open(SEEDS)) if s["baseline"]["rc"] == 0]
    print(f"{len(seeds)} seeds with a clean unmutated replay", flush=True)
    summary = collections.defaultdict(lambda: collections.Counter())
    n = 0
    with open(a.out, "w") as fo:
        for seed in seeds:
            prob = "::" in seed["program"] and seed["provenance"] in PROBABILISTIC
            for m in make_mutants(seed, rng, a.prob_mutants if prob else a.unit_mutants):
                res = run_scli(m["program"], m["provenance"], m["k"])
                base_k = None
                if m["expect"] == "monotone":
                    base_k = run_scli(seed["program"], m["provenance"], m["k"])
                    if base_k["rc"] != 0:
                        continue
                findings = judge(m, seed, res, base_k["out"] if False else base_k)
                n += 1
                cats = {c for c, _ in findings} or {"clean"}
                for c in cats:
                    summary[m["op"]][c] += 1
                fo.write(json.dumps({**{k: v for k, v in m.items() if k != "program"}, "program": m["program"],
                                     "test": seed["test"], "file": seed["file"], "findings": findings}) + "\n")
    print(f"ran {n} mutants")
    for op, c in summary.items():
        print(f"  {op:13s}", dict(c))


if __name__ == "__main__":
    main()
