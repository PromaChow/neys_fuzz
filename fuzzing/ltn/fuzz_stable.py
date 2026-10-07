"""Fuzz LTNtorch's own tests: flip the stable flag of each fuzzy operator for the call (answers must stay within the documented projection)

Usage: python fuzzing/ltn/fuzz_stable.py [--seeds N] [--python PATH]
Output: fuzzing/ltn/result/fuzz_stable.json (summary + findings), fuzz_stable_raw.jsonl (every run)
"""
from fuzz_common import main

if __name__ == "__main__":
    main("stable", "flip the stable flag of each fuzzy operator for the call (answers must stay within the documented projection)")
