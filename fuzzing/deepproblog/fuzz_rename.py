"""Fuzz DeepProbLog's own tests: consistently rename one predicate in the program and in the queries (answers must not change)

Usage: python fuzzing/deepproblog/fuzz_rename.py [--seeds N] [--python PATH]
Output: fuzzing/deepproblog/result/fuzz_rename.json (summary + findings), fuzz_rename_raw.jsonl (every run)
"""
from fuzz_common import main

if __name__ == "__main__":
    main("rename", "consistently rename one predicate in the program and in the queries (answers must not change)")
