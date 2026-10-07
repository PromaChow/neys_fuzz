
import json
import os
import pytest

OUT = os.environ.get("NESY_SEED_OUT") or os.path.join(os.path.dirname(__file__), "..", "results", "seeds", "deepproblog_seeds.json")
RECORDS = []
CURRENT = {"test": None}


def _install():
    from deepproblog.model import Model
    orig_init, orig_set_engine, orig_solve = Model.__init__, Model.set_engine, Model.solve

    def init(self, program_string, networks, embeddings=None, load=True):
        text = program_string
        if load:
            try:
                text = open(str(program_string)).read()
            except Exception:
                text = None
        self._trace = {"test": CURRENT["test"], "program": text, "loaded_from_file": bool(load),
                       "networks": [getattr(n, "name", str(n)) for n in networks],
                       "engine": None, "queries": []}
        RECORDS.append(self._trace)
        return orig_init(self, program_string, networks, embeddings, load)

    def set_engine(self, engine, **kw):
        t = getattr(self, "_trace", None)
        if t is not None:
            h = getattr(engine, "heuristic", None)
            t["engine"] = {"cls": type(engine).__name__, "k": getattr(engine, "k", None),
                           "heuristic": getattr(h, "name", None) if h is not None else None,
                           "kwargs": {k: repr(v) for k, v in kw.items()}}
        return orig_set_engine(self, engine, **kw)

    def solve(self, batch):
        t = getattr(self, "_trace", None)
        if t is not None:
            for q in batch:
                s = str(q.query)
                if s not in t["queries"]:
                    t["queries"].append(s)
        return orig_solve(self, batch)

    Model.__init__, Model.set_engine, Model.solve = init, set_engine, solve


def pytest_configure(config):
    _install()


@pytest.hookimpl(hookwrapper=True)
def pytest_runtest_setup(item):
    CURRENT["test"] = item.nodeid
    yield


@pytest.hookimpl(hookwrapper=True)
def pytest_runtest_call(item):
    CURRENT["test"] = item.nodeid
    yield


def pytest_sessionfinish(session, exitstatus):
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    seen, out = set(), []
    for r in RECORDS:
        key = (r["test"], r["program"], json.dumps(r["engine"], sort_keys=True), tuple(r["queries"]))
        if key not in seen:
            seen.add(key)
            out.append(r)
    json.dump(out, open(OUT, "w"), indent=1)
