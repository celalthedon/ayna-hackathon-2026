"""OD access gather regression: ties, ownership, explicit zeros and row isolation."""
from pathlib import Path
import sys
import unittest

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'src'))
from citypilot import routing_engine as engine


class SolverAccessTests(unittest.TestCase):
    def test_tied_endpoint_options_owned_destination_and_independent_records(self):
        import numpy as np
        import pandas as pd
        for profile,offset in (('P',0),('B',4)):
            with self.subTest(profile=profile):
                arcs=[(offset,offset+1,0.),(offset+1,offset+2,4.)]
                if offset:arcs.extend([(offset+1,1,1.),(1,2,10.)])
                graph=engine._minimum_graph(arcs,8 if offset else 4)
                original=(graph.data.copy(),graph.indices.copy(),graph.indptr.copy())
                access=pd.DataFrame([
                    {'profile':profile,'origin_id':'grid','physical_node_id':1,'entry_min':2.,'tag':'first'},
                    {'profile':profile,'origin_id':'grid','physical_node_id':0,'entry_min':2.,'tag':'second'},
                    {'profile':profile,'origin_id':'island','physical_node_id':3,'entry_min':0.,'tag':'island'}])
                if offset:
                    # Supplemental access supplies state IDs explicitly, rather
                    # than assuming they can always be derived by adding offset.
                    access['state_node_id']=[5,4,7]
                key=profile+'_disrupted'
                model={'runtime':{'scenarios':{key:{'profile':profile,'state':'disrupted','owned_offset':offset or None}}},
                       'graphs':{key:graph},'solutions':{},'reverse_paths':{},'access':access,
                       'origins':{'grid':{},'island':{}},'destinations':{
                           'd2':{'properties':{'walk_node_id':2}},'d1':{'properties':{'walk_node_id':1}}}}
                rows=engine._solve(model,key)
                grid=[r for r in rows if r['origin_id']=='grid']
                self.assertEqual([r['total'] for r in grid],[6.,2.])
                self.assertEqual([r['target'] for r in grid],[offset+2,offset+1])
                self.assertEqual([r['entry']['tag'] for r in grid],['first','first'])
                self.assertTrue(all(np.isinf(r['total']) for r in rows if r['origin_id']=='island'))
                self.assertIsNot(grid[0]['entry'],grid[1]['entry'])
                grid[0]['entry']['entry_min']=999.
                self.assertEqual(grid[1]['entry']['entry_min'],2.)
                self.assertEqual(access.iloc[0].entry_min,2.)
                for actual,expected in zip((graph.data,graph.indices,graph.indptr),original):np.testing.assert_array_equal(actual,expected)
                self.assertIn(0.,graph.data)


if __name__=='__main__':unittest.main()
