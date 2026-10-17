"""Decision (owner "ali") export allowlist. Owner "celal" rules must stay unchanged."""
import ast
import hashlib
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))

import export_notebooks as ex  # noqa: E402

# sha256 of the _safe_module source on main before the decision allowlist was added
SAFE_MODULE_SHA256 = "2237a9d553489189e1401c2d64f81517fc9bd6f54df09f9e3a52ec04dc20c17f"


def test_shared_rules_are_byte_for_byte_unchanged():
    src = (ROOT / "tools" / "export_notebooks.py").read_text()
    fn = next(n for n in ast.parse(src).body if isinstance(n, ast.FunctionDef) and n.name == "_safe_module")
    assert hashlib.sha256(ast.get_source_segment(src, fn).encode()).hexdigest() == SAFE_MODULE_SHA256


def test_temporary_stub_classes_are_pinned():
    # removed by the decision migration PR; this list must only shrink
    assert ex.DECISION_TEMPORARY_STUB_CLASSES == {
        "EvaluationResult", "Link", "ModelCatalog", "ODResult", "Parking", "RoutingPatch", "RoutingRequest",
        "ServiceGroup",
    }


def test_decision_allowlist_is_pinned():
    assert len(ex.DECISION_CLASSES) == 20
    assert not ex.DECISION_CLASSES & ex.DECISION_TEMPORARY_STUB_CLASSES
    assert ex.DECISION_EXTRA_IMPORTS == {"csv", "itertools", "datetime", "yaml"}
    assert ex.DECISION_NONLITERAL_DEFAULT_FUNCTIONS == {"count_lost", "gate_objective"}


@pytest.mark.parametrize("source", [
    "from dataclasses import dataclass\n@dataclass(frozen=True)\nclass Scenario:\n    x: int",
    "class ServiceGroup:\n    pass",  # temporary stub
    "import csv\nimport itertools\nimport yaml\nfrom datetime import datetime, timezone",
    "G = (40, 45, 50)\ndef count_lost(a, b, t=G):\n    return a",
])
def test_decision_accepts_allowlisted(source):
    ex._safe_decision_module(source)


@pytest.mark.parametrize("source", [
    "class Foo:\n    pass",                          # class not on the list
    "import os",                                     # import not on the list
    "import csv, os",                                # mixed import
    "G = (1,)\ndef other(t=G):\n    return t",       # executable default outside the two functions
    "def deco(f):\n    return f\n@deco\ndef count_lost(a):\n    return a",  # decorator still rejected
    "print('side effect')",                          # top-level work
])
def test_decision_rejects_everything_else(source):
    with pytest.raises(ex.ExportError):
        ex._safe_decision_module(source)


@pytest.mark.parametrize("source", [
    "class Scenario:\n    pass",
    "class ServiceGroup:\n    pass",
    "import csv",
    "G = (1,)\ndef count_lost(t=G):\n    return t",
])
def test_routing_owner_keeps_rejecting(source):
    with pytest.raises(ex.ExportError):
        ex._safe_module(source)


@pytest.mark.parametrize("owner", ["ali", "celal"])
def test_generated_modules_are_current(owner):
    notebook = Path(ex.OWNERS[owner][0])
    assert ex.export_notebook(notebook, owner, check=True) == ROOT / ex.OWNERS[owner][2]
