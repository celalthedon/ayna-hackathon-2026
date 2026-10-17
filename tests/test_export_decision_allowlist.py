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


CONTRACT_CLASSES = ("EvaluationResult", "Link", "ModelCatalog", "ODResult", "Parking", "RoutingPatch",
                    "RoutingRequest", "ServiceGroup")


def test_no_temporary_stub_classes_remain():
    assert not hasattr(ex, "DECISION_TEMPORARY_STUB_CLASSES")


@pytest.mark.parametrize("name", CONTRACT_CLASSES)
def test_decision_cannot_redefine_contract_classes(name):
    assert name not in ex.DECISION_CLASSES
    with pytest.raises(ex.ExportError, match="contracts.py"):
        ex._safe_decision_module(f"class {name}:\n    pass")


def test_decision_allowlist_is_pinned():
    assert len(ex.DECISION_CLASSES) == 20
    assert ex.DECISION_EXTRA_IMPORTS == {"csv", "itertools", "datetime", "yaml"}
    assert ex.DECISION_NONLITERAL_DEFAULT_FUNCTIONS == {"count_lost", "gate_objective"}


@pytest.mark.parametrize("source", [
    "from dataclasses import dataclass\n@dataclass(frozen=True)\nclass Scenario:\n    x: int",
    "from citypilot.contracts import ServiceGroup",
    "import csv\nimport itertools\nimport yaml\nfrom datetime import datetime, timezone",
    "GATE_THRESHOLDS_MIN = (40, 45, 50)\ndef count_lost(a, b, t=GATE_THRESHOLDS_MIN):\n    return a",
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


# Malicious examples are parsed/rejected only: never exec/import these snippets.
@pytest.mark.parametrize("member", [
    "print('side effect')", "x = print('side effect')", "x = 1",
    "if True: print('side effect')", "import os", "class Nested: pass",
    "x: int = print('side effect')", "x: int = factory()",
    "x: run()", "x: list[run()]", "x: int | run()", "x: 'run()'",
    "x: int = frozenset()", "x: int = frozenset([1])",
    "@run()\ndef method(self): pass",
    "@property()\ndef method(self): pass",
    "def method(self, x=run()): pass",
    "def method(self, *, x=run()): pass",
    "def method(self, x: run()): pass",
    "def method(self, *args: run()): pass",
    "def method(self, **kwargs: run()): pass",
    "def method(self) -> run(): pass",
    "async def method(self, x=run()): pass",
    "def count_lost(self, t=GATE_THRESHOLDS_MIN): pass",
])
def test_class_members_cannot_bypass_import_safety(member):
    source = "class Scenario:\n" + "\n".join("    " + line for line in member.splitlines())
    with pytest.raises(ex.ExportError):
        ex._safe_decision_module(source)


@pytest.mark.parametrize("prefix", [
    "@run()\nclass Scenario:",
    "@dataclass(frozen=run())\nclass Scenario:",
    "@dataclass(run())\nclass Scenario:",
    "@dataclass(**options)\nclass Scenario:",
    "@dataclass(order=True)\nclass Scenario:",
    "@dataclass(frozen=1)\nclass Scenario:",
    "@other.dataclass(frozen=True)\nclass Scenario:",
    "class Scenario(run()):", "class Scenario(module.ValueError):",
    "class Scenario(ValueError[int]):", "class Scenario(Unknown):",
    "class Scenario(metaclass=run()):",
])
def test_class_decorators_and_bases_are_explicit(prefix):
    with pytest.raises(ex.ExportError):
        ex._safe_decision_module(prefix + "\n    x: int")


@pytest.mark.parametrize("function", ["count_lost", "gate_objective"])
@pytest.mark.parametrize("default", [
    "run()", "OTHER", "GATE_THRESHOLDS_MIN + (60,)",
    "GATE_THRESHOLDS_MIN[0]", "module.GATE_THRESHOLDS_MIN",
    "(x for x in ())", "lambda: 1",
])
def test_special_defaults_reject_calls_and_computed_expressions(function, default):
    source = "GATE_THRESHOLDS_MIN = (40, 45, 50)\ndef " + function + "(t=" + default + "): pass"
    with pytest.raises(ex.ExportError):
        ex._safe_decision_module(source)


@pytest.mark.parametrize("source", [
    "def count_lost(t=GATE_THRESHOLDS_MIN): pass",
    "GATE_THRESHOLDS_MIN = run()\ndef count_lost(t=GATE_THRESHOLDS_MIN): pass",
    "GATE_THRESHOLDS_MIN = (40,)\ndef GATE_THRESHOLDS_MIN(): pass\ndef count_lost(t=GATE_THRESHOLDS_MIN): pass",
    "x: run() = 1", "def other(x: run()): pass",
    "def other() -> run(): pass",
    "def dataclass(): pass", "frozenset = 1", "ValueError = 1",
    "def set(): pass",
    "from csv import reader as dataclass",
    "class DecisionProblem:\n    requires_bike: frozenset[str] = frozenset(run())",
    "class DecisionProblem:\n    requires_bike: frozenset[str] = frozenset(extra=True)",
    "class DecisionProblem:\n    frozenset: int = 1\n    requires_bike: frozenset[str] = frozenset()",
])
def test_module_constants_annotations_and_approved_names_are_validated(source):
    with pytest.raises(ex.ExportError):
        ex._safe_decision_module(source)


@pytest.mark.parametrize("source", [
    "from dataclasses import dataclass\n@dataclass\nclass Scenario:\n    x: int = 1",
    "from dataclasses import dataclass\n@dataclass()\nclass Scenario:\n    x: int = 1",
    "from dataclasses import dataclass\n@dataclass(frozen=True)\nclass Scenario:\n    x: Mapping[str, tuple[int, ...]] | None = None",
    "class ObjectiveModelMismatch(ValueError):\n    'Domain exception'",
    "class StressFactorsNotSupported(NotImplementedError):\n    'Unsupported capability'",
    "class Scenario:\n    'docstring'\n    x: list['Scenario'] | None = None\n    def method(self, x: int = 1, *, flag: bool = False) -> str: return str(x)",
    "class PackageOutcome:\n    @property\n    def count(self) -> int: return 1",
    "class DecisionProblem:\n    requires_bike: frozenset[str] = frozenset()",
    "def count_lost(t=(40, 45), *, x=None): pass",
    "def gate_objective(t=45, *, x=True): pass",
    "GATE_THRESHOLDS_MIN = (40, 45, 50)\ndef count_lost(t=GATE_THRESHOLDS_MIN): pass\ndef gate_objective(*, t=GATE_THRESHOLDS_MIN): pass",
])
def test_required_decision_forms_remain_valid(source):
    ex._safe_decision_module(source)


def test_both_owners_render_deterministically_without_executing_analysis():
    import json
    from unittest.mock import patch
    for owner, (notebook, tag, output) in ex.OWNERS.items():
        document = json.loads((ROOT / notebook).read_text(encoding="utf-8"))
        # This untagged sentinel must never be parsed as exported source or run.
        document["cells"].append({"cell_type": "code", "metadata": {},
                                  "source": "raise RuntimeError('analysis executed')"})
        with patch.object(Path, "read_text", return_value=json.dumps(document)):
            destination, first = ex.render(Path(notebook), owner)
            _, second = ex.render(Path(notebook), owner)
        assert first == second == destination.read_bytes()
        assert b"analysis executed" not in first


def test_clean_process_imports_without_notebook_execution():
    import subprocess
    script = ("import sys; sys.path.insert(0, " + repr(str(ROOT / "src")) + "); "
              "import citypilot.contracts, citypilot.decision_engine, citypilot.routing_engine; "
              "print('clean imports OK')")
    result = subprocess.run([sys.executable, "-I", "-B", "-c", script],
                            cwd=ROOT / "notebooks", capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
    assert "clean imports OK" in result.stdout


def test_only_actual_special_constant_and_exception_bases_are_approved():
    assert ex.DECISION_DEFAULT_CONSTANTS == {
        "count_lost": {"GATE_THRESHOLDS_MIN"},
        "gate_objective": {"GATE_THRESHOLDS_MIN"},
    }
    assert set(ex.DECISION_DEFAULT_CONSTANTS) == ex.DECISION_NONLITERAL_DEFAULT_FUNCTIONS
    assert ex.DECISION_BASE_CLASSES == {"ValueError", "NotImplementedError"}
