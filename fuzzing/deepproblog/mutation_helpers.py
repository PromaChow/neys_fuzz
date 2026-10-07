
import re

BOUNDARY = [0.0, 1.0, 1e-9, 1.0 - 1e-9, 1e-5, 1.0001e-5, 0.99999, 0.5]
BUILTINS = {"between", "list_to_tensor", "tensor_index", "less_than", "evaluate", "ith_word", "t", "nn",
            "query", "findall", "member", "append", "length", "is", "not", "true", "fail", "call"}
PROB_RE = re.compile(r"(?P<t>t\()?(?P<num>\d+\.\d+(?:e[-+]?\d+)?|\d+e[-+]?\d+|\d+)(?(t)\))\s*::")


def statements(text):
    out, cur = [], []
    for line in text.splitlines():
        s = line.split("%")[0].rstrip()
        if not s.strip():
            continue
        cur.append(s)
        if s.endswith("."):
            out.append("\n".join(cur))
            cur = []
    if cur:
        out.append("\n".join(cur))
    return out



def join(stmts):
    return "\n".join(stmts) + "\n"


def fmt(p):
    return repr(float(p))


def mutate_prob(stmts, rng):
    cands = [(i, m) for i, s in enumerate(stmts) for m in PROB_RE.finditer(s)]
    if not cands:
        return None
    i, m = rng.choice(cands)
    old = float(m.group("num"))
    kind = rng.choice(["boundary", "boundary", "perturb", "complement"])
    if kind == "boundary":
        new = rng.choice(BOUNDARY)
    elif kind == "perturb":
        new = min(max(old + rng.choice([-1, 1]) * rng.choice([1e-9, 1e-6, 1e-3, 0.1]), 0.0), 1.0)
    else:
        new = 1.0 - old
    s = stmts[i]
    matches = list(PROB_RE.finditer(s))
    repaired = ""
    pieces, last = [], 0
    others = [x for x in matches if x.span() != m.span()]
    if ";" in s and others:                    
        rest_old = sum(float(x.group("num")) for x in others)
        budget = max(1.0 - new, 0.0)
        scale = (budget / rest_old) if rest_old > 0 else 0.0
        if rest_old > budget:                  
            repaired = f" (rescaled {len(others)} sibling alternative(s) by {scale:.6g})"
        else:
            scale = 1.0
    else:
        scale = 1.0
    for x in matches:
        pieces.append(s[last:x.start("num")])
        if x.span() == m.span():
            pieces.append(fmt(new))
        else:
            pieces.append(fmt(float(x.group("num")) * scale) if scale != 1.0 else x.group("num"))
        last = x.end("num")
    pieces.append(s[last:])
    out = list(stmts)
    out[i] = "".join(pieces)
    return out, f"probability {old!r} -> {new!r} ({kind}){repaired}"


def clause_heads(stmts):
    names = set()
    for s in stmts:
        head = s.split(":-")[0]
        for m in re.finditer(r"(?<![A-Za-z0-9_])([a-z][A-Za-z0-9_]*)", head.split("::")[-1]):
            names.add(m.group(1))
    return names - BUILTINS


