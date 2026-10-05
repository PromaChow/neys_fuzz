"""Neural-saturation and invariance checks for LTNtorch (the analogue of dimensions D4 and D5 of diff_fuzz.py).

D5  A predicate backed by a sigmoid network saturates (truth value exactly 0.0 or 1.0 in float32) for large logits.
    The formula's value and its gradient w.r.t. the network weight must stay finite, and float32 must agree with float64.
D4  Evaluation-mode invariance: a grounding computed for all individuals at once must equal the one computed individual by
    individual, and must not depend on the order of the individuals or on repeated calls.
"""
import json
import os
import random
import sys
import warnings

warnings.filterwarnings("ignore")
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(HERE, "..", "frameworks", "LTNtorch"))
import numpy as np
import torch
import ltn
from ltn import fuzzy_ops as F

OUT = os.path.join(HERE, "..", "results", "ltn_nn_fuzz.jsonl")
ROWS = []


def formulas(dtype):
    w = torch.nn.Parameter(torch.tensor([1.0], dtype=dtype))
    P = ltn.Predicate(func=lambda x: torch.sigmoid(w * x[:, 0]))
    Q = ltn.Predicate(func=lambda x: torch.sigmoid(-w * x[:, 0]))
    And = ltn.Connective(F.AndProd())
    Imp = ltn.Connective(F.ImpliesReichenbach())
    Not = ltn.Connective(F.NotStandard())
    Forall = ltn.Quantifier(F.AggregPMeanError(p=2), quantifier="f")
    Exists = ltn.Quantifier(F.AggregPMean(p=2), quantifier="e")

    def run(xs):
        x = ltn.Variable("x", xs.reshape(-1, 1))
        return {"forall_P": Forall(x, P(x)).value,
                "exists_P": Exists(x, P(x)).value,
                "forall_imp": Forall(x, Imp(P(x), Not(Q(x)))).value,
                "forall_and": Forall(x, And(P(x), Not(Q(x)))).value}
    return w, run


def add(**kw):
    ROWS.append(kw)


def saturation():
    rng = random.Random(0)
    for scale in (0.0, 1.0, 5.0, 10.0, 17.0, 20.0, 40.0, 88.0, 100.0, 200.0):
        base = torch.tensor([-1.0, -0.5, 0.5, 1.0, 2.0])
        for dtype in (torch.float32,):
            w32, run32 = formulas(torch.float32)
            w64, run64 = formulas(torch.float64)
            xs32, xs64 = base * scale, (base * scale).double()
            r32, r64 = run32(xs32), run64(xs64)
            for name in r32:
                v32, v64 = float(r32[name]), float(r64[name])
                fin = np.isfinite(v32)
                add(dim="D5", check="value", formula=name, scale=scale, float32=v32, float64=v64,
                    ok=bool(fin and abs(v32 - v64) <= 5e-4))
                # gradient of (1 - value) w.r.t. the weight
                for w, r in ((w32, r32), (w64, r64)):
                    w.grad = None
                (1 - r32[name]).backward()
                (1 - r64[name]).backward()
                g32, g64 = float(w32.grad[0]), float(w64.grad[0])
                add(dim="D5", check="gradient", formula=name, scale=scale, float32=g32, float64=g64,
                    ok=bool(np.isfinite(g32) and (abs(g32 - g64) <= 5e-3 * max(1.0, abs(g64)))))
                w32.grad = None; w64.grad = None


def invariance():
    rng = random.Random(1)
    for trial in range(60):
        n = rng.randint(2, 8)
        xs = torch.rand(n)
        w, run = formulas(torch.float32)
        full = run(xs)
        perm = torch.randperm(n)
        permuted = run(xs[perm])
        again = run(xs)
        for name in full:
            add(dim="D4", check="individual_order", formula=name, ok=bool(abs(float(full[name]) - float(permuted[name])) <= 1e-6),
                detail=f"{float(full[name])} vs {float(permuted[name])}")
            add(dim="D4", check="repeated_call", formula=name, ok=bool(float(full[name]) == float(again[name])))
        # per-individual grounding of an open formula equals the batched grounding
        x = ltn.Variable("x", xs.reshape(-1, 1))
        w2, _ = formulas(torch.float32)
        Pp = ltn.Predicate(func=lambda a: torch.sigmoid(a[:, 0]))
        Qq = ltn.Predicate(func=lambda a: torch.sigmoid(2 * a[:, 0] - 1))
        Imp = ltn.Connective(F.ImpliesReichenbach())
        batch = Imp(Pp(x), Qq(x)).value
        single = torch.cat([Imp(Pp(ltn.Variable("x", xs[i:i + 1].reshape(1, 1))), Qq(ltn.Variable("x", xs[i:i + 1].reshape(1, 1)))).value for i in range(n)])
        add(dim="D4", check="batch_vs_single", formula="Imp(P(x),Q(x))", ok=bool(torch.allclose(batch, single, atol=1e-6)))


def main():
    saturation()
    invariance()
    with open(OUT, "w") as f:
        for r in ROWS:
            f.write(json.dumps(r) + "\n")
    import collections
    c = collections.Counter((r["dim"], r["check"], r["ok"]) for r in ROWS)
    for k, v in sorted(c.items()):
        print(k, v)
    bad = [r for r in ROWS if not r["ok"]]
    print(len(ROWS), "checks,", len(bad), "failures ->", OUT)
    for r in bad[:12]:
        print("  ", {k: (round(v, 6) if isinstance(v, float) else v) for k, v in r.items() if k != "ok"})


if __name__ == "__main__":
    main()
