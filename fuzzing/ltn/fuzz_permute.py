"""Fuzz LTNtorch's own tests: shuffle the elements given to each fuzzy operator and shuffle the result back (answers must not change)

Usage: python fuzzing/ltn/fuzz_permute.py [--seeds N] [--python PATH]
Output: fuzzing/ltn/result/fuzz_permute.json (summary + findings), fuzz_permute_raw.jsonl (every run)
"""
from fuzz_common import main

if __name__ == "__main__":
    main("permute", "shuffle the elements given to each fuzzy operator and shuffle the result back (answers must not change)")
