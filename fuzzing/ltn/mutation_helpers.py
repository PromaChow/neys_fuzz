"""Value helpers used by ltn_mutation_plugin.py.

Truth-value counterpart of fuzzing/deepproblog/mutation_helpers.py: change the numbers a test hands to a fuzzy
operator. The special values come from fuzz/ltn_mutate.py (0, 1, and values around the library's own
projection threshold eps = 1e-4 in ltn/fuzzy_ops.py).
"""
import numpy as np

SPECIAL = [0.0, 1.0, 1e-9, 1 - 1e-9, 1e-5, 1e-4, 1.01e-4, 1 - 1e-4, 0.5]


def mutate_values(arr, rng, kind):
    """Return a copy of `arr` (float64) with some truth values replaced; every value stays in [0, 1].

    boundary    a third of the values (at least one) are replaced by one of SPECIAL
    perturb     every value moves by +-1e-9, 1e-6, 1e-3 or 0.1, clipped to [0, 1]
    complement  x -> 1 - x
    """
    a = np.array(arr, dtype=np.float64)
    flat = a.reshape(-1)
    if kind == "boundary":
        for i in rng.sample(range(flat.size), max(1, flat.size // 3)):
            flat[i] = rng.choice(SPECIAL)
    elif kind == "perturb":
        for i in range(flat.size):
            flat[i] = min(max(flat[i] + rng.choice([-1, 1]) * rng.choice([1e-9, 1e-6, 1e-3, 0.1]), 0.0), 1.0)
    elif kind == "complement":
        flat[:] = 1.0 - flat
    return a


def short(arr, n=8):
    """First n values of a tensor / array as plain floats, for the result records."""
    flat = np.asarray(arr, dtype=np.float64).reshape(-1)
    return {"n": int(flat.size), "first": [round(float(x), 9) for x in flat[:n]]}
