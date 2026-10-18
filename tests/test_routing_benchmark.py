"""Fast benchmark machinery checks; never load a real graph or spawn routing jobs."""
import contextlib
import hashlib
import importlib.util
import io
import json
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch,MagicMock

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'src'))
spec=importlib.util.spec_from_file_location('routing_benchmark',ROOT/'tools/benchmark_routing.py')
bench=importlib.util.module_from_spec(spec);sys.modules[spec.name]=bench;spec.loader.exec_module(bench)
from citypilot import routing_engine as engine
from citypilot.contracts import RoutingRequest


class BenchmarkTests(unittest.TestCase):
    def test_required_memory_monitor_dependency_is_pinned(self):
        from importlib.metadata import version
        import psutil
        # The CLI/monitor require this import without an optional fallback.
        # An already populated notebook environment must not hide an omitted pin.
        self.assertEqual(psutil.__version__,version('psutil'))
        self.assertIn('psutil=='+version('psutil'),
                      (ROOT/'requirements.txt').read_text(encoding='utf-8').splitlines())

    def test_timing_probe_anchors_and_functions_restore_without_source_edits(self):
        path=ROOT/'src/citypilot/routing_engine.py';before=hashlib.sha256(path.read_bytes()).hexdigest()
        originals={name:getattr(engine,name) for name in ('_scenario','_solve','_raw_arcs','_service_stress_arcs','_activate_services')}
        with bench.StageProfiler(engine) as profiler:
            self.assertIsNot(engine._scenario,originals['_scenario'])
            with profiler.region('independent_test'):sum(range(100))
            self.assertGreater(profiler.times['independent_test'],0)
        for name,value in originals.items():self.assertIs(getattr(engine,name),value)
        self.assertNotIn('_benchmark_region',engine.__dict__)
        self.assertEqual(before,hashlib.sha256(path.read_bytes()).hexdigest())

    def test_workload_is_bounded_deterministic_distinct_and_has_both_profiles(self):
        model={'manifest':{'artifact_version':'tiny','bundle_hash':'1'*64},'od':{'od_version':'fixed','od_hash':'2'*64},'closure_id':'closure:test'}
        stub=SimpleNamespace(baseline_request=engine.baseline_request,get_catalog=lambda _:MagicMock())
        a=bench.workload(stub,model);b=bench.workload(stub,model)
        self.assertEqual(a,b);self.assertEqual(len(a),8)
        requests=[RoutingRequest.from_json(r['request']) for r in a]
        self.assertEqual(len({r.config_hash for r in requests}),8)
        self.assertEqual({p:sum(r.profile==p for r in requests) for p in ('P','B')},{'P':4,'B':4})
        for request in requests:
            self.assertEqual(request.closure_id,'closure:test')
            self.assertEqual(request.state,'mitigated' if request.patches else 'disrupted')

    def test_full_payload_signature_ignores_only_runtime(self):
        a={'duration_ms':1.,'config_hash':'1'*64,'od_results':[{'minutes':3.,'status':'reachable'}]}
        b=dict(a,duration_ms=1000.)
        self.assertEqual(bench.signature(json.dumps(a)),bench.signature(json.dumps(b)))
        b['od_results']=[{'minutes':4.,'status':'reachable'}]
        self.assertNotEqual(bench.signature(json.dumps(a)),bench.signature(json.dumps(b)))

    def test_parallel_mismatch_and_duplicate_result_rejected(self):
        items=[{'case_id':'P_stress','config_hash':'1','signature':'2'}]
        reference=bench.verify_outputs(None,items)
        self.assertEqual(bench.verify_outputs(reference,items),reference)
        with self.assertRaises(AssertionError):bench.verify_outputs(reference,[dict(items[0],signature='3')])
        with self.assertRaises(AssertionError):bench.verify_outputs(None,items*2)

    def test_slowdown_or_pressure_stops_worker_escalation(self):
        a={'status':'ok','memory':{'pressure':None},'throughput_calls_per_s':2.}
        self.assertTrue(bench.should_increase(None,a))
        self.assertFalse(bench.should_increase(a,dict(a,throughput_calls_per_s=1.9)))
        self.assertFalse(bench.should_increase(a,dict(a,memory={'pressure':'low memory'})))
        self.assertFalse(bench.should_increase(a,dict(a,status='aborted')))

    def test_recommendation_excludes_even_completed_runs_with_late_pressure(self):
        safe={'status':'ok','memory':{'pressure':None},'throughput_calls_per_s':1.}
        unsafe=dict(safe,memory={'pressure':'late low-memory sample'},throughput_calls_per_s=2.)
        self.assertIs(bench.best_safe_run([safe,unsafe]),safe)
        self.assertIsNone(bench.best_safe_run([unsafe]))

    def test_low_memory_guard_prevents_model_load_and_process_pool(self):
        import psutil
        with tempfile.TemporaryDirectory() as temporary:
            base=Path(temporary);bundle=base/'bundle';bundle.mkdir()
            (bundle/'manifest.json').write_text(json.dumps({'bundle_hash':'1'*64}),encoding='utf-8')
            before=bench.snapshot(bundle)
            args=SimpleNamespace(artifact_dir=bundle,output=base/'report.json',mode='all',min_available_gib=2.,reference=None)
            with patch.object(psutil,'virtual_memory',return_value=SimpleNamespace(total=16*2**30,available=1)),patch.object(engine,'load_model',side_effect=AssertionError('guard failed')),patch.object(bench,'pool_run',side_effect=AssertionError('spawned under pressure')),contextlib.redirect_stdout(io.StringIO()):
                report=bench.run(args)
            self.assertEqual(report['status'],'blocked_memory_guard')
            self.assertEqual(report['not_run_worker_counts'],[1,2,4]);self.assertFalse(report['profiles'])
            self.assertIsNone(report['estimates_2550_by_profile']);self.assertTrue(report['inputs_unchanged'])
            self.assertEqual(bench.snapshot(bundle),before)
            with self.assertRaises(FileExistsError):bench.run(args)

    def test_profile_projection_is_labelled_estimate_and_includes_startup(self):
        result=bench.projections({'workers':2,'startup_s':4.,'items':[
            {'case_id':'P_one','task_wall_s':2.},{'case_id':'B_one','task_wall_s':4.}]})
        self.assertEqual(result['P']['estimated_2550_steady_s'],2550.)
        self.assertEqual(result['B']['estimated_2550_with_startup_s'],5104.)

    def test_native_thread_caps_set_before_scientific_imports(self):
        import subprocess
        code=f'''
import importlib.util,os,sys
spec=importlib.util.spec_from_file_location('isolated_benchmark',{str(ROOT/'tools/benchmark_routing.py')!r})
module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
assert all(os.environ[name]=='1' for name in module.THREAD_LIMITS)
assert sys.dont_write_bytecode
assert not any(n.startswith(('numpy','scipy','IPython','jupyter')) for n in sys.modules)
'''
        result=subprocess.run([sys.executable,'-I','-c',code],capture_output=True,text=True)
        self.assertEqual(result.returncode,0,result.stderr)

    def test_memory_stop_preserves_completed_partial_stage_measurement(self):
        model={'manifest':{'artifact_version':'tiny','bundle_hash':'1'*64},'od':{'od_version':'fixed','od_hash':'2'*64},'closure_id':'closure:test',
               'solutions':{},'reverse_paths':{}}
        request=engine.baseline_request(model,'disrupted').to_json()
        monitor=SimpleNamespace(pressure=None)
        profiler=MagicMock();profiler.__enter__.return_value=profiler
        def measure(*args):monitor.pressure='guard';return {'signature':'measured-before-stop'}
        profiler.measure.side_effect=measure
        with patch.object(bench,'StageProfiler',return_value=profiler),self.assertRaises(bench.MemoryPressure) as context:
            bench.profile_cases(engine,model,[{'case_id':'P_stress','request':request}],monitor)
        self.assertEqual(context.exception.partial[0]['measurements']['first_uncached']['signature'],'measured-before-stop')
        self.assertEqual(profiler.measure.call_count,1)


if __name__=='__main__':unittest.main()
