"""Fuzz LTNtorch's own tests: run each fuzzy operator in float64 and cast the result back (answers must not change)

Usage: python fuzzing/ltn/fuzz_float64.py [--seeds N] [--python PATH]
Output: fuzzing/ltn/result/fuzz_float64.json (summary + findings), fuzz_float64_raw.jsonl (every run)
"""
from fuzz_common import main

if __name__ == "__main__":
    main("float64", "run each fuzzy operator in float64 and cast the result back")
