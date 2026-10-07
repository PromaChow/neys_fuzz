"""Fuzz DeepProbLog's own tests: append a duplicate of one rule to each test's program (answers must not change)

Usage: python fuzzing/deepproblog/fuzz_duplicate_rule.py [--seeds N] [--python PATH]
Output: fuzzing/deepproblog/result/fuzz_duplicate_rule.json (summary + findings), fuzz_duplicate_rule_raw.jsonl (every run)
"""
from fuzz_common import main

if __name__ == "__main__":
    main("duplicate_rule", "append a duplicate of one rule to each test's program (answers must not change)")
