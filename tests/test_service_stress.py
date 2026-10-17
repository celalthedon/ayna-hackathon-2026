"""C5 phase 1: real service costs, immutable scenarios and shared v1 results."""
from dataclasses import replace
import hashlib
import json
import math
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'src'))
from citypilot import routing_engine as engine
from citypilot.contracts import ContractError,RoutingPatch,RoutingRequest,EvaluationResult,JourneyResult
BUNDLE=Path(os.environ['CITYPILOT_TEST_BUNDLE']) if os.environ.get('CITYPILOT_TEST_BUNDLE') else None


class CostKernelTests(unittest.TestCase):
    def test_parallel_winner_changes_after_stress_and_zero_edges_survive(self):
        import pandas as pd
        # The baseline winner is walking; faster bus movement must select the
        # other parallel alternative. CSR must never sum these alternatives.
        rows=[(0,1,8.,'walk',None),(0,1,10.,'bus_ride','SG_R2'),
              (1,2,3.75,'bus_board','SG_R2'),(2,3,25/60,'bus_continue','SG_R2'),
              (3,4,0.,'bus_ride','SG_R2'),(4,5,2.5,'metro_ride',None),(5,6,1.,'walk',None)]
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp)
            arcs=pd.DataFrame(rows,columns=['u','v','time_min','kind','service_group_id'])
            arcs.to_csv(root/'P_normal_arcs.csv.gz',index=False)
            graph=engine._minimum_graph([(u,v,t) for u,v,t,_,_ in rows],8)
            model={'root':root,'manifest':{'artifact_version':'small','bundle_hash':'1'*64},
                'od':{'od_version':'small','od_hash':'2'*64},'closure_id':'small:closure',
                'runtime':{'scenarios':{'P_normal':{'owned_offset':None,'profile':'P','state':'normal'}}},
                'services':pd.DataFrame([{'service_group_id':'SG_R2','headway_default_min':7.5},
                                          {'service_group_id':'SG_R14','headway_default_min':5.}]),
                'origins':{'o':{}},'destinations':{'d':{'properties':{'walk_node_id':6}}},
                'access':pd.DataFrame([{'profile':'P','origin_id':'o','physical_node_id':0,'entry_min':0.}]),
                'graphs':{'P_normal':graph},'arc_tables':{},'solutions':{},'reverse_paths':{},
                'provenance':engine._provenance('synthetic:c5','Synthetic parallel and zero-edge cost test'),'warnings':()}
            q=replace(engine.baseline_request(model),speed_factor=2,headway_factor_by_group={'SG_R2':1.2,'SG_R14':1})
            scenario,key=engine._scenario(model,q)
            self.assertEqual(graph[0,1],8);self.assertEqual(scenario['graphs'][key][0,1],5)
            self.assertEqual(scenario['graphs'][key].nnz,graph.nnz)
            self.assertEqual(engine._arcs(scenario,key).loc[(3,4),'time_min'],0)
            self.assertEqual(engine._arcs(scenario,key).loc[(0,1),'kind'],'bus_ride')
            result=engine.evaluate_package(model,q)
            self.assertAlmostEqual(result.od_results[0].minutes,5+4.5+25/60+2.5+1,places=12)
            self.assertEqual(graph[1,2],3.75)

    def test_nonfinite_derived_costs_rejected_and_source_table_unchanged(self):
        import pandas as pd
        table=pd.DataFrame([{'kind':'bus_ride','service_group_id':'R','time_min':10.},
                            {'kind':'bus_continue','service_group_id':'R','time_min':25/60},
                            {'kind':'bus_board','service_group_id':'R','time_min':3.75}])
        original=table.copy(deep=True)
        with self.assertRaisesRegex(ContractError,'non-finite'):
            engine._service_stress_arcs(table,1e-320,{'R':7.5},{'R':7.5})
        pd.testing.assert_frame_equal(table,original)


@unittest.skipUnless(BUNDLE,'Set CITYPILOT_TEST_BUNDLE to the explicit immutable bundle')
class ServiceStressTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):cls.model=engine.load_model(BUNDLE,BUNDLE/'config')

    def request(self,state='normal',profile='P',**changes):
        return replace(engine.baseline_request(self.model,state,profile),**changes)

    def test_factor_one_all_10872_rows_match_saved_baseline(self):
        import pandas as pd
        expected={'P_normal':(2060,2339,2496),'P_disrupted':(636,1191,1697),
                  'B_normal':(2406,2506,2511),'B_disrupted':(2406,2506,2511)}
        for key,counts in expected.items():
            profile,state=key.split('_')
            q=self.request(state,profile,speed_factor=1,headway_factor_by_group={'SG_R14':1,'SG_R2':1})
            result=engine.evaluate_package(self.model,q)
            baseline=engine.evaluate_package(self.model,self.request(state,profile))
            self.assertEqual(result.od_results,baseline.od_results)
            self.assertEqual(tuple(result.within_counts.values()),counts)
            saved=pd.read_csv(BUNDLE/f'od/times_{key}.csv.gz').set_index(['origin_id','destination_id'])
            refs={r.od_id:(r.origin_id,r.destination_id) for r in engine.get_od_table(self.model,profile)}
            self.assertEqual(len(result.od_results),2718)
            for row in result.od_results:
                value=saved.loc[refs[row.od_id]]
                self.assertEqual(row.status,value.status)
                if row.status=='no_path':self.assertIsNone(row.minutes)
                else:self.assertLessEqual(abs(row.minutes-value.total_min),1e-6)
                self.assertLessEqual(abs(row.capped_minutes-value.capped_min),1e-6)
            self.assertLessEqual(abs(result.capped_time_sum-saved.capped_min.sum()),1e-6)

    def test_nine_minute_headway_and_exact_seven_point_two_override(self):
        q=self.request(headway_factor_by_group={'SG_R2':1.2,'SG_R14':1})
        scenario,key=engine._scenario(self.model,q)
        arcs=engine._arcs(scenario,key)
        r2=arcs.loc[(arcs.kind=='bus_board')&(arcs.service_group_id=='SG_R2')]
        self.assertEqual(set(r2.pattern_id),{'2_A','2_B'})
        self.assertEqual(set(r2.time_min),{4.5})
        q=replace(q,state='mitigated',closure_id=self.model['closure_id'],
            patches=(RoutingPatch(kind='set_service_headway',target_id='SG_R2',headway_min=7.2),))
        scenario,key=engine._scenario(self.model,q);arcs=engine._arcs(scenario,key)
        self.assertEqual(set(arcs.loc[(arcs.kind=='bus_board')&(arcs.service_group_id=='SG_R2'),'time_min']),{3.6})

    def test_only_bus_movement_scales_dwell_metro_and_all_other_costs_exact(self):
        import numpy as np
        for profile in ('P','B'):
            q=self.request('normal',profile,speed_factor=1.25)
            scenario,key=engine._scenario(self.model,q)
            base=engine._arcs(self.model,key);changed=engine._arcs(scenario,key).loc[base.index]
            moving=base.kind=='bus_ride'
            np.testing.assert_array_equal(changed.loc[moving,'time_min'],base.loc[moving,'time_min']/1.25)
            np.testing.assert_array_equal(changed.loc[~moving,'time_min'],base.loc[~moving,'time_min'])
            self.assertEqual(set(changed.loc[changed.kind=='bus_continue','time_min']),{25/60})
            # Verify actual sparse graph weights, not only DataFrame metadata.
            graph=scenario['graphs'][key];original=self.model['graphs'][key]
            unchanged=base.loc[~moving].reset_index()
            np.testing.assert_array_equal(np.asarray(graph[unchanged.u,unchanged.v]),np.asarray(original[unchanged.u,unchanged.v]))

    def test_empty_mitigated_equals_disrupted_with_same_factors(self):
        for profile in ('P','B'):
            q=self.request('disrupted',profile,speed_factor=0.8,headway_factor_by_group={'SG_R2':1.2,'SG_R14':1.1})
            a=engine.evaluate_package(self.model,q);other=replace(q,state='mitigated')
            b=engine.evaluate_package(self.model,other)
            self.assertEqual(a.od_results,b.od_results)
            self.assertEqual(a.within_counts,b.within_counts);self.assertEqual(a.capped_time_sum,b.capped_time_sum)
            self.assertNotEqual(a.config_hash,b.config_hash)

    def test_invalid_factors_complete_mappings_and_unsupported_activations(self):
        catalog=engine.get_catalog(self.model)
        for mapping in ({},{'SG_R2':1.2},{'SG_R2':1,'SG_R14':1,'SVC_M2_A':1},
                        {'unknown':1,'SG_R2':1},{'SG_R2':1,'SG_R14':1e308}):
            q=self.request(headway_factor_by_group=mapping)
            with self.subTest(mapping=mapping),self.assertRaises(ContractError):engine.evaluate_package(self.model,q)
            if set(mapping)!=set(catalog.service_groups):
                with self.assertRaisesRegex(ContractError,'exactly cover'):catalog.validate_request(q)
        for value in (0,-1,True,'1',float('nan'),float('inf')):
            for changes in ({'speed_factor':value},{'headway_factor_by_group':{'SG_R2':value,'SG_R14':1}}):
                with self.subTest(changes=changes),self.assertRaises(ContractError):self.request(**changes)
        q=self.request('mitigated')
        with self.assertRaisesRegex(ContractError,'Unknown existing'):
            engine.evaluate_package(self.model,replace(q,patches=(RoutingPatch(kind='set_service_headway',target_id='SVC_M2_A',headway_min=7.2),)))
        for kind in ('activate_service','activate_link','enable_parking'):
            bad=self.request('mitigated','B',patches=(RoutingPatch(kind=kind,target_id='future:asset'),))
            with self.subTest(kind=kind),self.assertRaisesRegex(ContractError,'phase 1 unsupported patch'):
                engine.evaluate_package(self.model,bad)
        with self.assertRaisesRegex(ContractError,'Conflicting'):
            replace(q,patches=(RoutingPatch(kind='set_service_headway',target_id='SG_R2',headway_min=7.2),
                               RoutingPatch(kind='set_service_headway',target_id='SG_R2',headway_min=8)))

    def test_canonical_mapping_and_patch_order_hashes(self):
        patches=(RoutingPatch(kind='set_service_headway',target_id='SG_R2',headway_min=7.2),
                 RoutingPatch(kind='set_service_headway',target_id='SG_R14',headway_min=4.5))
        q=self.request('mitigated',speed_factor=0.8,headway_factor_by_group={'SG_R2':1.2,'SG_R14':1.1},patches=patches)
        other=replace(q,headway_factor_by_group={'SG_R14':1.1,'SG_R2':1.2},patches=tuple(reversed(patches))*2)
        self.assertEqual(q.config_hash,other.config_hash);self.assertEqual(q.to_json(),other.to_json())
        self.assertEqual(RoutingRequest.from_json(q.to_json()),q)
        self.assertEqual(engine.evaluate_package(self.model,q).od_results,engine.evaluate_package(self.model,other).od_results)

    def test_interleaving_requests_does_not_mutate_graphs_source_arcs_or_catalog(self):
        import numpy as np
        def fingerprint(graph):
            return hashlib.sha256(graph.data.tobytes()+graph.indices.tobytes()+graph.indptr.tobytes()).hexdigest()
        before={k:fingerprint(g) for k,g in self.model['graphs'].items()}
        catalog=engine.get_catalog(self.model).to_json()
        q=self.request();baseline=engine.evaluate_package(self.model,q)
        table=engine._arcs(self.model,'P_normal');times=table.time_min.to_numpy().copy()
        for factor in (0.7,1.3,0.8,1.4):
            changed=replace(q,speed_factor=factor,headway_factor_by_group={'SG_R2':1.2,'SG_R14':1.1})
            engine.evaluate_package(self.model,changed)
            self.assertEqual(engine.evaluate_package(self.model,q).od_results,baseline.od_results)
        self.assertEqual(before,{k:fingerprint(g) for k,g in self.model['graphs'].items()})
        np.testing.assert_array_equal(table.time_min,times)
        self.assertEqual(engine.get_catalog(self.model).to_json(),catalog)
        self.assertLessEqual(len(self.model['service_scenarios']),2)

    def test_stressed_terminal_grid_journeys_and_continuations_match_evaluation(self):
        continued=0;boarded=0
        grid=next(o for o in self.model['origins'] if ':grid:' in o)
        for state,profile in (('normal','P'),('disrupted','P'),('mitigated','P'),('mitigated','B')):
            patches=() if state!='mitigated' else (RoutingPatch(kind='set_service_headway',target_id='SG_R2',headway_min=7.2),)
            q=self.request(state,profile,speed_factor=0.8,headway_factor_by_group={'SG_R2':1.2,'SG_R14':1.1},patches=patches)
            result=engine.evaluate_package(self.model,q);result.validate_request(q)
            scenario,key=engine._scenario(self.model,q);arcs=engine._arcs(scenario,key)
            for origin in ('origin:terminal:baku_international',grid):
                journey=engine.inspect_journey(self.model,q,origin,next(iter(self.model['destinations'])))
                row=next(r for r in result.od_results if r.od_id==journey.od_id)
                self.assertEqual(row.status,journey.status);self.assertAlmostEqual(row.minutes,journey.total_min,places=6)
                self.assertAlmostEqual(math.fsum(l.total_min for l in journey.legs),journey.total_min,places=6)
                self.assertEqual(JourneyResult.from_json(journey.to_json()),journey)
                if origin==grid:
                    selected=next(r for r in engine._solve(scenario,key) if r['origin_id']==origin and r['destination_id']==journey.destination_id)
                    self.assertAlmostEqual(sum(l.total_min for l in journey.legs[:2]),selected['entry']['entry_min'],places=9)
                for leg in journey.legs:
                    if not (leg.from_id.startswith('state:') and leg.to_id.startswith('state:')):continue
                    arc=arcs.loc[(int(leg.from_id[6:]),int(leg.to_id[6:]))]
                    if arc.kind=='bus_board':
                        boarded+=1;self.assertAlmostEqual(leg.wait_min,engine._effective_headways(self.model,q)[arc.service_group_id]/2,places=12)
                    elif arc.kind=='bus_continue':
                        continued+=1;self.assertEqual(leg.wait_min,0);self.assertAlmostEqual(leg.ride_min,25/60,places=12)
        self.assertGreater(boarded,0);self.assertGreater(continued,0)

    def test_clean_process_stress_and_notebook_export_numerical_parity(self):
        script=f'''
import sys,json
from pathlib import Path
from dataclasses import replace
sys.path.insert(0,{str(ROOT/'src')!r})
from citypilot import routing_engine as e
from citypilot.contracts import RoutingPatch
assert not any(n.startswith(('IPython','jupyter','numpy','pandas')) for n in sys.modules)
b=Path({str(BUNDLE)!r});m=e.load_model(b,b/'config')
q=replace(e.baseline_request(m,'mitigated'),speed_factor=0.8,headway_factor_by_group={{'SG_R2':1.2,'SG_R14':1}},patches=(RoutingPatch(kind='set_service_headway',target_id='SG_R2',headway_min=7.2),))
r=e.evaluate_package(m,q);j=e.inspect_journey(m,q,'origin:terminal:baku_international',next(iter(m['destinations'])))
for x in (q,e.get_catalog(m),r,j):assert type(x).from_json(x.to_json())==x
nb=json.loads(Path({str(ROOT/'notebooks/01_network_routing.ipynb')!r}).read_text(encoding='utf-8'))
source='\\n\\n'.join(''.join(c['source']) for c in nb['cells'] if 'routing_export' in c.get('metadata',{{}}).get('tags',[]))
scope={{}};exec(compile(source,'<tagged-definitions>','exec'),scope)
assert scope['evaluate_package'](m,q).od_results==r.od_results
assert scope['inspect_journey'](m,q,j.origin_id,j.destination_id)==j
assert not any(n.startswith(('IPython','jupyter','http.server')) for n in sys.modules)
print('clean C5 load/evaluate/journey and source/export parity OK')
'''
        with tempfile.TemporaryDirectory() as temp:run=subprocess.run([sys.executable,'-I','-X','utf8','-c',script],cwd=temp,capture_output=True,text=True)
        self.assertEqual(run.returncode,0,run.stderr)


if __name__=='__main__':unittest.main()
