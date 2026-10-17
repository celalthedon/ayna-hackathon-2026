"""C3/C4 validation against an explicit immutable bundle; no notebook execution."""
import copy
from dataclasses import replace
import hashlib
import json
import math
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'src'))
from citypilot import routing_engine as engine
from citypilot.contracts import ContractError,StressFactorsNotSupported,RoutingPatch,RoutingRequest,Provenance,JourneyResult,EvaluationResult,ModelCatalog

BUNDLE=Path(os.environ['CITYPILOT_TEST_BUNDLE']) if os.environ.get('CITYPILOT_TEST_BUNDLE') else None


class SmallAdapterTests(unittest.TestCase):
    def test_reverse_solver_distinguishes_no_path_and_physical_over_cap(self):
        import pandas as pd
        graph=engine._minimum_graph([(0,1,0.),(1,2,130.)],4)
        model={'manifest':{'artifact_version':'small-case','bundle_hash':'1'*64},
            'od':{'od_version':'small-od','od_hash':'2'*64},'closure_id':'closure:test',
            'runtime':{'scenarios':{'P_normal':{'owned_offset':None,'profile':'P','state':'normal'}}},
            'origins':{'a':{},'b':{}},'destinations':{'d':{'properties':{'walk_node_id':2}}},
            'graphs':{'P_normal':graph},'solutions':{},'reverse_paths':{},
            'access':pd.DataFrame([{'profile':'P','origin_id':o,'physical_node_id':n,'entry_min':0.0}
                                   for o,n in [('a',0),('b',3)]]),
            'provenance':engine._provenance('synthetic:small-case','Explicit disconnected/130-minute test graph'),
            'warnings':('synthetic small case only',)}
        request=engine.baseline_request(model)
        result=engine.evaluate_package(model,request)
        self.assertEqual([(v.status,v.minutes) for v in result.od_results],[('over_cap',130.),('no_path',None)])
        self.assertEqual(result.capped_time_sum,240.)
        journey=engine.inspect_journey(model,request,'b','d')
        self.assertEqual(journey.status,'no_path');self.assertIsNone(journey.total_min)
        self.assertIsNone(journey.geometry);self.assertFalse(journey.legs)
        result.validate_request(request)

    def test_explicit_zero_and_min_parallel_edges(self):
        from scipy.sparse.csgraph import dijkstra
        graph=engine._minimum_graph([(0,1,4.),(0,1,0.),(1,2,2.),(0,2,10.)],4)
        self.assertEqual(graph.nnz,3)
        self.assertEqual(graph.data.min(),0)
        distance=dijkstra(graph,directed=True,indices=0)
        self.assertEqual(distance[2],2)
        self.assertTrue(math.isinf(distance[3]))
        self.assertEqual(engine._status_time(float(distance[3]),120),('no_path',None,120.))
        self.assertEqual(engine._status_time(130,120),('over_cap',130.,120.))
        self.assertEqual(engine._status_time(120,120),('reachable',120.,120.))
        with self.assertRaises(ContractError):engine._status_time(float('nan'),120)

    def test_manifest_payload_and_hash_corruption(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);(root/'config').mkdir()
            (root/'payload').write_bytes(b'original')
            files={'payload':hashlib.sha256(b'original').hexdigest()}
            manifest={'artifact_version':'c4-alpha-1','files':files,
                'bundle_hash':hashlib.sha256(json.dumps(files,sort_keys=True).encode()).hexdigest()}
            (root/'manifest.json').write_text(json.dumps(manifest))
            (root/'payload').write_bytes(b'changed')
            with self.assertRaisesRegex(ContractError,'file hash mismatch'):
                engine.load_model(root,root/'config')
            manifest['bundle_hash']='0'*64
            (root/'manifest.json').write_text(json.dumps(manifest))
            with self.assertRaisesRegex(ContractError,'Bundle hash mismatch'):
                engine.load_model(root,root/'config')
            manifest['files']={'../escape':'0'*64}
            manifest['bundle_hash']=hashlib.sha256(json.dumps(manifest['files'],sort_keys=True).encode()).hexdigest()
            (root/'manifest.json').write_text(json.dumps(manifest))
            with self.assertRaisesRegex(ContractError,'escapes'):
                engine.load_model(root,root/'config')


@unittest.skipUnless(BUNDLE,'Set CITYPILOT_TEST_BUNDLE to the explicit validated bundle path')
class RealBundleTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.model=engine.load_model(BUNDLE,BUNDLE/'config')

    def test_bundle_identity_catalog_and_saved_rows(self):
        import pandas as pd
        self.assertEqual(self.model['manifest']['bundle_hash'],'9457bfe95125b1d8bddb1be662ad6f0bbd1a00c0ac8f8abcc2fbecf872d53066')
        self.assertEqual(self.model['od']['od_hash'],'10c1b58f1d704cec25b11936da32c2c09bc995323e8a4083fd0bd46f50286ac8')
        catalog=engine.get_catalog(self.model)
        self.assertEqual(set(catalog.service_groups),{'SG_R2','SG_R14'})
        self.assertEqual(len(catalog.patterns),4)
        self.assertFalse(catalog.links)
        self.assertFalse(catalog.prebuilt_services)
        self.assertEqual(len(catalog.parking),639)
        self.assertTrue(all(p.baseline_enabled and p.status=='assumption' for p in catalog.parking.values()))
        self.assertEqual(ModelCatalog.from_json(catalog.to_json()),catalog)
        for group in catalog.service_groups.values():
            source=self.model['services'].set_index('service_group_id').loc[group.service_group_id]
            self.assertAlmostEqual(group.speed_kmh,float(source.speed_kmh),places=10)
            self.assertEqual(group.stops_per_cycle,int(source.intermediate_stops))
            self.assertEqual(group.layover_min,10)
            self.assertAlmostEqual(group.full_cycle_km,float(source.cycle_km_geometry),places=10)
            self.assertEqual(group.dwell_s,25)
            self.assertEqual(group.field_status['speed_kmh'],'assumption')
            self.assertEqual(group.field_status['base_headway_min'],str(source.headway_status))
        expected={'P_normal':[2060,2339,2496],'P_disrupted':[636,1191,1697],
                  'B_normal':[2406,2506,2511],'B_disrupted':[2406,2506,2511]}
        for key,counts in expected.items():
            profile,state=key.split('_');request=engine.baseline_request(self.model,state,profile)
            result=engine.evaluate_package(self.model,request);result.validate_request(request)
            self.assertEqual([result.within_counts[t] for t in (40,45,50)],counts)
            self.assertEqual(len(result.od_results),2718)
            saved=pd.read_csv(BUNDLE/f'od/times_{key}.csv.gz').set_index(['origin_id','destination_id'])
            references={r.od_id:(r.origin_id,r.destination_id) for r in engine.get_od_table(self.model,profile)}
            self.assertEqual(len(references),2718)
            self.assertEqual(set(saved.index),set(references.values()))
            self.assertEqual(set(references),{r.od_id for r in result.od_results})
            self.assertEqual(EvaluationResult.from_json(result.to_json()),result)
            for row in result.od_results:
                ref=saved.loc[references[row.od_id]]
                self.assertEqual(row.status,ref.status)
                if row.status=='no_path':self.assertIsNone(row.minutes)
                else:self.assertLessEqual(abs(row.minutes-ref.total_min),1e-6)
                self.assertLessEqual(abs(row.capped_minutes-ref.capped_min),1e-6)
            self.assertLessEqual(abs(result.capped_time_sum-saved.capped_min.sum()),1e-6)
            self.assertTrue(math.isfinite(result.duration_ms))
            json.loads(result.to_json(),parse_constant=lambda value:self.fail('Non-finite JSON: '+value))

    def test_unsupported_requests_and_threshold_cap_identity(self):
        request=engine.baseline_request(self.model)
        unsupported=replace(request,state='mitigated',closure_id=self.model['closure_id'],patches=(RoutingPatch(kind='activate_link',target_id='x'),))
        with self.assertRaises(StressFactorsNotSupported):engine.evaluate_package(self.model,unsupported)
        for other in (replace(request,headway_factor_by_group={'SG_R2':1.2}),
                      replace(request,od_set_id='wrong'),replace(request,model_version='wrong'),
                      replace(request,state='disrupted',closure_id='unregistered')):
            with self.subTest(other=other),self.assertRaises(ContractError):engine.evaluate_package(self.model,other)
        with self.assertRaises(ContractError):RoutingRequest.from_dict(dict(request.to_dict(),assumptions=[]))
        changed=replace(request,thresholds_min=(40,42,45,50),primary_t_min=42,cap_min=50)
        self.assertNotEqual(changed.config_hash,request.config_hash)
        output=engine.evaluate_package(self.model,changed)
        self.assertEqual(set(output.within_counts),{40,42,45,50})
        self.assertTrue(any(r.status=='over_cap' and r.minutes>50 for r in output.od_results))
        traced=replace(request,candidate_ids=('trace:only',))
        self.assertEqual(engine.evaluate_package(self.model,traced).od_results,engine.evaluate_package(self.model,request).od_results)
        # Paths do not enter identity; immutable bundle hash binds baseline assumptions.
        moved=dict(self.model,root=Path('different-machine'),config=Path('different-config'))
        self.assertEqual(engine.baseline_request(moved).config_hash,request.config_hash)

    def test_terminal_grid_and_all_saved_predecessor_routes(self):
        model=self.model
        grid=next(v for v in model['origins'] if ':grid:' in v)
        terminal='origin:terminal:baku_international'
        for profile in ('P','B'):
            for state in ('normal','disrupted'):
                request=engine.baseline_request(model,state,profile);key=profile+'_'+state
                rows=engine._solve(model,key);targets,pred=model['reverse_paths'][key]
                graph=model['graphs'][key];arcs=engine._arcs(model,key)
                # Every saved pair must have an acyclic directed route to the exact
                # winning individual destination ownership state, not just a station.
                for row in rows:
                    cur=row['start'];seen={cur};elapsed=row['entry']['entry_min'];hops=0
                    nexts=pred[targets.index(row['target'])]
                    while cur!=row['target']:
                        nxt=int(nexts[cur]);self.assertGreaterEqual(nxt,0);self.assertNotIn(nxt,seen)
                        begin,end=graph.indptr[cur:cur+2]
                        import numpy as np
                        pos=int(np.searchsorted(graph.indices[begin:end],nxt))+begin
                        self.assertLess(pos,end);self.assertEqual(int(graph.indices[pos]),nxt)
                        elapsed+=float(graph.data[pos]);seen.add(nxt);cur=nxt;hops+=1
                    self.assertLessEqual(abs(elapsed-row['total']),1e-6)
                for origin in (terminal,grid):
                    for dest in (next(iter(model['destinations'])),list(model['destinations'])[-1]):
                        journey=engine.inspect_journey(model,request,origin,dest);journey.validate_request(request)
                        self.assertLessEqual(abs(sum(l.total_min for l in journey.legs)-journey.total_min),1e-6)
                        self.assertEqual(journey.legs[0].from_id,origin)
                        self.assertEqual(journey.legs[-1].to_id,dest)
                        self.assertEqual(type(journey).from_json(journey.to_json()),journey)
                        self.assertIs(type(journey),JourneyResult)
                        self.assertIsNotNone(journey.geometry)
                        if journey.geometry_metadata.partial:
                            self.assertEqual(journey.geometry.type,'MultiLineString')
                            self.assertIn('GEOMETRY_GAPS',journey.warnings)
                        evaluation=engine.evaluate_package(model,request)
                        evaluated=next(r for r in evaluation.od_results if r.od_id==journey.od_id)
                        self.assertEqual(evaluated.status,journey.status)
                        self.assertLessEqual(abs(evaluated.minutes-journey.total_min),1e-6)
                        selected=next(r for r in rows if r['origin_id']==origin and r['destination_id']==dest)
                        if origin==grid:
                            self.assertLessEqual(abs(journey.legs[0].walk_min-selected['entry']['entry_walk_min']),1e-9)
                            self.assertLessEqual(abs(journey.legs[1].total_min-selected['entry']['partial_edge_min']),1e-9)
                        if profile=='P':self.assertFalse(any(l.mode=='bike' for l in journey.legs))

    def test_projected_stop_shapes_use_saved_substrings(self):
        import numpy as np
        regenerated=engine.projected_bus_geometries(self.model)
        self.assertEqual(set(regenerated),set(self.model['bus_geometry']))
        for ride,geom in regenerated.items():
            ref=self.model['bus_geometry'][ride]['geometry']
            self.assertEqual(geom['type'],ref['type'])
            np.testing.assert_allclose(geom['coordinates'],ref['coordinates'],rtol=0,atol=1e-8)

    def test_profile_od_ids_and_tagged_source_numerical_parity(self):
        p=engine.get_od_table(self.model,'P');b=engine.get_od_table(self.model,'B')
        self.assertEqual([(r.origin_id,r.destination_id) for r in p],[(r.origin_id,r.destination_id) for r in b])
        self.assertFalse({r.od_id for r in p}&{r.od_id for r in b})
        document=json.loads((ROOT/'notebooks/01_network_routing.ipynb').read_text(encoding='utf-8'))
        code='\n\n'.join(''.join(c['source']) for c in document['cells'] if 'routing_export' in c.get('metadata',{}).get('tags',[]))
        scope={};exec(compile(code,'<tagged-definitions>','exec'),scope)
        self.assertEqual(scope['get_catalog'](self.model).to_json(),engine.get_catalog(self.model).to_json())
        for profile in ('P','B'):
            for state in ('normal','disrupted'):
                request=engine.baseline_request(self.model,state,profile)
                a=engine.evaluate_package(self.model,request).to_dict()
                b=scope['evaluate_package'](self.model,request).to_dict()
                a.pop('duration_ms');b.pop('duration_ms');self.assertEqual(a,b)
        request=engine.baseline_request(self.model)
        args=(self.model,request,'origin:terminal:baku_international',next(iter(self.model['destinations'])))
        self.assertEqual(scope['inspect_journey'](*args),engine.inspect_journey(*args))

    def test_clean_process_load_evaluate_catalog_journey(self):
        code=f'''
import sys
sys.path.insert(0,{str(ROOT/'src')!r})
from citypilot import routing_engine as e
assert not any(n.startswith(('IPython','jupyter','numpy','pandas')) for n in sys.modules)
from pathlib import Path
b=Path({str(BUNDLE)!r})
m=e.load_model(b,b/'config')
c=e.get_catalog(m)
request=e.baseline_request(m)
evaluation=e.evaluate_package(m,request)
journey=e.inspect_journey(m,request,'origin:terminal:baku_international',next(iter(m['destinations'])))
assert len(evaluation.od_results)==2718 and c.service_groups and not c.prebuilt_services and journey.total_min>0
from citypilot.contracts import RoutingRequest,ModelCatalog,EvaluationResult,JourneyResult
for value in (request,c,evaluation,journey):assert type(value).from_json(value.to_json())==value
assert type(journey) is JourneyResult
assert not any(n.startswith(('IPython','jupyter','http.server')) for n in sys.modules)
print('clean baseline adapter process OK')
'''
        with tempfile.TemporaryDirectory() as temp:
            run=subprocess.run([sys.executable,'-I','-c',code],cwd=temp,text=True,capture_output=True)
        self.assertEqual(run.returncode,0,run.stderr)
        self.assertIn('clean baseline adapter process OK',run.stdout)


if __name__=='__main__':unittest.main()
