"""Bounded routing profiling / Windows-spawn throughput; no production cache files."""
from __future__ import annotations

import argparse
import ast
from collections import defaultdict
from contextlib import contextmanager
import cProfile
from dataclasses import replace
from datetime import datetime,timezone
import gc
import hashlib
import inspect
import json
import multiprocessing as mp
import os
from pathlib import Path
import queue
import shutil
import sys
import tempfile
import threading
import time

THREAD_LIMITS=('OMP_NUM_THREADS','OPENBLAS_NUM_THREADS','MKL_NUM_THREADS',
               'NUMEXPR_NUM_THREADS','BLIS_NUM_THREADS','VECLIB_MAXIMUM_THREADS')
for _name in THREAD_LIMITS:os.environ[_name]='1'
os.environ['PYTHONDONTWRITEBYTECODE']='1'
sys.dont_write_bytecode=True
ROOT=Path(__file__).resolve().parents[1]
WORKER_MODEL=None


def sha(path):
    digest=hashlib.sha256()
    with Path(path).open('rb') as stream:
        for chunk in iter(lambda:stream.read(1024*1024),b''):digest.update(chunk)
    return digest.hexdigest()


def snapshot(directory):
    root=Path(directory)
    return {p.relative_to(root).as_posix():sha(p) for p in root.rglob('*') if p.is_file()}


def canonical(value):
    return json.dumps(value,sort_keys=True,separators=(',',':'),ensure_ascii=False,allow_nan=False)


def signature(wire):
    value=json.loads(wire);value.pop('duration_ms')
    return hashlib.sha256(canonical(value).encode('utf-8')).hexdigest()


def clear_solutions(model):
    model.get('service_scenarios',{}).clear()
    model['solutions'].clear();model['reverse_paths'].clear()


def workload(engine,model):
    from citypilot.contracts import RoutingPatch
    rows=[]
    for profile in ('P','B'):
        base=engine.baseline_request(model,'disrupted',profile)
        definitions=[
            ('stress',replace(base,speed_factor=.8,headway_factor_by_group={'SG_R2':1.2,'SG_R14':1.1})),
            ('headway',replace(base,state='mitigated',speed_factor=.9,
                headway_factor_by_group={'SG_R2':1.1,'SG_R14':1.2},patches=(
                    RoutingPatch(kind='set_service_headway',target_id='SG_R2',headway_min=7.2),))),
            ('activation6',replace(base,state='mitigated',patches=(
                    RoutingPatch(kind='activate_service',target_id='SYN_INS_28_6'),))),
            ('activation_both',replace(base,state='mitigated',speed_factor=1.15,
                headway_factor_by_group={'SG_R2':1.2,'SG_R14':1.1},patches=(
                    RoutingPatch(kind='activate_service',target_id='SYN_INS_28_6'),
                    RoutingPatch(kind='activate_service',target_id='SYN_INS_28_9'),
                    RoutingPatch(kind='set_service_headway',target_id='SG_R2',headway_min=8.0))))]
        rows.extend({'case_id':profile+'_'+name,'request':q.to_json()} for name,q in definitions)
    assert len({r['request'] for r in rows})==8
    catalog=engine.get_catalog(model)
    from citypilot.contracts import RoutingRequest
    for row in rows:catalog.validate_request(RoutingRequest.from_json(row['request']))
    return rows


class MemoryMonitor:
    """Sample this supervisor plus its child process tree; conservative summed RSS."""
    def __init__(self,min_available_bytes,max_tree_bytes):
        self.min_available=min_available_bytes;self.max_tree=max_tree_bytes
        self.peak_rss=0;self.peak_private=0;self.min_system_available=None
        self.max_threads={};self.samples=0;self.pressure=None
        self.stop_event=threading.Event();self.thread=None

    def sample(self):
        import psutil
        available=psutil.virtual_memory().available
        self.min_system_available=available if self.min_system_available is None else min(available,self.min_system_available)
        rss=private=0
        parent=psutil.Process()
        for process in [parent,*parent.children(recursive=True)]:
            try:
                memory=process.memory_info();rss+=memory.rss;private+=getattr(memory,'private',0)
                self.max_threads[str(process.pid)]=max(self.max_threads.get(str(process.pid),0),process.num_threads())
            except (psutil.NoSuchProcess,psutil.AccessDenied):pass
        self.samples+=1;self.peak_rss=max(self.peak_rss,rss);self.peak_private=max(self.peak_private,private)
        if available<self.min_available:self.pressure='system available memory below guard'
        if rss>self.max_tree:self.pressure='process-tree RSS exceeds guard'

    def start(self):
        self.sample()
        def loop():
            while not self.stop_event.wait(.05):self.sample()
        self.thread=threading.Thread(target=loop,daemon=True);self.thread.start();return self

    def finish(self):
        self.stop_event.set()
        if self.thread:self.thread.join()
        self.sample()
        return {'peak_tree_rss_bytes':self.peak_rss,'peak_tree_private_bytes':self.peak_private,
                'min_system_available_bytes':self.min_system_available,'samples':self.samples,
                'max_threads_by_pid':self.max_threads,'pressure':self.pressure,
                'sampling_interval_s':.05,'rss_note':'Sum of RSS may double-count shared pages; sampled peak is a lower bound on instantaneous peak.'}


class StageProfiler:
    """Temporary AST timing probes; never edit routing files or run notebook cells."""
    def __init__(self,engine):self.engine=engine;self.times=defaultdict(float);self.saved={}

    @contextmanager
    def region(self,name):
        start=time.perf_counter()
        try:yield
        finally:self.times[name]+=time.perf_counter()-start

    def wrapped(self,function,name):
        def run(*args,**kwargs):
            with self.region(name):return function(*args,**kwargs)
        return run

    def probe(self,node,name):
        return ast.With(items=[ast.withitem(context_expr=ast.Call(func=ast.Name(id='_benchmark_region',ctx=ast.Load()),
                        args=[ast.Constant(name)],keywords=[]),optional_vars=None)],body=[node],type_comment=None)

    def rewrite(self,name):
        tree=ast.parse(inspect.getsource(self.saved[name]));body=[];matched=[]
        for node in tree.body[0].body:
            if isinstance(node,ast.Assign):
                target=ast.unparse(node.targets[0])
                if name=='_scenario' and target=='graph':
                    body.append(self.probe(node,'csr_build'));matched.append('csr');continue
                if name=='_scenario' and target=='arcs' and 'sort_values' in ast.unparse(node.value):
                    body.append(self.probe(node,'parallel_minimum'));matched.append('minimum');continue
                if name=='_solve' and target=='(distances, predecessors)':
                    call=node.value
                    transpose=ast.Assign(targets=[ast.Name(id='_benchmark_reverse_graph',ctx=ast.Store())],value=call.args[0])
                    call.args[0]=ast.Name(id='_benchmark_reverse_graph',ctx=ast.Load())
                    body.extend([self.probe(transpose,'reverse_csr'),self.probe(node,'dijkstra')]);matched.append('dijkstra');continue
            body.append(node)
        expected=['minimum','csr'] if name=='_scenario' else ['dijkstra']
        if matched!=expected:raise RuntimeError('Timing probe anchors changed: '+name+': '+str(matched))
        tree.body[0].body=body;ast.fix_missing_locations(tree)
        exec(compile(tree,'<benchmark probes '+name+'>','exec'),self.engine.__dict__)
        return getattr(self.engine,name)

    def __enter__(self):
        names=('_scenario','_solve','_raw_arcs','_service_stress_arcs','_activate_services')
        self.saved={name:getattr(self.engine,name) for name in names}
        self.engine.__dict__['_benchmark_region']=self.region
        try:
            for name in ('_scenario','_solve'):setattr(self.engine,name,self.wrapped(self.rewrite(name),name))
            for name in ('_raw_arcs','_service_stress_arcs','_activate_services'):
                setattr(self.engine,name,self.wrapped(self.saved[name],name))
        except Exception:
            self.__exit__();raise
        return self

    def __exit__(self,*args):
        for name,value in self.saved.items():setattr(self.engine,name,value)
        self.engine.__dict__.pop('_benchmark_region',None)

    def measure(self,model,request):
        self.times.clear();start=time.perf_counter()
        result=self.engine.evaluate_package(model,request);wall=time.perf_counter()-start
        start=time.perf_counter();wire=result.to_json();serialization=time.perf_counter()-start
        t=self.times
        stages={'asset_scenario_preparation_s':t['_scenario']-t['_raw_arcs']-t['_service_stress_arcs']-t['parallel_minimum']-t['csr_build'],
            'arc_weight_construction_s':t['_raw_arcs']+t['_service_stress_arcs']+t['parallel_minimum'],
            'sparse_graph_construction_s':t['csr_build']+t['reverse_csr'],'shortest_path_s':t['dijkstra'],
            'od_access_reduction_s':t['_solve']-t['reverse_csr']-t['dijkstra'],
            'result_construction_validation_s':wall-t['_scenario']-t['_solve']}
        assert abs(sum(stages.values())-wall)<1e-6
        return {'evaluation_wall_s':wall,'duration_ms':result.duration_ms,'serialization_s':serialization,
                'total_with_serialization_s':wall+serialization,'stages':stages,'probe_details_s':dict(t),
                'config_hash':result.config_hash,'od_count':len(result.od_results),'signature':signature(wire)}


class MemoryPressure(RuntimeError):
    def __init__(self,reason,partial):super().__init__(reason);self.partial=partial


def profile_cases(engine,model,rows,monitor):
    from citypilot.contracts import RoutingRequest
    result=[]
    # Six representative configurations; the both-variant case remains in the pool workload.
    with StageProfiler(engine) as profiler:
        for row in rows:
            if row['case_id'].endswith('_both'):continue
            request=RoutingRequest.from_json(row['request']);measurements={}
            for label,uncached in (('first_uncached',True),('immediate_cached_repeat',False),('second_uncached',True)):
                if monitor.pressure:
                    if measurements:result.append({'case_id':row['case_id'],'measurements':measurements,'status':'partial_memory_guard'})
                    raise MemoryPressure(monitor.pressure,result)
                if uncached:clear_solutions(model)
                measurements[label]=profiler.measure(model,request)
            assert len({m['signature'] for m in measurements.values()})==1
            result.append({'case_id':row['case_id'],'measurements':measurements})
            print('profile',row['case_id'],{k:round(v['evaluation_wall_s'],3) for k,v in measurements.items()},flush=True)
    # Independent profiler diagnostic, explicitly excluded from throughput figures.
    if monitor.pressure:raise MemoryPressure(monitor.pressure,result)
    request=RoutingRequest.from_json(rows[0]['request']);clear_solutions(model)
    profile=cProfile.Profile();profile.enable();engine.evaluate_package(model,request);profile.disable()
    stats=sorted(profile.getstats(),key=lambda s:s.totaltime,reverse=True)[:25]
    top=[{'function':(Path(s.code.co_filename).name+':'+str(s.code.co_firstlineno)+':'+s.code.co_name) if hasattr(s.code,'co_name') else str(s.code),
          'calls':s.callcount,'cumulative_s':s.totaltime,'self_s':s.inlinetime} for s in stats]
    return result,top


def worker_init(bundle,config,ready):
    global WORKER_MODEL
    sys.path.insert(0,str(ROOT/'src'))
    from citypilot import routing_engine as engine
    started=time.perf_counter()
    try:
        WORKER_MODEL=engine.load_model(bundle,config)
        ready.put({'pid':os.getpid(),'load_s':time.perf_counter()-started})
    except Exception as exc:ready.put({'pid':os.getpid(),'error':type(exc).__name__+': '+str(exc)})


def worker_evaluate(row):
    from citypilot import routing_engine as engine
    from citypilot.contracts import RoutingRequest
    started=time.perf_counter();request=RoutingRequest.from_json(row['request'])
    # Every workload item is unique. Explicit cache clearing makes uncached intent testable.
    clear_solutions(WORKER_MODEL)
    before=time.perf_counter();result=engine.evaluate_package(WORKER_MODEL,request);wall=time.perf_counter()-before
    assert result.config_hash==request.config_hash
    before=time.perf_counter();wire=result.to_json();serialization=time.perf_counter()-before
    return {'case_id':row['case_id'],'pid':os.getpid(),'config_hash':result.config_hash,
            'signature':signature(wire),'evaluation_wall_s':wall,'duration_ms':result.duration_ms,
            'serialization_s':serialization,'task_wall_s':time.perf_counter()-started,
            'od_count':len(result.od_results),'within_counts':dict(result.within_counts)}


def pool_run(bundle,config,rows,workers,min_available,max_tree):
    ctx=mp.get_context('spawn');ready=ctx.Queue();monitor=MemoryMonitor(min_available,max_tree).start()
    pool=None;started=time.perf_counter();initial=[];items=[];startup=None
    try:
        if monitor.pressure:return {'workers':workers,'status':'blocked_memory_guard','memory':monitor.finish()}
        pool=ctx.Pool(workers,initializer=worker_init,initargs=(str(bundle),str(config),ready))
        deadline=time.perf_counter()+120
        while len(initial)<workers:
            if monitor.pressure:raise RuntimeError(monitor.pressure)
            if time.perf_counter()>deadline:raise RuntimeError('worker startup timeout')
            try:
                item=ready.get(timeout=.1)
                if 'error' in item:raise RuntimeError(item['error'])
                initial.append(item)
            except queue.Empty:pass
        startup=time.perf_counter()-started;work_started=time.perf_counter()
        pending=pool.map_async(worker_evaluate,rows,chunksize=1)
        while not pending.ready():
            if monitor.pressure:raise RuntimeError(monitor.pressure)
            if time.perf_counter()-work_started>180:raise RuntimeError('bounded workload timeout')
            pending.wait(.05)
        items=pending.get();work_s=time.perf_counter()-work_started
        pool.close();pool.join();pool=None
        return {'workers':workers,'status':'ok','startup_s':startup,'worker_loads':initial,
                'workload_s':work_s,'shutdown_and_total_s':time.perf_counter()-started,
                'throughput_calls_per_s':len(rows)/work_s,'items':items,'memory':monitor.finish()}
    except Exception as exc:
        if pool:pool.terminate();pool.join();pool=None
        return {'workers':workers,'status':'aborted','reason':str(exc),'items':items,'startup_s':startup,
                'elapsed_s':time.perf_counter()-started,'worker_loads':initial,'memory':monitor.finish()}
    finally:
        if pool:pool.terminate();pool.join()
        ready.close();ready.join_thread()


def should_increase(previous,current):
    if current['status']!='ok' or current['memory']['pressure']:return False
    return previous is None or current['throughput_calls_per_s']>previous['throughput_calls_per_s']


def best_safe_run(runs):
    # A late monitor observation can flag pressure even after work completed.
    candidates=[r for r in runs if r['status']=='ok' and not r['memory']['pressure']]
    return max(candidates,key=lambda r:r['throughput_calls_per_s'],default=None)


def verify_outputs(expected,items):
    observed={r['case_id']:(r['config_hash'],r['signature']) for r in items}
    assert len(observed)==len(items),'Duplicate workload result'
    if expected is not None:assert observed==expected,'Sequential/parallel full OD result or config hash mismatch'
    return observed


def projections(run):
    """Mixed-workload estimate, not a measured profile-exclusive 2550-call run."""
    result={}
    for profile in ('P','B'):
        rows=[r for r in run['items'] if r['case_id'].startswith(profile+'_')]
        average=sum(r['task_wall_s'] for r in rows)/len(rows)
        result[profile]={'sample_calls':len(rows),'mean_task_s_under_measured_concurrency':average,
                        'estimated_2550_steady_s':2550*average/run['workers'],
                        'estimated_2550_with_startup_s':2550*average/run['workers']+run['startup_s']}
    return result


def run(args):
    import psutil
    sys.path.insert(0,str(ROOT/'src'))
    from citypilot import routing_engine as engine
    bundle=args.artifact_dir.resolve();output=args.output.resolve()
    if output.exists():raise FileExistsError('Report already exists; preserve it and choose a new output')
    if output.is_relative_to(bundle):raise ValueError('Output must be outside immutable bundle')
    original=snapshot(bundle);vm=psutil.virtual_memory();minimum=int(args.min_available_gib*2**30)
    maximum=min(int(vm.total*.45),6*2**30)
    report={'schema':'routing-performance-1','mode':args.mode,'python':sys.executable,
            'retrieved_at_utc':datetime.now(timezone.utc).isoformat(),
            'source_sha256':sha(ROOT/'src/citypilot/routing_engine.py'),
            'bundle_hash':json.loads((bundle/'manifest.json').read_text())['bundle_hash'],
            'system':{'total_memory_bytes':vm.total,'available_before_bytes':vm.available,
                      'logical_cpus':psutil.cpu_count(),'physical_cpus':psutil.cpu_count(logical=False)},
            'native_thread_environment':{name:os.environ[name] for name in THREAD_LIMITS},
            'guard':{'min_available_bytes':minimum,'max_tree_rss_bytes':maximum},
            'planned_worker_counts':[1,2,4] if args.mode in ('throughput','all') else [],
            'worker_runs':[],'profiles':[],'estimates_2550_by_profile':None,
            'cache_policy':'process-local RAM only; no routing cache files; only supervisor writes report; no pyc writes',
            'workload_limit':'8 distinct configs, 4 per profile; no exhaustive search',
            'notes':['Synthetic shuttle is not final M workload. OS filesystem cache is not flushed.',
                     'Worker IPC returns compact full-result fingerprints/metrics, not full OD payloads.',
                     'Instrumented stage profiles are separate from uninstrumented spawn throughput.',
                     'duration_ms is captured before final EvaluationResult validation; external wall and serialization are separate.']}
    if vm.available<minimum:
        report.update(status='blocked_memory_guard',reason='Insufficient free memory before loading any model',
                      worker_runs=[],profiles=[],projections_2550=None)
    else:
        with tempfile.TemporaryDirectory(prefix='citypilot-routing-benchmark-') as temporary:
            config=Path(temporary)/'config';shutil.copytree(bundle/'config',config)
            shutil.copytree(ROOT/'tests/fixtures/prebuilt_services',config/'prebuilt_services')
            config_before=snapshot(config)
            if args.mode in ('profile','all'):
                monitor=MemoryMonitor(minimum,maximum).start();started=time.perf_counter()
                model=engine.load_model(bundle,config);report['model_load_s']=time.perf_counter()-started
                if monitor.pressure:
                    report.update(status='blocked_memory_guard',reason=monitor.pressure,profiles=[])
                else:
                    rows=workload(engine,model)
                    try:
                        report['profiles'],report['cprofile_diagnostic']=profile_cases(engine,model,rows,monitor)
                        report['workload']=rows;report['status']='ok'
                    except MemoryPressure as exc:
                        report.update(status='stopped_memory_guard',reason=str(exc),profiles=exc.partial)
                report['profile_memory']=monitor.finish();del model;gc.collect()
            else:
                # One temporary load obtains canonical request identity; released before workers start.
                monitor=MemoryMonitor(minimum,maximum).start();started=time.perf_counter()
                model=engine.load_model(bundle,config);report['canonical_request_load_s']=time.perf_counter()-started
                rows=workload(engine,model);report['workload']=rows;del model;gc.collect()
                report['canonical_request_load_memory']=monitor.finish()
                report['status']='blocked_memory_guard' if monitor.pressure else 'ok'
            if args.mode in ('throughput','all') and report['status']=='ok':
                runs=[];previous=None;expected=None
                for workers in (1,2,4):
                    current=pool_run(bundle,config,rows,workers,minimum,maximum);runs.append(current)
                    print('pool',workers,current['status'],current.get('throughput_calls_per_s'),flush=True)
                    if current['status']=='ok':
                        observed=verify_outputs(expected,current['items'])
                        if expected is None:expected=observed
                        current['sequential_parallel_parity']=True
                        if args.reference:
                            reference=json.loads(args.reference.read_text())
                            reference={r['case_id']:r['measurements']['first_uncached'] for r in reference['profiles']}
                            for item in current['items']:
                                if item['case_id'] in reference:assert item['signature']==reference[item['case_id']]['signature']
                    if not should_increase(previous,current):
                        report['worker_stop_reason']=current['memory']['pressure'] or current.get('reason') or 'slower throughput at higher worker count'
                        break
                    previous=current
                report['worker_runs']=runs
                # Uniform mixed-workload extrapolation; not 2,550 packages executed.
                best=best_safe_run(runs)
                if best is not None:
                    report['recommended_workers_for_measured_workload']=best['workers']
                    report['estimated_2550_mixed_calls_s']=2550/best['throughput_calls_per_s']
                    report['estimates_2550_by_profile']=projections(best)
                if any(r['status']!='ok' for r in runs):report['status']='partial'
            assert snapshot(config)==config_before,'Benchmark mutated shared config/fixture inputs'
    assert snapshot(bundle)==original,'Benchmark mutated immutable bundle files'
    report['not_run_worker_counts']=[n for n in report['planned_worker_counts'] if n not in {r['workers'] for r in report['worker_runs']}]
    report['inputs_unchanged']=True;output.parent.mkdir(parents=True,exist_ok=True)
    with output.open('x',encoding='utf-8') as stream:json.dump(report,stream,ensure_ascii=False,sort_keys=True,indent=2,allow_nan=False)
    print('report',output,'status',report['status'],flush=True)
    return report


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--artifact-dir',type=Path,required=True)
    parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--mode',choices=('profile','throughput','all'),default='all')
    parser.add_argument('--reference',type=Path)
    parser.add_argument('--min-available-gib',type=float,default=2.)
    args=parser.parse_args()
    if not 1.5<=args.min_available_gib<=8:parser.error('min-available-gib must be between 1.5 and 8')
    run(args)


if __name__=='__main__':
    mp.freeze_support();main()
