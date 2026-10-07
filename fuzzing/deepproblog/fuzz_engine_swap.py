"""Fuzz DeepProbLog's own tests: swap ExactEngine <-> ApproximateEngine(k=100) under each test (answers must not change)

Usage: python fuzzing/deepproblog/fuzz_engine_swap.py [--seeds N] [--python PATH]
Output: fuzzing/deepproblog/result/fuzz_engine_swap.json (summary + findings), fuzz_engine_swap_raw.jsonl (every run)
"""
from fuzz_common import main

if __name__ == "__main__":
    main("engine_swap", "swap ExactEngine <-> ApproximateEngine(k=100) under each test (answers must not change)")
