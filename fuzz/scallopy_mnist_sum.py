"""Scallop's flagship pattern: two categorical digit distributions -> distribution over their sum, via forward_function.
Exact answer: P(sum=s) = sum_{a+b=s} p1[a] * p2[b]  (two independent categorical variables)."""
import collections, itertools, sys, warnings
warnings.filterwarnings("ignore")
import numpy as np, torch, scallopy

PROVS = ["difftopkproofs", "diffminmaxprob", "diffaddmultprob", "diffnandmultprob", "diffmaxmultprob", "difftopbottomkclauses"]

def exact(p1, p2):
    out = np.zeros((p1.shape[0], 19))
    for a, b in itertools.product(range(10), repeat=2):
        out[:, a + b] += p1[:, a].numpy().astype(np.float64) * p2[:, b].numpy().astype(np.float64)
    return out

def make(prov, dispatch, k=10):
    ctx = scallopy.ScallopContext(provenance=prov, k=k)
    ctx.add_relation("digit_1", int, range(10)); ctx.add_relation("digit_2", int, range(10))
    ctx.add_rule("sum_2(a + b) = digit_1(a) and digit_2(b)")
    return ctx.forward_function("sum_2", list(range(19)), dispatch=dispatch)

def softmax_rows(rng, n, scale):
    return torch.softmax(torch.tensor(rng.normal(size=(n, 10)) * scale, dtype=torch.float32), dim=1)

def run(f, p1, p2):
    return f(digit_1=p1, digit_2=p2).detach().numpy().astype(np.float64)

rng = np.random.default_rng(0)
print(f"{'provenance':22s} {'dispatch':9s} | exact-sum error (random rows) | batch-vs-single diff | saturated rows (one-hot) error")
for prov in PROVS:
    for dispatch in ("serial", "single"):
        try:
            f = make(prov, dispatch)
            p1, p2 = softmax_rows(rng, 8, 1.0), softmax_rows(rng, 8, 1.0)
            batch = run(f, p1, p2)
            err_exact = np.abs(batch - exact(p1, p2)).max()
            singles = np.vstack([run(make(prov, dispatch), p1[i:i+1], p2[i:i+1]) for i in range(8)])
            err_batch = np.abs(batch - singles).max()
            oh1 = torch.zeros(4, 10); oh2 = torch.zeros(4, 10)
            for i in range(4): oh1[i, rng.integers(10)] = 1.0; oh2[i, rng.integers(10)] = 1.0
            err_sat = np.abs(run(make(prov, dispatch), oh1, oh2) - exact(oh1, oh2)).max()
            print(f"{prov:22s} {dispatch:9s} | {err_exact:10.2e}                  | {err_batch:10.2e}           | {err_sat:10.2e}")
        except BaseException as e:
            if isinstance(e, KeyboardInterrupt): raise
            print(f"{prov:22s} {dispatch:9s} | ERROR {type(e).__name__}: {str(e)[:70]}")
