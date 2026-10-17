"""Focused offline construction tests; engine suites are reused from 9915cac."""
import copy
import csv
from dataclasses import replace
import json
import math
from pathlib import Path
import sys
import tempfile
import unittest

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'src'))
from citypilot.m_service_builder import (Anchor,BusRoadNetwork,ORDERS,read_stops,
                                        prepare,canonical,build_supplement)
SOURCE=ROOT/'supplements/m_services_v1/source_stops.csv'


def network(xy, links):
    import pandas as pd
    nodes=pd.DataFrame([{'node_id':i,'x':x,'y':y} for i,(x,y) in enumerate(xy)]).set_index('node_id',drop=False)
    edges=[]
    for eid,u,v,forward,reverse,length in links:
        edges.append({'edge_id':eid,'u':u,'v':v,'x0':xy[u][0],'y0':xy[u][1],
                      'x1':xy[v][0],'y1':xy[v][1],'length_m':length,
                      'drive_forward':forward,'drive_reverse':reverse,'walk_forward':True,
                      'walk_reverse':True,'edge_type':'road','fclass':'busway'})
    return BusRoadNetwork(nodes,pd.DataFrame(edges))


class NetworkTests(unittest.TestCase):
    def test_oneway_partial_costs_and_independent_return(self):
        n=network([(0.,0.),(100.,0.),(100.,100.),(0.,100.)],
                  [('a',0,1,True,False,200.),('b',1,2,True,False,100.),
                   ('c',2,3,True,False,100.),('d',3,0,True,False,100.)])
        a=n.snap((25.,2.),10.);b=n.snap((75.,2.),10.)
        self.assertAlmostEqual(n.pattern([a,b])[0],100.)
        self.assertAlmostEqual(n.pattern([b,a])[0],400.)
        back=n.pattern([b,a])[1][0][1]
        self.assertEqual([p[0] for p in back],['a','b','c','d','a'])
        self.assertTrue(all(y>=x for _,x,y in back))
        self.assertEqual(len(n.edges),4)  # Busways retained.

    def test_intermediate_orientation_prevents_artificial_uturn(self):
        n=network([(0.,0.),(100.,0.)],[('a',0,1,True,True,100.)])
        a=n.snap((20.,0.),1.);b=n.snap((80.,0.),1.)
        self.assertAlmostEqual(n.pattern([a,b])[0],60.)
        self.assertAlmostEqual(n.pattern([b,a])[0],60.)
        # Two independent legs would reverse at the artificial 80 m anchor.
        solved=n.pattern([a,b,a])
        self.assertAlmostEqual(solved[0],160.)
        self.assertEqual(solved[2],[1,-1,-1])
        self.assertEqual(solved[1][0][1],[('a',.2,1.),('a',1.,.8)])
        self.assertEqual(solved[1][1][1],[('a',.8,.2)])

    def test_no_geometric_grade_join_or_farther_reachable_resnap(self):
        n=network([(0.,0.),(100.,0.),(0.,0.),(100.,0.),(100.,10.),(200.,10.)],
                  [('a',0,1,True,False,100.),('b',2,3,True,False,100.),('c',3,4,True,False,10.),('d',4,5,True,False,100.)])
        a=n.snap((50.,0.),100.);b=n.snap((150.,10.),100.)
        self.assertEqual(a.edge_id,'a')
        self.assertIsNone(n.pattern([a,b]))
        self.assertGreater(n.snap((50.,1000.),1.).displacement_m,1.)

    def test_endpoint_anchor_does_not_force_full_edge_and_geometry_follows_cost(self):
        n=network([(0.,0.),(100.,0.),(100.,100.)],
                  [('a',0,1,True,False,300.),('b',1,2,True,False,200.)])
        a=n.snap((100.,0.),1.);b=n.snap((100.,50.),1.)
        result=n.pattern([a,b]);self.assertEqual(result[0],100.)
        class Identity:
            def transform(self,*xy):return xy
        self.assertEqual(n.geometry(result[1][0][1],Identity(),a),
                         {'type':'LineString','coordinates':[[100.,0.],[100.,50.]]})

    def test_bad_network_and_parameters(self):
        with self.assertRaisesRegex(ValueError,'Invalid road'):
            network([(0.,0.),(1.,0.)],[('a',0,1,True,False,float('nan'))])
        n=network([(0.,0.),(1.,0.)],[('a',0,1,True,False,1.)])
        for limit in (0.,-1.,float('inf'),float('nan')):
            with self.assertRaises(ValueError):n.snap((0.,0.),limit)


class InputAndPreparationTests(unittest.TestCase):
    def setUp(self):
        self.temporary=tempfile.TemporaryDirectory();self.addCleanup(self.temporary.cleanup)
        self.root=Path(self.temporary.name)
        self.rows=read_stops(SOURCE)

    def write_csv(self,rows,columns=None):
        path=self.root/'stops.csv'
        with path.open('w',encoding='utf-8',newline='') as f:
            writer=csv.DictWriter(f,fieldnames=columns or list(self.rows[0]));writer.writeheader();writer.writerows(rows)
        return path

    def test_original_strings_notes_and_expected_scope(self):
        self.assertEqual(len(self.rows),24)
        self.assertEqual(len({r['stop_key'] for r in self.rows}),7)
        self.assertEqual(self.rows[0]['google_stop_id'],'001001166')
        self.assertEqual(self.rows[0]['checked_by'],'Ali')
        self.assertIn('not published',self.rows[0]['notes'])
        self.assertEqual(sum(len(order)-1 for order in ORDERS.values())*2,14)

    def test_bad_and_missing_csv_inputs(self):
        with self.assertRaises(FileNotFoundError):read_stops(self.root/'missing.csv')
        mutations=[lambda r:r.pop(),
                   lambda r:r[0].update(seq='3'),lambda r:r[0].update(lat='nan'),
                   lambda r:r[0].update(line='M9'),lambda r:r[0].update(stop_key='different'),
                   lambda r:r[1].update(lat='40.0'),lambda r:r[0].update(order_status='assumption'),
                   lambda r:r[0].update(google_stop_id='1001166'),lambda r:r[2].update(seq='2')]
        for mutation in mutations:
            rows=copy.deepcopy(self.rows);mutation(rows)
            with self.subTest(mutation=mutation):
                with self.assertRaises(ValueError):read_stops(self.write_csv(rows))
        path=self.write_csv([{k:v for k,v in r.items() if k!='notes'} for r in self.rows],list(self.rows[0])[:-1])
        with self.assertRaisesRegex(ValueError,'columns'):read_stops(path)

    def model(self):
        import pandas as pd
        from pyproj import Transformer
        xy=[(400000.+i*100.,4470000.) for i in range(7)]
        n=network(xy,[(str(i),i,i+1,True,True,100.) for i in range(6)])
        model={'nodes':n.nodes,'edges':n.all_edges,'root':self.root,'runtime':{'metric_crs':'EPSG:32639'},
               'services':pd.DataFrame([{'service_group_id':'SG_R2','speed_kmh':20.},
                                        {'service_group_id':'SG_R14','speed_kmh':30.}])}
        (self.root/'curated').mkdir(exist_ok=True)
        (self.root/'curated/assumptions.csv').write_text('param_id,unit,value_default\nP5,min,5\n')
        backward=Transformer.from_crs('EPSG:32639','EPSG:4326',always_xy=True)
        by_stop={s:backward.transform(*p) for s,p in zip(sorted({r['stop_key'] for r in self.rows}),xy)}
        rows=copy.deepcopy(self.rows)
        for r in rows:r['lon'],r['lat']=map(str,by_stop[r['stop_key']])
        return model,rows

    def test_cycle_totals_dwell_variants_and_deterministic_output(self):
        model,rows=self.model();assets,report=prepare(model,rows,100.,3.)
        other,report2=prepare(model,list(reversed(rows)),100.,3.)
        # CSV row audit preserves input order; registered assets are order independent.
        self.assertEqual(canonical(assets),canonical(other))
        self.assertEqual(report['directions'],report2['directions'])
        patterns={p['pattern']['pattern_id']:p for p in assets['patterns']}
        self.assertEqual(len(assets['prebuilt_services']),10)
        for g in assets['prebuilt_services']:
            line=g['service_group_id'].split('_')[1]
            self.assertAlmostEqual(g['full_cycle_km'],math.fsum(math.fsum(patterns[p]['segment_m']) for p in g['pattern_ids'])/1000)
            self.assertEqual(g['stops_per_cycle'],2 if line in ('M2','M3') else 0)
            self.assertEqual(g['speed_kmh'],25.);self.assertEqual(g['layover_min'],10.)
            self.assertEqual(g['base_headway_min'],6. if g['service_group_id'].endswith('_A') else 9.)
            self.assertEqual(g['pattern_ids'],[line+'_A',line+'_B'])
            self.assertIn('CONSTRUCTED',g['provenance']['evidence'])

    def test_blocked_and_excessive_services_excluded(self):
        model,rows=self.model()
        # Break the only source link between two halves, while all snaps stay nearby.
        model['edges'].loc[2,['drive_forward','drive_reverse']]=False
        assets,report=prepare(model,rows,100.,3.)
        self.assertTrue(report['blocked_lines'])
        for line in report['blocked_lines']:
            self.assertFalse(any(g['service_group_id'].startswith('SVC_'+line+'_') for g in assets['prebuilt_services']))
        model,rows=self.model()
        for r in rows:
            if r['stop_key']=='M_ELMLER':r['lat']=str(float(r['lat'])+.001)
        _,report=prepare(model,rows,1.,3.)
        self.assertIn('M1',report['blocked_lines']);self.assertIn('M6',report['blocked_lines'])

    def test_missing_calibration_and_layover_rejected(self):
        model,rows=self.model();model['services']=model['services'].iloc[:1]
        with self.assertRaisesRegex(ValueError,'R2/R14'):prepare(model,rows,100.,3.)
        model,rows=self.model();(self.root/'curated/assumptions.csv').write_text('param_id,unit,value_default\n')
        with self.assertRaisesRegex(ValueError,'P5'):prepare(model,rows,100.,3.)

    def test_builder_wont_write_into_bundle_or_over_existing_output(self):
        bundle=self.root/'bundle';bundle.mkdir()
        with self.assertRaisesRegex(ValueError,'separate'):build_supplement(bundle,SOURCE,bundle/'output',max_snap_m=100.)
        existing=self.root/'existing';existing.mkdir()
        with self.assertRaisesRegex(ValueError,'exists'):build_supplement(bundle,SOURCE,existing,max_snap_m=100.)


if __name__=='__main__':unittest.main()
