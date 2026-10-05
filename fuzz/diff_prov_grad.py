"""Gradient self-consistency of every differentiable Scallop provenance:
autograd gradient of the forward value  vs  central finite difference of the same forward function.
No semantics needed: whatever a provenance computes, its derivative must match its own function (away from kinks)."""
import collections, itertools, os, random, sys, warnings
warnings.filterwarnings("ignore")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import torch, scallopy
from nesy_prog import gen_prog, shrink
from scallop_fuzz import scl_rule

PROVS = ["diffminmaxprob", "diffaddmultprob", "diffmaxmultprob", "diffnandminprob", "diffnandmultprob",
         "difftopkproofs", "difftopbottomkclauses", "diffaddmultprob2", "diffnandmultprob2", "diffmaxmultprob2"]
H = 1e-2

def forward_values(prog, prov, probs):
    """values[(rel, tuple)] as a list of tensors (graph kept) for given fact-probability tensor list."""
    ctx = scallopy.ScallopContext(provenance=prov, k=10)
    idx = {rel: [i for i, f in enumerate(prog.facts) if f[0] == rel] for rel in prog.edb}
    for rel, ar in prog.edb.items():
        types = tuple([int] * ar); mapping = [prog.facts[i][1] for i in idx[rel]]
        ctx.add_relation(rel, types, input_mapping=mapping) if mapping else ctx.add_relation(rel, types)
    for r in prog.rules:
        ctx.add_rule(scl_rule(r))
    inputs = {rel: torch.stack([probs[i] for i in ids]).unsqueeze(0) for rel, ids in idx.items() if ids}
    out = {}
    for rel in prog.idb:
        tuples = prog.possible_tuples(rel)
        res = ctx.forward_function(rel, output_mapping=tuples)(**inputs)
        for j, t in enumerate(tuples):
            out[(rel, t)] = res[0, j]
    return out

def check(prog, prov):
    base = [torch.tensor(f[2], dtype=torch.float32, requires_grad=True) for f in prog.facts]
    vals = forward_values(prog, prov, base)
    bad = []
    for (rel, t), v in vals.items():
        grads = torch.autograd.grad(v, base, retain_graph=True, allow_unused=True)
        for i, g in enumerate(grads):
            ag = 0.0 if g is None else float(g)
            hi = [b.detach().clone() for b in base]; lo = [b.detach().clone() for b in base]
            hi[i] += H; lo[i] -= H
            num = (float(forward_values(prog, prov, hi)[(rel, t)]) - float(forward_values(prog, prov, lo)[(rel, t)])) / (2 * H)
            if abs(ag - num) > 4e-3 + 0.03 * abs(num):
                bad.append(f"d {rel}{t} / d fact#{i}{prog.facts[i][:2]}: autograd={ag:.4f} numeric={num:.4f}")
    return bad

def safe_check(prog, prov):
    try:
        return check(prog, prov), None
    except BaseException as e:
        if isinstance(e, KeyboardInterrupt): raise
        return [], f"{type(e).__name__}: {str(e)[:90]}"

def main(n=120, seed=0):
    rng = random.Random(seed)
    progs = []
    while len(progs) < n:
        p = gen_prog(rng, allow_neg=False, allow_groups=False, boundary_rate=0.0, max_facts=6)
        p.facts = [(r, t, round(rng.uniform(0.08, 0.92), 3)) for (r, t, _) in p.facts]       # avoid kinks and boundaries
        if p.is_cyclic():
            continue
        progs.append(p)
    for prov in PROVS:
        stats = collections.Counter(); first = None; err_example = None
        for p in progs:
            bad, err = safe_check(p, prov)
            if err:
                stats["error"] += 1; err_example = err_example or err
            elif bad:
                stats["gradient_mismatch"] += 1
                if first is None:
                    small = shrink(p, lambda q: bool(safe_check(q, prov)[0]))
                    first = (small, safe_check(small, prov)[0][:2])
            else:
                stats["ok"] += 1
        print(f"{prov:24s} {dict(stats)}" + (f"   error e.g. {err_example}" if err_example else ""))
        if first:
            print("    minimal mismatch:", first[1]); print("    " + first[0].to_text().replace("\n", "\n    "))

if __name__ == "__main__":
    main(*(int(a) for a in sys.argv[1:]))
