"""Synthetic activation mechanics; no researched M-line readiness claim."""
from dataclasses import replace
import copy
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
from citypilot import routing_engine as e
from citypilot.contracts import ContractError,StressFactorsNotSupported,RoutingPatch,ModelCatalog,EvaluationResult,JourneyResult
BUNDLE=Path(os.environ['CITYPILOT_TEST_BUNDLE']) if os.environ.get('CITYPILOT_TEST_BUNDLE') else None
FIXTURE=ROOT/'tests/fixtures/prebuilt_services'
PROV={'source_id':'synthetic:small-activation','status':'assumption','source':'Independent miniature service fixture',
      'evidence':'All distances, speed, dwell and headways synthetic; not M-line data.','synthetic':True}


def registry(config,data,bundle_hash):
    target=config/'prebuilt_services';target.mkdir(parents=True,exist_ok=True)
    payload=(json.dumps(data,sort_keys=True,allow_nan=False)+'\n').encode()
    (target/'assets.json').write_bytes(payload)
    manifest={'asset_version':'prebuilt-services-1','bundle_hash':bundle_hash,
              'files':{'assets.json':hashlib.sha256(payload).hexdigest()}}
    manifest['supplement_hash']=hashlib.sha256(json.dumps(manifest,sort_keys=True,separators=(',',':')).encode()).hexdigest()
    (target/'manifest.json').write_text(json.dumps(manifest),encoding='utf-8')


def small(root,*,park=False):
    import pandas as pd
    from pyproj import Transformer
    root.mkdir(parents=True,exist_ok=True);config=root.parent/'config';config.mkdir(exist_ok=True)
    xy=[(400000.,4470000.),(401000.,4470000.),(402000.,4470000.),(400000.,4470050.),(402000.,4470050.)]
    nodes=pd.DataFrame([{'node_id':i,'x':x,'y':y,'walk_active':True} for i,(x,y) in enumerate(xy)]).set_index('node_id',drop=False)
    edges=[];rows=[]
    for index,(u,v) in enumerate(((0,1),(1,2),(3,4))):
        a,b=xy[u],xy[v];length=math.dist(a,b);eid='road:'+str(index)
        edges.append({'edge_id':eid,'u':u,'v':v,'x0':a[0],'y0':a[1],'x1':b[0],'y1':b[1],
                      'length_m':length,'edge_type':'road','walk_forward':True,'walk_reverse':True,
                      'bike_forward':True,'bike_reverse':False})
        for x,y in ((u,v),(v,u)):
            rows.append({'u':x,'v':y,'time_min':length/4.788*0.06,'length_m':length,'edge_id':eid,'kind':'walk'})
    graphs={};scenarios={}
    for state in ('normal','disrupted'):
        for profile in ('P','B'):
            key=profile+'_'+state;data=copy.deepcopy(rows)
            if profile=='B':
                for row in rows:
                    new=dict(row,u=row['u']+5,v=row['v']+5,kind='ride_bike' if row['u']<row['v'] else 'push_bike')
                    if new['kind']=='ride_bike':new['time_min']=row['length_m']/15*.06
                    data.append(new)
                if park:data.append({'u':5,'v':0,'time_min':1.,'length_m':0.,'edge_id':'park','kind':'park_bike'})
            table=pd.DataFrame(data)
            for column in ('service_group_id','pattern_id','line_id','link_id'):table[column]=None
            table.to_csv(root/(key+'_arcs.csv.gz'),index=False)
            graphs[key]=e._minimum_graph([(r.u,r.v,r.time_min) for r in table.itertuples()],10 if profile=='B' else 5)
            scenarios[key]={'owned_offset':5 if profile=='B' else None,'profile':profile,'state':state}
    t=Transformer.from_crs('EPSG:32639','EPSG:4326',always_xy=True)
    coords=[tuple(t.transform(*p)) for p in xy]
    grid_xy=(400500.,4470000.);grid_coord=tuple(t.transform(*grid_xy))
    origins={'o':{'geometry':{'type':'Point','coordinates':coords[0]}},
             'origin:grid':{'geometry':{'type':'Point','coordinates':grid_coord}}}
    access=[]
    for profile in ('P','B'):
        access.append({'profile':profile,'origin_id':'o','physical_node_id':0,'entry_min':0.,'entry_walk_min':0.,'partial_edge_min':0.,'partial_edge_mode':'walk'})
        for node in (0,1):
            cycling=profile=='B' and node==1
            cost=500/(15 if cycling else 4.788)*.06
            access.append({'profile':profile,'origin_id':'origin:grid','physical_node_id':node,'entry_min':cost,'entry_walk_min':0.,'partial_edge_min':cost,
                           'partial_edge_mode':'ride_bike' if cycling else ('push_bike' if profile=='B' else 'walk')})
    model={'root':root,'config':config,'manifest':{'artifact_version':'tiny','bundle_hash':'1'*64},
        'od':{'od_version':'fixed','od_hash':'2'*64},'closure_id':'closure:test',
        'runtime':{'metric_crs':'EPSG:32639','scenarios':scenarios,'c3_parameters':{'walk_speed_kmh':4.788,'bike_speed_kmh':15.}},
        'graphs':graphs,'arc_tables':{},'solutions':{},'reverse_paths':{},'nodes':nodes,
        'edges':pd.DataFrame(edges).set_index('edge_id',drop=False),'access':pd.DataFrame(access),
        'origins':origins,'destinations':{f'd{n}':{'geometry':{'type':'Point','coordinates':coords[n]},'properties':{'walk_node_id':n}} for n in (1,2)},
        'grid':{'origin:grid':{'edge_id':'road:0','u':0,'v':1,'fraction':.5,'snap_x':grid_xy[0],'snap_y':grid_xy[1],'snap_distance_m':0.}},
        'services':pd.DataFrame(columns=['service_group_id','headway_default_min']),
        'patterns':pd.DataFrame(columns=['pattern_id']),'stops':pd.DataFrame(columns=['stop_id']),
        'bus_nodes':pd.DataFrame(columns=['node_id','pattern_id','service_group_id','route','stop_id','seq','phase']).set_index('node_id'),
        'bus_stops':pd.DataFrame(columns=['stop_id']).set_index('stop_id'),
        'metro_nodes':{s:pd.DataFrame(columns=['node_id']).set_index('node_id') for s in ('normal','disrupted')},
        'parking':pd.DataFrame(columns=['parking_id']),'stations':{},'metro_exits':pd.DataFrame(columns=['access_id']),
        'warnings':(),'provenance':e._provenance('synthetic:baseline','Synthetic miniature baseline')}
    stops=[{'stop_id':'s'+str(i),'model_node_id':i,'coordinates':coords[i],'provenance':PROV} for i in (0,1,2)]
    patterns=[]
    for pid,order,lengths in (('out',[0,1,2],[100.,200.]),('back',[2,1,0],[200.,100.])):
        patterns.append({'pattern':{'pattern_id':pid,'route_id':'synthetic','direction_id':pid,'stop_ids':['s'+str(i) for i in order],'provenance':PROV},
            'segment_m':lengths,'segment_geometry':[{'type':'LineString','coordinates':[coords[a],coords[b]]} for a,b in zip(order,order[1:])]})
    groups=[]
    for headway in (6,9):
        g={'service_group_id':'SYN'+str(headway),'pattern_ids':['out','back'],'base_headway_min':float(headway),
           'full_cycle_km':.6,'speed_kmh':30.,'stops_per_cycle':2,'dwell_s':60.,'layover_min':10.,'coverage':'full','provenance':PROV}
        g['field_status']={k:'assumption' for k in g if k not in ('service_group_id','provenance')};groups.append(g)
    return model,{'access_policy':{'max_snap_m':100.,'excessive_snap':'unreachable'},'stops':stops,'patterns':patterns,'prebuilt_services':groups}


def activate(model,*ids,profile='P',**changes):
    return replace(e.baseline_request(model,'mitigated',profile),patches=tuple(RoutingPatch(kind='activate_service',target_id=s) for s in ids),**changes)


class ActivationTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.model,self.data=small(Path(self.temp.name)/'bundle')

    def load(self,data=None):
        registry(self.model['config'],self.data if data is None else data,self.model['manifest']['bundle_hash'])
        e._load_prebuilt(self.model)

    def test_checked_in_fixture_payload_bytes_match_manifest(self):
        manifest=json.loads((FIXTURE/'manifest.json').read_text(encoding='utf-8'))
        self.assertEqual(hashlib.sha256((FIXTURE/'assets.json').read_bytes()).hexdigest(),manifest['files']['assets.json'])

    def test_inactive_catalog_separation_strict_serialization_and_identity(self):
        base=e.evaluate_package(self.model,e.baseline_request(self.model)).od_results
        old_identity=e._identity(self.model);old_ids=e.get_od_table(self.model,'P')
        self.load();catalog=e.get_catalog(self.model)
        self.assertEqual(set(catalog.prebuilt_services),{'SYN6','SYN9'});self.assertFalse(catalog.service_groups)
        self.assertEqual(ModelCatalog.from_json(catalog.to_json()),catalog)
        self.assertEqual(base,e.evaluate_package(self.model,e.baseline_request(self.model)).od_results)
        self.assertNotEqual(old_identity,e._identity(self.model));self.assertEqual(old_ids,e.get_od_table(self.model,'P'))

    def test_waits_dwell_alighting_and_design_layover_not_passenger_cost(self):
        self.load()
        for sid,wait in (('SYN6',3.),('SYN9',4.5)):
            q=activate(self.model,sid);result=e.evaluate_package(self.model,q);result.validate_request(q)
            mid=e.inspect_journey(self.model,q,'o','d1');end=e.inspect_journey(self.model,q,'o','d2')
            self.assertAlmostEqual(mid.total_min,wait+.2,places=10)
            self.assertAlmostEqual(end.total_min,wait+.2+1+.4,places=10)
            self.assertAlmostEqual(sum(l.wait_min for l in end.legs),wait)
            self.assertAlmostEqual(sum(l.total_min for l in end.legs),end.total_min)
            self.assertEqual({l.route_id for l in end.legs if l.mode=='bus'},{sid})
            self.assertEqual(JourneyResult.from_json(end.to_json()),end)
            self.assertEqual(EvaluationResult.from_json(result.to_json()),result)
            for j in (mid,end):self.assertAlmostEqual(next(r.minutes for r in result.od_results if r.od_id==j.od_id),j.total_min)

    def test_variants_distinct_order_duplicate_canonicalization_and_immutability(self):
        self.load();catalog=e.get_catalog(self.model).to_json();base={k:g.data.copy() for k,g in self.model['graphs'].items()}
        q=activate(self.model,'SYN6','SYN9');other=activate(self.model,'SYN9','SYN6','SYN6')
        self.assertEqual(q.config_hash,other.config_hash)
        scenario,key=e._scenario(self.model,q);arcs=e._arcs(scenario,key)
        for sid,wait in (('SYN6',3.),('SYN9',4.5)):
            self.assertEqual(set(arcs.loc[(arcs.kind=='bus_board')&(arcs.service_group_id==sid),'time_min']),{wait})
        self.assertEqual(len(scenario['bus_nodes']),24)
        a=e.evaluate_package(self.model,q)
        self.assertEqual(a.od_results,e.evaluate_package(self.model,other).od_results)
        for factor in (2.,.5,1.3):e.evaluate_package(self.model,activate(self.model,'SYN9',speed_factor=factor))
        self.assertEqual(catalog,e.get_catalog(self.model).to_json())
        for key,g in self.model['graphs'].items():self.assertEqual(list(base[key]),list(g.data))
        self.assertEqual(a.od_results,e.evaluate_package(self.model,q).od_results)

    def test_speed_scales_only_motion_not_wait_dwell_or_walk(self):
        self.load();base,key=e._scenario(self.model,activate(self.model,'SYN6'))
        fast,_=e._scenario(self.model,activate(self.model,'SYN6',speed_factor=2.))
        a=e._arcs(base,key);b=e._arcs(fast,key).loc[a.index]
        moving=a.kind=='bus_ride'
        self.assertEqual(list(b.loc[moving,'time_min']),list(a.loc[moving,'time_min']/2))
        self.assertEqual(list(b.loc[~moving,'time_min']),list(a.loc[~moving,'time_min']))
        j=e.inspect_journey(self.model,activate(self.model,'SYN6',speed_factor=2),'o','d2')
        self.assertAlmostEqual(j.total_min,3+.1+1+.2)

    def test_direction_partial_coverage_and_zero_motion(self):
        self.data['patterns']=self.data['patterns'][:1]
        for g in self.data['prebuilt_services']:
            g.update(pattern_ids=['out'],coverage='partial',full_cycle_km=None,stops_per_cycle=None,layover_min=None)
            for k in ('full_cycle_km','stops_per_cycle','layover_min'):g['field_status'][k]='unverified'
        self.data['patterns'][0]['segment_m']=[0.,0.]
        self.load();q=activate(self.model,'SYN6');scenario,key=e._scenario(self.model,q)
        arcs=e._arcs(scenario,key);rides=arcs.loc[arcs.kind=='bus_ride']
        self.assertEqual(set(rides.time_min),{0.});self.assertEqual(set(rides.pattern_id),{'out'})
        self.assertIsNone(e.get_catalog(self.model).prebuilt_services['SYN6'].full_cycle_km)
        self.assertAlmostEqual(e.inspect_journey(self.model,q,'o','d2').total_min,4.)
        from scipy.sparse.csgraph import dijkstra
        self.assertAlmostEqual(dijkstra(scenario['graphs'][key],directed=True,indices=2)[0],2000/4.788*.06)

    def test_bike_cannot_board_until_parking_and_never_retrieves(self):
        self.load();q=activate(self.model,'SYN6',profile='B')
        j=e.inspect_journey(self.model,q,'o','d2');self.assertFalse(any(l.mode=='bus' for l in j.legs))
        model,data=small(Path(self.temp.name)/'park_bundle',park=True)
        registry(model['config'],data,model['manifest']['bundle_hash']);e._load_prebuilt(model)
        q=activate(model,'SYN6',profile='B');j=e.inspect_journey(model,q,'o','d2')
        self.assertTrue(any(l.mode=='bus' for l in j.legs));self.assertAlmostEqual(j.total_min,1+4.6)
        scenario,key=e._scenario(model,q);arcs=e._arcs(scenario,key)
        for (u,v),arc in arcs.loc[arcs.kind=='bus_board'].iterrows():
            self.assertFalse(e._owned_node(scenario,key,u));self.assertFalse(e._owned_node(scenario,key,v))

    def test_new_stop_splits_without_endpoint_shortcut_and_grid_access_preserved(self):
        from pyproj import Transformer
        from scipy.sparse.csgraph import dijkstra
        t=Transformer.from_crs('EPSG:32639','EPSG:4326',always_xy=True)
        self.data['stops'][0].pop('model_node_id');self.data['stops'][0]['coordinates']=t.transform(400750.,4470005.)
        self.load();q=activate(self.model,'SYN6');scenario,key=e._scenario(self.model,q)
        baseline=dijkstra(self.model['graphs'][key],indices=[0,1,2],directed=True)
        # Remove bus arcs only: physical street/access distances stay identical.
        arcs=e._arcs(scenario,key).reset_index();street=arcs.loc[~arcs.kind.str.startswith('bus_')]
        graph=e._minimum_graph([(r.u,r.v,r.time_min) for r in street.itertuples()],scenario['graphs'][key].shape[0])
        updated=dijkstra(graph,indices=[0,1,2],directed=True)
        for i in range(3):
            for j in range(3):self.assertAlmostEqual(baseline[i,j],updated[i,j],places=10)
        original=self.model['access'];saved=scenario['access'].iloc[:len(original)]
        self.assertEqual(list(original.entry_min),list(saved.entry_min));self.assertEqual(list(original.physical_node_id),list(saved.physical_node_id))
        j=e.inspect_journey(self.model,q,'origin:grid','d2');result=e.evaluate_package(self.model,q)
        self.assertTrue(any(l.mode=='bus' for l in j.legs))
        self.assertAlmostEqual(j.legs[1].total_min,250/4.788*.06,places=9)
        self.assertAlmostEqual(j.total_min,next(r.minutes for r in result.od_results if r.od_id==j.od_id))
        self.assertAlmostEqual(sum(l.total_min for l in j.legs),j.total_min)
        # Splitting the same road in B preserves one-way cycling and reverse push.
        s,k=e._scenario(self.model,activate(self.model,'SYN6',profile='B'))
        for (u,v),arc in e._arcs(s,k).iterrows():
            if arc.edge_id=='road:0' and e._owned_node(s,k,u):
                a=e._node_coord(s,k,u)[0];b=e._node_coord(s,k,v)[0]
                self.assertEqual(arc.kind,'ride_bike' if b>a else 'push_bike')

    def test_excessive_snap_unreachable_and_no_component_resnap(self):
        from pyproj import Transformer
        t=Transformer.from_crs('EPSG:32639','EPSG:4326',always_xy=True)
        self.data['stops'][0].pop('model_node_id');self.data['stops'][0]['coordinates']=t.transform(400750.,4470049.)
        self.load();stop=self.model['prebuilt_stops']['s0']
        self.assertEqual(stop['attachment'][0],'road:2') # nearest disconnected road, not the main road
        from scipy.sparse.csgraph import dijkstra
        scenario,key=e._scenario(self.model,activate(self.model,'SYN6'))
        arcs=e._arcs(scenario,key).reset_index()
        street=arcs.loc[~arcs.kind.str.startswith('bus_')]
        graph=e._minimum_graph([(r.u,r.v,r.time_min) for r in street.itertuples()],scenario['graphs'][key].shape[0])
        self.assertTrue(math.isinf(dijkstra(graph,directed=True,indices=0)[3]))
        self.data['access_policy']['max_snap_m']=.1;self.load()
        self.assertEqual(self.model['prebuilt_stops']['s0']['status'],'snap_failed')
        self.assertIn('PREBUILT_STOP_UNREACHABLE:s0',self.model['warnings'])

    def test_missing_geometry_disclosed_as_gaps_not_fabricated_connectors(self):
        self.data['patterns'][0]['segment_geometry']=[None,None];self.load()
        j=e.inspect_journey(self.model,activate(self.model,'SYN6'),'o','d2')
        self.assertTrue(j.geometry_metadata.partial);self.assertIn('GEOMETRY_GAPS',j.warnings)
        self.assertIn('PREBUILT_GEOMETRY_MISSING:out',j.warnings)
        self.assertEqual(JourneyResult.from_json(j.to_json()),j)
        for leg in j.legs:
            if leg.mode=='bus' and leg.geometry.type=='MultiLineString':
                self.assertTrue(all(line[0]==line[-1] for line in leg.geometry.coordinates))

    def test_invalid_assets_and_unsupported_requests_fail_clearly(self):
        cases=[]
        for mutate in (lambda d:d['patterns'][0].pop('segment_m'),
                       lambda d:d['patterns'][0]['segment_m'].__setitem__(0,-1),
                       lambda d:d['patterns'][0]['segment_m'].__setitem__(0,10**500),
                       lambda d:d['patterns'][0]['pattern']['stop_ids'].__setitem__(0,'unknown'),
                       lambda d:d['prebuilt_services'][0].__setitem__('speed_kmh',0),
                       lambda d:d['prebuilt_services'][0].__setitem__('full_cycle_km',1),
                       lambda d:d['prebuilt_services'][0].__setitem__('stops_per_cycle',3),
                       lambda d:d['prebuilt_services'][0]['field_status'].__setitem__('speed_kmh','observed'),
                       lambda d:d['stops'][0].__setitem__('coordinates',[200,40]),
                       lambda d:d['stops'][0].__setitem__('model_node_id',999)):
            data=copy.deepcopy(self.data);mutate(data);cases.append(data)
        for data in cases:
            with self.subTest(data=data),self.assertRaises(ContractError):self.load(data)
        self.load()
        with self.assertRaisesRegex(ContractError,'Unknown prebuilt'):e.evaluate_package(self.model,activate(self.model,'M9'))
        for kind in ('activate_link','enable_parking'):
            q=replace(activate(self.model,profile='B'),patches=(RoutingPatch(kind=kind,target_id='x'),))
            with self.assertRaisesRegex(StressFactorsNotSupported,'unsupported patch'):e.evaluate_package(self.model,q)
        with self.assertRaisesRegex(ContractError,'Patches require mitigated'):replace(activate(self.model,'SYN6'),state='disrupted')

    def test_corrupt_supplement_and_semantic_changes_invalidate_identity(self):
        self.load();old=e._identity(self.model);q=activate(self.model,'SYN6');e.evaluate_package(self.model,q)
        target=self.model['config']/'prebuilt_services/assets.json'
        target.write_bytes(target.read_bytes()+b' ')
        with self.assertRaisesRegex(ContractError,'payload hash'):e._load_prebuilt(self.model)
        self.data['prebuilt_services'][0]['base_headway_min']=7.;self.load()
        self.assertNotEqual(old,e._identity(self.model))
        with self.assertRaisesRegex(ContractError,'identity mismatch'):e.evaluate_package(self.model,q)
        self.assertAlmostEqual(e.inspect_journey(self.model,activate(self.model,'SYN6'),'o','d2').total_min,5.1)

    def test_existing_stop_reference_keeps_coordinate_and_catalog_id(self):
        import pandas as pd
        self.model['stops']=pd.DataFrame([{'stop_id':'s0'}])
        self.model['bus_stops']=pd.DataFrame([{'stop_id':'s0','node_id':0,'source_x':400000.,'source_y':4470000.}]).set_index('stop_id')
        self.data['stops'][0].pop('model_node_id');self.data['stops'][0]['model_stop_id']='s0'
        self.load();catalog=e.get_catalog(self.model)
        self.assertEqual(catalog.stop_ids.count('s0'),1)
        self.assertEqual(self.model['prebuilt_stops']['s0']['status'],'existing_stop')
        self.assertAlmostEqual(e.inspect_journey(self.model,activate(self.model,'SYN6'),'o','d2').total_min,4.6)

    def test_station_exit_proxy_is_explicit_assumption_and_preserved_in_journey(self):
        stop=self.data['stops'][0]
        stop['location_kind']='station_exit_proxy'
        stop['provenance']=dict(PROV,source_id='synthetic:station-exit-proxy',
            evidence='Synthetic station-exit proxy for future schema verification; not verified bus-stop coordinates.')
        self.load()
        self.assertEqual(self.model['prebuilt_stops']['s0']['location_kind'],'station_exit_proxy')
        self.assertIn('PREBUILT_STATION_EXIT_PROXY:s0',self.model['warnings'])
        catalog=e.get_catalog(self.model)
        self.assertEqual(next(p.status for p in catalog.sources if p.source_id=='synthetic:station-exit-proxy'),'assumption')
        j=e.inspect_journey(self.model,activate(self.model,'SYN6'),'o','d2')
        self.assertIn('PREBUILT_STATION_EXIT_PROXY:s0',j.warnings)
        self.assertTrue(any(p.source_id=='synthetic:station-exit-proxy' and p.status=='assumption'
                            for leg in j.legs for p in leg.provenance))
        self.assertEqual(JourneyResult.from_json(j.to_json()),j)
        self.assertAlmostEqual(j.total_min,4.6)
        for status in ('published','curated','observed','modelled','unverified'):
            stop['provenance']=dict(stop['provenance'],synthetic=False,status=status)
            with self.subTest(status=status),self.assertRaisesRegex(ContractError,'proxies require assumption'):
                self.load()
        stop['provenance']=dict(stop['provenance'],status='assumption')
        stop['location_kind']='unlabelled_proxy'
        with self.assertRaisesRegex(ContractError,'location_kind'):self.load()

    def test_ali_package_states_shared_capability_error_and_result_schema(self):
        self.load()
        self.assertTrue(issubclass(StressFactorsNotSupported,NotImplementedError))
        self.assertFalse(issubclass(StressFactorsNotSupported,ContractError))
        baseline=e.baseline_request(self.model,'disrupted')
        self.assertEqual((baseline.state,baseline.closure_id,baseline.patches),('disrupted','closure:test',()))
        result=e.evaluate_package(self.model,baseline)
        empty_mitigated=replace(baseline,state='mitigated')
        self.assertEqual(result.od_results,e.evaluate_package(self.model,empty_mitigated).od_results)
        action=replace(baseline,state='mitigated',patches=(RoutingPatch(kind='activate_service',target_id='SYN6'),))
        self.assertEqual(action.closure_id,baseline.closure_id)
        self.assertAlmostEqual(e.inspect_journey(self.model,action,'o','d2').total_min,4.6)
        traced=replace(baseline,candidate_ids=('decision:trace',))
        payload=e.evaluate_package(self.model,traced).to_dict()
        self.assertNotIn('candidate_ids',payload)
        with self.assertRaisesRegex(ContractError,'Unknown fields'):
            EvaluationResult.from_dict(dict(payload,candidate_ids=[]))
        bad=replace(action,profile='B',patches=(RoutingPatch(kind='enable_parking',target_id='future'),))
        with self.assertRaises(StressFactorsNotSupported):e.evaluate_package(self.model,bad)
        # Malformed factors/IDs still fail validation before capability selection.
        with self.assertRaises(ContractError):e.evaluate_package(self.model,replace(bad,headway_factor_by_group={'unknown':1.}))
        with self.assertRaises(ContractError):RoutingPatch(kind='unknown_kind',target_id='x')

    def test_manifest_hash_binding_and_exact_endpoint_new_stop(self):
        self.load();path=self.model['config']/'prebuilt_services/manifest.json'
        for field in ('supplement_hash','bundle_hash'):
            manifest=json.loads(path.read_text());manifest[field]='0'*64;path.write_text(json.dumps(manifest))
            with self.assertRaisesRegex(ContractError,'hash|bundle'):e._load_prebuilt(self.model)
            self.load()
        # New coordinate exactly at a street endpoint must attach to that endpoint,
        # without a new bypass arc or positive displacement.
        self.data['stops'][0].pop('model_node_id');self.load()
        stop=self.model['prebuilt_stops']['s0'];self.assertEqual(stop['fraction'],0.)
        scenario,key=e._scenario(self.model,activate(self.model,'SYN6'))
        arcs=e._arcs(scenario,key);links=arcs.loc[arcs.edge_id=='prebuilt:access:s0']
        self.assertTrue(all(min(u,v)==0 for u,v in links.index))
        self.assertLess(max(links.time_min),1e-7)

    def test_opaque_ids_do_not_alias_service_geometry_or_arc_provenance(self):
        self.data['patterns']=[]
        for pid,length in (('c',100.),('b:c',200.)):
            self.data['patterns'].append({'pattern':{'pattern_id':pid,'route_id':'opaque','direction_id':pid,
                'stop_ids':['s0','s1','s0'],'provenance':PROV},'segment_m':[length,length],
                'segment_geometry':[{'type':'Point','coordinates':self.data['stops'][0]['coordinates']}]*2})
        for group,sid,pid,length in zip(self.data['prebuilt_services'],('a:b','a'),('c','b:c'),(100.,200.)):
            group.update(service_group_id=sid,pattern_ids=[pid],full_cycle_km=length*2/1000,stops_per_cycle=1)
        self.load();scenario,key=e._scenario(self.model,activate(self.model,'a:b','a'))
        rides=e._arcs(scenario,key).loc[lambda a:a.kind=='bus_ride']
        self.assertEqual(len(rides),4);self.assertEqual(len(set(rides.edge_id)),4)
        self.assertEqual(len(scenario['prebuilt_geometry']),4)

    def test_zero_partial_access_at_grid_snap_ignores_nontravel_direction(self):
        import pandas as pd
        edge=self.model['edges'].loc['road:0'];self.model['edges'].loc['road:0','walk_forward']=False
        # Only reverse pedestrian travel exists on this road. At the origin's
        # exact snap, reaching a co-located new stop requires no directed travel.
        for key in ('P_normal','P_disrupted'):
            table=e._raw_arcs(self.model,key)
            table=table.loc[~((table.u==0)&(table.v==1))]
            table.to_csv(self.model['root']/(key+'_arcs.csv.gz'),index=False)
            self.model['graphs'][key]=e._minimum_graph([(r.u,r.v,r.time_min) for r in table.itertuples()],5)
        access=self.model['access']
        self.model['access']=access.loc[~((access.origin_id=='origin:grid')&(access.profile=='P')&(access.physical_node_id==1))].copy()
        self.data['stops'][0].pop('model_node_id')
        self.data['stops'][0]['coordinates']=self.model['origins']['origin:grid']['geometry']['coordinates']
        self.load();j=e.inspect_journey(self.model,activate(self.model,'SYN6'),'origin:grid','d2')
        self.assertAlmostEqual(j.legs[1].total_min,0.,places=9)
        self.assertAlmostEqual(j.total_min,4.6,places=8)


@unittest.skipUnless(BUNDLE,'Set CITYPILOT_TEST_BUNDLE')
class RealActivationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp=tempfile.TemporaryDirectory();cls.addClassCleanup(cls.temp.cleanup)
        config=Path(cls.temp.name)/'config';shutil.copytree(BUNDLE/'config',config)
        shutil.copytree(FIXTURE,config/'prebuilt_services')
        cls.model=e.load_model(BUNDLE,config);cls.config=config

    def test_inactive_registration_all_10872_rows_and_counts(self):
        import pandas as pd
        expected={'P_normal':(2060,2339,2496),'P_disrupted':(636,1191,1697),
                  'B_normal':(2406,2506,2511),'B_disrupted':(2406,2506,2511)}
        for key,counts in expected.items():
            profile,state=key.split('_');result=e.evaluate_package(self.model,e.baseline_request(self.model,state,profile))
            saved=pd.read_csv(BUNDLE/'od'/('times_'+key+'.csv.gz')).set_index(['origin_id','destination_id'])
            for row,ref in zip(result.od_results,e.get_od_table(self.model,profile)):
                reference=saved.loc[(ref.origin_id,ref.destination_id)]
                self.assertEqual(row.status,reference.status)
                if row.minutes is not None:self.assertAlmostEqual(row.minutes,reference.total_min,delta=1e-6)
                self.assertAlmostEqual(row.capped_minutes,reference.capped_min,delta=1e-6)
            self.assertEqual(tuple(result.within_counts.values()),counts)
            self.assertAlmostEqual(result.capped_time_sum,saved.capped_min.sum(),delta=1e-6)

    def test_real_activation_journey_grid_stress_and_catalog(self):
        model=self.model;catalog=e.get_catalog(model)
        self.assertEqual(set(catalog.service_groups),{'SG_R2','SG_R14'})
        self.assertEqual(set(catalog.prebuilt_services),{'SYN_INS_28_6','SYN_INS_28_9'})
        node=model['nodes'].loc[118425]
        origin=min(model['grid'],key=lambda oid:(model['grid'][oid]['snap_x']-node.x)**2+(model['grid'][oid]['snap_y']-node.y)**2)
        destination=next(d for d,f in model['destinations'].items() if f['properties']['walk_node_id']==118435)
        q=activate(model,'SYN_INS_28_6',headway_factor_by_group={'SG_R2':1.2,'SG_R14':1.1})
        result=e.evaluate_package(model,q);j=e.inspect_journey(model,q,origin,destination)
        self.assertTrue(any(l.route_id=='SYN_INS_28_6' for l in j.legs))
        self.assertEqual(JourneyResult.from_json(j.to_json()),j)
        self.assertAlmostEqual(j.total_min,next(r.minutes for r in result.od_results if r.od_id==j.od_id),delta=1e-6)
        self.assertAlmostEqual(sum(l.total_min for l in j.legs),j.total_min,delta=1e-6)
        scenario,key=e._scenario(model,q);arcs=e._arcs(scenario,key)
        self.assertEqual(set(arcs.loc[(arcs.kind=='bus_board')&(arcs.service_group_id=='SYN_INS_28_6'),'time_min']),{3.})
        self.assertEqual(set(arcs.loc[(arcs.kind=='bus_board')&(arcs.service_group_id=='SG_R2'),'time_min']),{4.5})
        terminal=e.inspect_journey(model,q,'origin:terminal:baku_international',destination)
        self.assertAlmostEqual(sum(l.total_min for l in terminal.legs),terminal.total_min,delta=1e-6)
        print('SYNTHETIC_REAL_RESULT',json.dumps({'within_counts':dict(result.within_counts),'capped_sum':result.capped_time_sum,
            'duration_ms':result.duration_ms,'grid_origin':origin,'destination':destination,'journey_min':j.total_min,'terminal_min':terminal.total_min}))

    def test_clean_process_load_catalog_evaluate_journey_and_export_parity(self):
        code=f'''
import sys,json
from pathlib import Path
from dataclasses import replace
sys.path.insert(0,{str(ROOT/'src')!r})
from citypilot import routing_engine as e
from citypilot.contracts import RoutingPatch,ModelCatalog,EvaluationResult,JourneyResult
assert not any(n.startswith(('IPython','jupyter','numpy','pandas')) for n in sys.modules)
m=e.load_model(Path({str(BUNDLE)!r}),Path({str(self.config)!r}))
q=replace(e.baseline_request(m,'mitigated'),patches=(RoutingPatch(kind='activate_service',target_id='SYN_INS_28_6'),))
r=e.evaluate_package(m,q);j=e.inspect_journey(m,q,'origin:terminal:baku_international',next(iter(m['destinations'])))
for x in (e.get_catalog(m),q,r,j):assert type(x).from_json(x.to_json())==x
n=json.loads(Path({str(ROOT/'notebooks/01_network_routing.ipynb')!r}).read_text(encoding='utf-8'))
source='\\n\\n'.join(''.join(c['source']) for c in n['cells'] if 'routing_export' in c.get('metadata',{{}}).get('tags',[]))
scope={{}};exec(compile(source,'<definitions-only>','exec'),scope)
a=scope['evaluate_package'](m,q).to_dict();b=r.to_dict();a.pop('duration_ms');b.pop('duration_ms');assert a==b
assert scope['inspect_journey'](m,q,j.origin_id,j.destination_id)==j
assert not any(n.startswith(('IPython','jupyter','http.server')) for n in sys.modules)
print('clean activation process and tagged export parity OK')
'''
        result=subprocess.run([sys.executable,'-I','-X','utf8','-c',code],capture_output=True,text=True)
        self.assertEqual(result.returncode,0,result.stderr);self.assertIn('clean activation process',result.stdout)

    def test_real_bike_and_combined_existing_patch_interaction(self):
        model=self.model
        patches=(RoutingPatch(kind='activate_service',target_id='SYN_INS_28_6'),
                 RoutingPatch(kind='activate_service',target_id='SYN_INS_28_9'),
                 RoutingPatch(kind='set_service_headway',target_id='SG_R2',headway_min=7.2))
        q=replace(e.baseline_request(model,'mitigated'),patches=patches,speed_factor=1.25,
                  headway_factor_by_group={'SG_R2':1.2,'SG_R14':1.1})
        self.assertEqual(q.config_hash,replace(q,patches=tuple(reversed(patches))*2).config_hash)
        scenario,key=e._scenario(model,q);arcs=e._arcs(scenario,key)
        for sid,wait in (('SG_R2',3.6),('SYN_INS_28_6',3.),('SYN_INS_28_9',4.5)):
            self.assertEqual(set(arcs.loc[(arcs.kind=='bus_board')&(arcs.service_group_id==sid),'time_min']),{wait})
        catalog=e.get_catalog(model).to_json()
        for profile in ('P','B'):
            request=replace(q,profile=profile);result=e.evaluate_package(model,request)
            for origin in ('origin:grid:32639:1328:14906','origin:terminal:baku_international'):
                j=e.inspect_journey(model,request,origin,'destination:metro_exit:44')
                self.assertEqual(JourneyResult.from_json(j.to_json()),j)
                self.assertAlmostEqual(sum(l.total_min for l in j.legs),j.total_min,delta=1e-6)
                self.assertAlmostEqual(j.total_min,next(r.minutes for r in result.od_results if r.od_id==j.od_id),delta=1e-6)
            self.assertEqual(catalog,e.get_catalog(model).to_json())
            print('SYNTHETIC_COMBINED_RESULT',profile,json.dumps({'within_counts':dict(result.within_counts),
                'capped_sum':result.capped_time_sum,'duration_ms':result.duration_ms}))


if __name__=='__main__':unittest.main()
