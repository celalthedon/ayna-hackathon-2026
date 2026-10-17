import importlib.util
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("citypilot_export", ROOT / "tools/export_notebooks.py")
exporter = importlib.util.module_from_spec(spec)
spec.loader.exec_module(exporter)


def cell(source, tags=("routing_export",)):
    return {"cell_type":"code", "metadata":{"tags":list(tags)}, "source":source,
            "outputs":[], "execution_count":None}


class ExportTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        (self.root / "notebooks").mkdir()
        (self.root / "src/citypilot").mkdir(parents=True)
        self.notebook = self.root / "notebooks/01_network_routing.ipynb"
        self.other = self.root / "src/citypilot/decision_engine.py"
        self.other.write_bytes(b"# Ali's existing work\n")
        self.write([cell("def ready():\n    return 1\n")])

    def write(self, cells):
        self.notebook.write_text(json.dumps({"nbformat":4,"nbformat_minor":5,"cells":cells}),encoding="utf-8")

    def test_export_deterministic_order_ignores_notebook_outputs(self):
        self.write([cell("FIRST = 1\r\n"),cell("print('analysis only')",tags=()),cell("SECOND = 2\n")])
        target = exporter.export_notebook(self.notebook,"celal",repo_root=self.root)
        initial, mtime = target.read_bytes(),target.stat().st_mtime_ns
        self.assertLess(initial.index(b"FIRST = 1"), initial.index(b"SECOND = 2"))
        self.assertNotIn(b"analysis only",initial)
        nb=json.loads(self.notebook.read_text())
        nb["cells"][0]["outputs"]=[{"anything":"changed"}]
        nb["cells"][0]["execution_count"]=99
        self.notebook.write_text(json.dumps(nb),encoding="utf-8")
        exporter.export_notebook(self.notebook,"celal",repo_root=self.root)
        self.assertEqual(target.read_bytes(),initial)
        self.assertEqual(target.stat().st_mtime_ns,mtime)
        self.assertEqual(self.other.read_bytes(),b"# Ali's existing work\n")

    def test_owner_mismatch_never_writes_either_module(self):
        before=self.other.read_bytes()
        with self.assertRaises(exporter.ExportError):
            exporter.export_notebook(self.notebook,"ali",repo_root=self.root)
        self.assertEqual(self.other.read_bytes(),before)
        self.assertFalse((self.root/"src/citypilot/routing_engine.py").exists())

    def test_explicit_ali_export_only_in_temporary_fixture(self):
        other_nb=self.root/"notebooks/02_interventions_optimization.ipynb"
        other_nb.write_text(json.dumps({"cells":[cell("def fixture_only():\n    return None",("decision_export",))]}))
        # Existing non-generated work cannot be overwritten, even with explicit owner.
        with self.assertRaises(exporter.ExportError):
            exporter.export_notebook(other_nb,"ali",repo_root=self.root)
        self.other.write_bytes(exporter.HEADER.encode()+b"# old generated fixture\n")
        routing=exporter.export_notebook(self.notebook,"celal",repo_root=self.root)
        before=routing.read_bytes()
        exporter.export_notebook(other_nb,"ali",repo_root=self.root)
        self.assertEqual(routing.read_bytes(),before)

    def test_missing_tags_and_cross_owner_tags_fail(self):
        for cells in ([cell("X=1",tags=())],[cell("X=1",tags=("routing_export","decision_export"))]):
            self.write(cells)
            with self.assertRaises(exporter.ExportError):
                exporter.export_notebook(self.notebook,"celal",repo_root=self.root)

    def test_import_time_side_effects_and_magics_rejected(self):
        for code in ("print('bad')", "%matplotlib inline", "MODEL = load_model()",
                     "@run()\ndef f():\n    pass", "def f(x=download()):\n    pass",
                     "import requests", "if True:\n    open('x','w')", "TARGET.attr = 1"):
            with self.subTest(code=code):
                self.write([cell(code)])
                with self.assertRaises(exporter.ExportError):
                    exporter.export_notebook(self.notebook,"celal",repo_root=self.root)

    def test_check_is_readonly_and_refuses_stale_output(self):
        target=exporter.export_notebook(self.notebook,"celal",repo_root=self.root)
        before=target.read_bytes()
        exporter.export_notebook(self.notebook,"celal",repo_root=self.root,check=True)
        self.write([cell("CHANGED = 1")])
        with self.assertRaises(exporter.ExportError):
            exporter.export_notebook(self.notebook,"celal",repo_root=self.root,check=True)
        self.assertEqual(target.read_bytes(),before)

    def test_checked_in_module_parity_and_cli_requires_explicit_selection(self):
        exporter.export_notebook(Path("notebooks/01_network_routing.ipynb"),"celal",check=True)
        proc=subprocess.run([sys.executable,str(ROOT/"tools/export_notebooks.py")],capture_output=True,text=True)
        self.assertNotEqual(proc.returncode,0)
        self.assertIn("--owner",proc.stderr)
        self.assertIn("--notebook",proc.stderr)

    def test_export_cells_clean_execution_and_module_signature_parity(self):
        script=f'''
import codeop, json, sys
from pathlib import Path
root=Path({str(ROOT)!r})
document=json.loads((root/'notebooks/01_network_routing.ipynb').read_text(encoding='utf-8'))
sys.path.insert(0,str(root/'src'))
scope={{'__name__':'__main__'}}
compiler=codeop.Compile()
for cell in document['cells']:
    if cell['cell_type']=='code' and 'routing_export' in cell.get('metadata',{{}}).get('tags',[]):
        exec(compiler(''.join(cell['source']),'<notebook>','exec'),scope)
from citypilot import routing_engine
for name in ('load_model','get_catalog','evaluate_package','inspect_journey'):
    assert str(__import__('inspect').signature(scope[name])) == str(__import__('inspect').signature(getattr(routing_engine,name)))
print('clean tagged export execution OK; no analysis/server cells run')
'''
        proc=subprocess.run([sys.executable,"-I","-c",script],cwd=ROOT/"notebooks",text=True,capture_output=True)
        self.assertEqual(proc.returncode,0,proc.stderr)
        self.assertIn("clean tagged export execution OK",proc.stdout)


if __name__ == "__main__":
    unittest.main()
