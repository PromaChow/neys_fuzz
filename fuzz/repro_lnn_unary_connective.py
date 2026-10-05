"""LNN: And(A), Or(A), XOr(A) (a single operand) are accepted by add_knowledge()/add_data() and crash in infer()."""
import logging
import os
import sys
import traceback
import warnings
logging.disable(logging.CRITICAL)
warnings.filterwarnings("ignore")
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "frameworks", "LNN"))
from lnn import Model, Proposition, And, Or, XOr, Fact

for name, ctor in (("And", And), ("Or", Or), ("XOr", XOr)):
    A = Proposition("A")
    f = ctor(A)
    m = Model()
    m.add_knowledge(f)
    m.add_data({A: Fact.TRUE})
    try:
        m.infer()
        print(f"{name}(A): infer ok, bounds {f.get_data().tolist()}")
    except Exception as e:
        t = traceback.extract_tb(e.__traceback__)[-1]
        print(f"{name}(A): construction, add_knowledge and add_data succeed; infer() raises {type(e).__name__}: {e}  [{os.path.basename(t.filename)}:{t.lineno}]")
