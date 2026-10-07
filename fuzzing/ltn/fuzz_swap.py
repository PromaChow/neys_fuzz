"""Fuzz LTNtorch's own tests: swap the two operands of each commutative binary connective (answers must not change)

Usage: python fuzzing/ltn/fuzz_swap.py [--seeds N] [--python PATH]
Output: fuzzing/ltn/result/fuzz_swap.json (summary + findings), fuzz_swap_raw.jsonl (every run)
"""
from fuzz_common import main

if __name__ == "__main__":
    main("swap", "swap the two operands of each commutative binary connective (answers must not change)")
