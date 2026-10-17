"""Focused static distance checks; no Ali code, notebook or stress suite."""
import csv
import hashlib
import json
import math
import os
from pathlib import Path
import subprocess
import sys
import unittest

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'src'))
from citypilot.od_car_distances import CarNetwork,DistanceError,physical_distances,minimum_graph,graph_hash


def make_network(points,segments):
    import pandas as pd
    nodes=pd.DataFrame([{'x':x,'y':y,'endpoint_transition_assumed':False} for x,y in points])
    edges=[];arcs=[]
    for edge_id,u,v,forward,reverse,fclass in segments:
        x0,y0=points[u];x1,y1=points[v];length=math.hypot(x1-x0,y1-y0)
        edges.append(dict(edge_id=edge_id,u=u,v=v,x0=x0,y0=y0,x1=x1,y1=y1,length_m=length,
            drive_forward=forward,drive_reverse=reverse,fclass=fclass,edge_type='road'))
        for enabled,a,b,direction in ((forward,u,v,'forward'),(reverse,v,u,'reverse')):
            if enabled:arcs.append(dict(edge_id=edge_id,u=a,v=b,length_m=length,direction=direction))
    return CarNetwork(nodes,pd.DataFrame(edges),pd.DataFrame(arcs,columns=['edge_id','u','v','length_m','direction']))


class DistanceUnitTests(unittest.TestCase):
    def one_way(self):return make_network([(0,0),(100,0)],[('road',0,1,True,False,'residential')])

    def pair(self,network,origin,destination,limit=100):
        return physical_distances(network,{'o':network.snap(origin,limit)},{'d':network.snap(destination,limit)})['o','d']

    def test_saved_edge_id_index_is_normalized_without_mutating_source(self):
        import pandas as pd
        net=self.one_way();edges=net.edges.set_index('edge_id',drop=False)
        original=edges.copy(deep=True)
        nodes=pd.DataFrame([{'x':0.,'y':0.},{'x':100.,'y':0.}])
        derived=CarNetwork(nodes,edges,net.arcs)
        self.assertAlmostEqual(self.pair(derived,(20,0),(80,0))['car_distance_km'],0.06)
        pd.testing.assert_frame_equal(edges,original)

    def test_direct_same_segment_forward_no_endpoint_detour(self):
        row=self.pair(self.one_way(),(20,0),(80,0))
        self.assertEqual(row['status'],'modelled');self.assertAlmostEqual(row['car_distance_km'],0.06)

    def test_forbidden_reverse_has_no_path(self):
        row=self.pair(self.one_way(),(80,0),(20,0))
        self.assertEqual(row['status'],'no_path');self.assertIsNone(row['car_distance_km'])

    def test_two_way_direct_forward_and_reverse(self):
        net=make_network([(0,0),(100,0)],[('road',0,1,True,True,'residential')])
        for a,b in (((20,0),(80,0)),((80,0),(20,0))):self.assertAlmostEqual(self.pair(net,a,b)['car_distance_km'],0.06)

    def test_reverse_flag_only(self):
        net=make_network([(0,0),(100,0)],[('road',0,1,False,True,'residential')])
        self.assertEqual(self.pair(net,(20,0),(80,0))['status'],'no_path')
        self.assertAlmostEqual(self.pair(net,(80,0),(20,0))['car_distance_km'],0.06)

    def test_directed_asymmetric_partial_endpoints_with_loop(self):
        net=make_network([(0,0),(100,0),(100,100),(0,100)],
            [('a',0,1,True,False,'residential'),('b',1,2,True,False,'residential'),
             ('c',2,3,True,False,'residential'),('d',3,0,True,False,'residential')])
        self.assertAlmostEqual(self.pair(net,(20,0),(80,0))['car_distance_km'],0.06)
        self.assertAlmostEqual(self.pair(net,(80,0),(20,0))['car_distance_km'],0.34)

    def test_exact_endpoint_needs_no_forbidden_partial_reverse(self):
        # At B, a forward-only A->B segment must still allow departing B->C.
        net=make_network([(0,0),(100,0),(100,100)],
            [('a',0,1,True,False,'residential'),('b',1,2,True,False,'residential')])
        self.assertEqual(net.snap((100,0),100).edge_id,'a')
        self.assertAlmostEqual(self.pair(net,(100,0),(100,50))['car_distance_km'],0.05)
        self.assertAlmostEqual(self.pair(net,(20,0),(100,0))['car_distance_km'],0.08)
        self.assertEqual(self.pair(net,(100,0),(20,0))['status'],'no_path')

    def test_snap_displacement_excluded_and_justified_zero_preserved(self):
        net=self.one_way();row=self.pair(net,(20,3),(80,4))
        self.assertAlmostEqual(row['car_distance_km'],0.06)
        self.assertEqual((row['origin_snap_m'],row['destination_snap_m'],row['snap_m']),(3,4,4))
        zero=self.pair(net,(20,3),(20,-4))
        self.assertEqual(zero['status'],'modelled');self.assertEqual(zero['car_distance_km'],0)

    def test_snap_limit_failure_keeps_nearest_displacement(self):
        row=self.pair(self.one_way(),(20,101),(80,4))
        self.assertEqual(row['status'],'snap_failed');self.assertIsNone(row['car_distance_km'])
        self.assertEqual(row['snap_m'],101)
        self.assertEqual(self.pair(self.one_way(),(20,100),(80,4))['status'],'modelled')
        for limit in (0,-1,True,float('nan'),float('inf')):
            with self.assertRaises(DistanceError):self.one_way().snap((20,0),limit)

    def test_nearest_component_is_not_changed_to_find_a_route(self):
        net=make_network([(0,0),(100,0),(0,10),(200,10)],
            [('dead',0,1,True,True,'residential'),('connected',2,3,True,True,'residential')])
        row=self.pair(net,(50,1),(150,10))
        self.assertEqual(net.snap((50,1),100).edge_id,'dead')
        self.assertEqual(row['status'],'no_path')

    def test_deterministic_ties_do_not_join_grade_crossings(self):
        points=[(-10,0),(10,0),(0,-10),(0,10)]
        edges=[('a_lower',0,1,True,True,'residential'),('z_upper',2,3,True,True,'residential')]
        a=make_network(points,edges);b=make_network(points,list(reversed(edges)))
        self.assertEqual(a.snap((0,0),100).edge_id,'a_lower')
        self.assertEqual(a.snap((0,0),100),b.snap((0,0),100))
        self.assertEqual(self.pair(a,(-9,0),(0,9))['status'],'no_path')
        self.assertEqual(graph_hash(a.graph),graph_hash(b.graph))

    def test_busway_removed_from_routing_and_snapping(self):
        net=make_network([(0,0),(100,0),(0,20),(100,20)],
            [('busway',0,1,True,True,'busway'),('car',2,3,True,True,'residential')])
        self.assertEqual(net.summary['excluded_busway_segments'],1)
        self.assertEqual(set(net.arcs.edge_id),{'car'})
        self.assertEqual(net.snap((20,0),100).edge_id,'car')
        self.assertEqual(self.pair(net,(20,0),(80,0))['origin_snap_m'],20)

    def test_no_eligible_segment_reports_unknown_snap_distances(self):
        net=make_network([(0,0),(100,0)],[('bus',0,1,True,True,'busway')])
        row=self.pair(net,(20,0),(80,0))
        self.assertEqual(row['status'],'snap_failed');self.assertIsNone(row['snap_m'])
        self.assertIsNone(row['origin_snap_m']);self.assertIsNone(row['destination_snap_m'])

    def test_zero_edges_and_minimum_parallel_distance(self):
        import pandas as pd
        graph=minimum_graph(pd.DataFrame([(0,1,9.),(0,1,4.),(1,2,0.)],columns=['u','v','length_m']),3)
        self.assertEqual(graph.nnz,2);self.assertEqual(graph[0,1],4);self.assertIn(0,graph.data)
        net=make_network([(0,0),(10,0),(10,0),(20,0)],
            [('a',0,1,True,False,'residential'),('zero',1,2,True,False,'residential'),('c',2,3,True,False,'residential')])
        self.assertEqual(net.graph.nnz,3)
        self.assertEqual(net.summary['degenerate_segments_not_used_for_snapping'],1)
        self.assertAlmostEqual(self.pair(net,(0,0),(20,0))['car_distance_km'],0.02)

    def test_cli_requires_explicit_positive_finite_snap_limit(self):
        command=[sys.executable,'-I',str(ROOT/'tools/build_od_car_distances.py'),'--artifact-dir','missing']
        for extra in ([],['--max-snap-m','nan'],['--max-snap-m','0']):
            run=subprocess.run(command+extra,capture_output=True,text=True)
            self.assertNotEqual(run.returncode,0);self.assertIn('max-snap-m',run.stderr)


@unittest.skipUnless(os.environ.get('CITYPILOT_CAR_OUTPUT_DIR') and os.environ.get('CITYPILOT_TEST_BUNDLE'),
                     'Set explicit real supplement and bundle paths')
class RealSupplementTests(unittest.TestCase):
    def test_real_output_exact_evaluator_joins_profiles_hashes_and_finite_values(self):
        from collections import Counter
        from citypilot import routing_engine as routing
        root=Path(os.environ['CITYPILOT_CAR_OUTPUT_DIR']);bundle=Path(os.environ['CITYPILOT_TEST_BUNDLE'])
        manifest=json.loads((root/'manifest.json').read_text(),parse_constant=lambda x: self.fail(x))
        payload=(root/'od_car_distances.csv').read_bytes()
        self.assertEqual(hashlib.sha256(payload).hexdigest(),manifest['output_sha256']['od_car_distances.csv'])
        self.assertEqual(manifest['physical_pair_count'],2718);self.assertEqual(manifest['profile_row_count'],5436)
        self.assertEqual(manifest['policy']['max_snap_m'],100)
        self.assertEqual(manifest['filtered_car_graph']['excluded_busway_segments'],192)
        rows=list(csv.DictReader(payload.decode('utf-8').splitlines()))
        self.assertEqual(len(rows),5436);self.assertEqual(len({r['od_id'] for r in rows}),5436)
        self.assertEqual(dict(Counter(r['status'] for r in rows)),manifest['profile_status_counts'])
        physical={}
        for row in rows:
            pair=row['origin_id'],row['destination_id']
            value=tuple(row[c] for c in ('car_distance_km','status','snap_m','origin_snap_m','destination_snap_m'))
            if pair in physical:self.assertEqual(physical[pair],value)
            else:physical[pair]=value
            if row['status']=='modelled':
                self.assertTrue(math.isfinite(float(row['car_distance_km'])));self.assertGreaterEqual(float(row['car_distance_km']),0)
            else:self.assertEqual(row['car_distance_km'],'')
            if row['origin_snap_m'] and row['destination_snap_m']:
                self.assertEqual(float(row['snap_m']),max(float(row['origin_snap_m']),float(row['destination_snap_m'])))
        self.assertEqual(len(physical),2718)
        model=routing.load_model(bundle,bundle/'config')
        for profile in ('P','B'):
            expected=routing.evaluate_package(model,routing.baseline_request(model,profile=profile))
            actual={r['od_id']: (r['origin_id'],r['destination_id']) for r in rows if r['profile']==profile}
            self.assertEqual(set(actual),{r.od_id for r in expected.od_results})
            self.assertEqual(actual,{r.od_id:(r.origin_id,r.destination_id) for r in routing.get_od_table(model,profile)})
        for name,digest in manifest['input_sha256'].items():self.assertEqual(hashlib.sha256((bundle/name).read_bytes()).hexdigest(),digest)


if __name__=='__main__':unittest.main()
