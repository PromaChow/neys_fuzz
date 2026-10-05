"""Translators and runners: one function per system, each returning {rel: {tuple: probability}} for a Prog
(or {sum: probability} for a NeuralCase). Existing, already-validated translators from ../fuzz are reused."""
import os
import sys
import warnings

warnings.filterwarnings("ignore")
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "fuzz"))
sys.path.insert(0, os.path.join(HERE, "..", "frameworks", "NeurASP"))

K_BIG = 300
# per-system tolerance on |value - oracle| (+ 1e-5 relative): float64 engines vs float32 tensors
TOL = {"scallop_topk": 1e-9, "scallop_wmcdisj": 1e-9, "problog": 1e-9, "dpl_exact": 1e-5, "dpl_approx": 1e-5,
       "neurasp": 1e-5, "scallop_nn": 1e-5, "dpl_exact_nn": 1e-5, "dpl_approx_nn": 1e-5}

SYMBOLIC = ["scallop_topk", "scallop_wmcdisj", "problog", "dpl_exact", "dpl_approx", "neurasp"]
NEURAL = ["scallop_nn", "dpl_exact_nn", "dpl_approx_nn"]


def run_symbolic(system, prog):
    if system == "scallop_topk":
        from scallop_fuzz import scallop_probs
        return scallop_probs(prog, "topkproofs", K_BIG)
    if system == "scallop_wmcdisj":
        if not prog.groups:
            return None                                           # flag only matters with disjunctions
        from scallop_fuzz import scallop_probs
        return scallop_probs(prog, "topkproofs", K_BIG, wmc_disj=True)
    if system == "problog":
        return _problog(prog)
    if system == "dpl_exact":
        from deepproblog_fuzz import values_and_grads
        return values_and_grads(prog, "exact", want_grads=False)[0]
    if system == "dpl_approx":
        if prog.is_cyclic():
            return None                                           # left-recursive SLD loops (REPORT.md sec. 5)
        from deepproblog_fuzz import values_and_grads
        return values_and_grads(prog, "approx", k=200, want_grads=False)[0]
    if system == "neurasp":
        from neurasp_fuzz import inference
        return inference(prog, False)[2]
    raise ValueError(system)


def _problog(prog):
    from problog.program import PrologString
    from problog import get_evaluatable
    from problog.logic import Term
    from deepproblog_fuzz import program_text
    text = program_text(prog, False)
    queries = [(rel, t) for rel in prog.idb for t in prog.possible_tuples(rel)]
    text += "".join(f"query({rel}({','.join(map(str, t))})).\n" for rel, t in queries)
    res = get_evaluatable().create_from(PrologString(text)).evaluate()
    got = {str(k): float(v) for k, v in res.items()}
    out = {rel: {} for rel in prog.idb}
    for rel, t in queries:
        out[rel][t] = got.get(f"{rel}({','.join(map(str, t))})", 0.0)
    return out


# ---------------------------------------------------------------- neural template: sum of categorical variables
def run_neural(system, case):
    import numpy as np
    import torch
    P = torch.tensor(case.probs, dtype=torch.float32)
    n, k = case.n, len(case.probs)
    if system == "scallop_nn":
        import scallopy
        ctx = scallopy.ScallopContext(provenance="difftopkproofs", k=10)
        for i in range(k):
            ctx.add_relation(f"digit_{i}", int, range(n))
        ctx.add_rule("total(" + " + ".join(f"a{i}" for i in range(k)) + ") = " + " and ".join(f"digit_{i}(a{i})" for i in range(k)))
        f = ctx.forward_function("total", list(range(k * (n - 1) + 1)), dispatch="serial")
        out = f(**{f"digit_{i}": P[i:i + 1] for i in range(k)}).detach().numpy()[0]
        return {s: float(v) for s, v in enumerate(out)}
    if system in ("dpl_exact_nn", "dpl_approx_nn"):
        from deepproblog.engines import ExactEngine, ApproximateEngine
        from deepproblog.model import Model
        from deepproblog.network import Network
        from deepproblog.query import Query
        from problog.logic import Term, Constant

        class Net(torch.nn.Module):
            def forward(self, x):
                return P[int(x.flatten()[0])]

        class Src:
            def __getitem__(self, i):
                i = i[0] if isinstance(i, tuple) else i
                return torch.tensor([float(i)])

        vs = [f"A{i}" for i in range(k)]
        prog = (f"nn(net,[X],Y,[{','.join(map(str, range(n)))}]) :: digit(X,Y).\n"
                f"total({','.join(f'X{i}' for i in range(k))},Z) :- "
                + ", ".join(f"digit(X{i},A{i})" for i in range(k)) + f", Z is {' + '.join(vs)}.\n")
        m = Model(prog, [Network(Net(), "net")], load=False)
        m.add_tensor_source("t", Src())
        m.set_engine(ExactEngine(m) if system == "dpl_exact_nn" else ApproximateEngine(m, 200, ApproximateEngine.geometric_mean))
        out = {}
        for s in range(k * (n - 1) + 1):
            args = [Term("tensor", Term("t", Constant(i))) for i in range(k)]
            q = Term("total", *args, Constant(s))
            r = m.solve([Query(q)])[0].result
            out[s] = float(r[q]) if q in r else 0.0
        return out
    raise ValueError(system)


def oracle_neural(case):
    """Exact distribution of the sum of independent categorical variables, on the float32-rounded inputs."""
    import numpy as np
    rows = [np.asarray(np.asarray(p, dtype=np.float32), dtype=np.float64) for p in case.probs]
    dist = np.array([1.0])
    for r in rows:
        dist = np.convolve(dist, r)
    return {s: float(v) for s, v in enumerate(dist)}
