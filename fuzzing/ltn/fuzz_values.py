"""Fuzz LTNtorch's own tests: change the truth values given to each fuzzy operator (boundary 0/1/1e-9/1-1e-9/eps, small perturbation, complement)

Usage: python fuzzing/ltn/fuzz_values.py [--seeds N] [--python PATH]
Output: fuzzing/ltn/result/fuzz_values.json (summary + findings), fuzz_values_raw.jsonl (every run)
"""
from fuzz_common import main

if __name__ == "__main__":
    main("values", "change the truth values given to each fuzzy operator (boundary 0/1/1e-9/1-1e-9/eps, small perturbation, complement)")
