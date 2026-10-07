"""Fuzz DeepProbLog's own tests: change one probability in each test's program (boundary 0/1/1e-9/0.99999, small perturbation, complement)

Usage: python fuzzing/deepproblog/fuzz_probability.py [--seeds N] [--python PATH]
Output: fuzzing/deepproblog/result/fuzz_probability.json (summary + findings), fuzz_probability_raw.jsonl (every run)
"""
from fuzz_common import main

if __name__ == "__main__":
    main("probability", "change one probability in each test's program (boundary 0/1/1e-9/0.99999, small perturbation, complement)")
