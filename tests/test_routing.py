"""Strict shared v1 serialization, evidence, statuses and geometry validation."""
import json
import math
from dataclasses import replace
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'src'))
from citypilot.contracts import (CONTRACT_VERSION,ContractError,RoutingRequest,RoutingPatch,
    JourneyResult,EvaluationResult,ModelCatalog,LineString,MultiLineString,Point,GeometryMetadata,Parking)
from citypilot import routing_engine as engine
from c1_examples import examples


class ContractsTests(unittest.TestCase):
    def setUp(self):self.request,self.catalog,self.evaluation,self.journey=examples()

    def test_round_trip_all_shared_contracts_and_examples(self):
        self.assertEqual(CONTRACT_VERSION,'1.0')
        for name,value in zip(('request','catalog','evaluation','journey'),examples()):
            with self.subTest(name=name):
                self.assertEqual(value,type(value).from_json(value.to_json()))
                self.assertEqual(value.to_json(),type(value).from_dict(value.to_dict()).to_json())
                raw=(ROOT/'docs/examples'/('synthetic_'+name+'.json')).read_text(encoding='utf-8')
                self.assertEqual(type(value).from_json(raw),value)
        self.catalog.validate_request(self.request)
        self.evaluation.validate_request(self.request);self.journey.validate_request(self.request)

    def test_invalid_headways_and_nonfinite_nested_json(self):
        for value in (0,-1,True,'10',None,math.nan,math.inf,-math.inf,10**1000):
            with self.subTest(value=str(value)),self.assertRaises(ContractError):
                RoutingPatch(kind='set_service_headway',target_id='x',headway_min=value)
        for constant in ('NaN','Infinity','-Infinity','1e999'):
            raw=self.request.to_json().replace('"speed_factor":0.9','"speed_factor":'+constant)
            with self.subTest(constant=constant),self.assertRaises(ContractError):RoutingRequest.from_json(raw)
        raw=self.request.to_dict();raw['headway_factor_by_group']['synthetic:existing']=float('nan')
        with self.assertRaises(ContractError):RoutingRequest.from_dict(raw)
        with self.assertRaises(ContractError):replace(self.request,headway_factor_by_group={'x':0})
        with self.assertRaises(ContractError):RoutingPatch(kind='activate_link',target_id='x',headway_min=7)

    def test_explicit_v1_unknown_fields_and_strict_types(self):
        for value in examples():
            data=value.to_dict()
            for version in (None,'0.1.0-draft','future'):
                bad=dict(data)
                if version is None:bad.pop('contract_version')
                else:bad['contract_version']=version
                with self.subTest(model=type(value).__name__,version=version),self.assertRaises(ContractError):
                    type(value).from_dict(bad)
        for name,value in [('assumptions',[]),('model_hash','0'*64),('threshold_min',45),('extra',False)]:
            with self.subTest(field=name),self.assertRaises(ContractError):RoutingRequest.from_dict(dict(self.request.to_dict(),**{name:value}))
        with self.assertRaises(ContractError):RoutingRequest.from_json('{"state":"normal","state":"disrupted"}')
        for changes in ({'profile':'X'},{'state':'closed'},{'cap_min':40},{'speed_factor':True},
                        {'thresholds_min':(40.0,45,50)},{'thresholds_min':(40,45,45)},
                        {'primary_t_min':42},{'closure_id':None}):
            with self.subTest(changes=changes),self.assertRaises(ContractError):replace(self.request,**changes)

    def test_patch_order_exact_headway_and_identity(self):
        self.assertEqual(replace(self.request,patches=tuple(reversed(self.request.patches))),self.request)
        self.assertEqual(replace(self.request,patches=self.request.patches*2).config_hash,self.request.config_hash)
        patch=next(p for p in self.request.patches if p.kind=='set_service_headway')
        self.assertEqual(patch.headway_min,7.2)
        with self.assertRaises(ContractError):replace(self.request,patches=(*self.request.patches,replace(patch,headway_min=7)))
        for changes in ({'primary_t_min':40},{'cap_min':121},{'speed_factor':0.8},
                        {'candidate_ids':()},{'headway_factor_by_group':None},{'patches':()},
                        {'model_version':'other'},{'od_set_id':'other'},{'profile':'P','patches':()},
                        {'closure_id':'other'}):
            self.assertNotEqual(replace(self.request,**changes).config_hash,self.request.config_hash)

    def test_states_closures_and_profiles(self):
        for state in ('normal','disrupted','mitigated'):
            for profile in ('P','B'):
                value=replace(self.request,state=state,profile=profile,patches=(),
                    closure_id=None if state=='normal' else 'synthetic:closure')
                self.catalog.validate_request(value)
        for changes in ({'profile':'P'},{'state':'normal'},{'state':'disrupted'}):
            with self.assertRaises(ContractError):replace(self.request,**changes)
        with self.assertRaises(ContractError):self.catalog.validate_request(replace(self.request,closure_id='wrong'))

    def test_separate_service_maps_statuses_parking_and_partial(self):
        self.assertFalse(set(self.catalog.service_groups)&set(self.catalog.prebuilt_services))
        self.assertFalse(self.catalog.parking['synthetic:parking'].baseline_enabled)
        for kind in ('activate_service','activate_link','enable_parking','set_service_headway'):
            patch=RoutingPatch(kind=kind,target_id='missing',headway_min=6 if kind=='set_service_headway' else None)
            with self.assertRaises(ContractError):self.catalog.validate_request(replace(self.request,patches=(patch,)))
        with self.assertRaises(ContractError):
            self.catalog.validate_request(replace(self.request,headway_factor_by_group={'synthetic:prebuilt':1.2}))
        service=self.catalog.service_groups['synthetic:existing']
        with self.assertRaises(ContractError):replace(service,field_status={**service.field_status,'speed_kmh':'assumed'})
        with self.assertRaises(ContractError):replace(service,field_status={})
        with self.assertRaises(ContractError):replace(service,speed_kmh=None)
        with self.assertRaises(ContractError):replace(service,coverage='partial',speed_kmh=None)
        partial=replace(service,coverage='partial',speed_kmh=None,field_status={**service.field_status,'speed_kmh':'unverified'})
        self.assertIsNone(partial.speed_kmh)
        with self.assertRaises(ContractError):replace(self.catalog,prebuilt_services={'synthetic:existing':service})
        with self.assertRaises(ContractError):replace(self.catalog,service_groups={'wrong':service})
        with self.assertRaises(ContractError):replace(service.provenance,status='observed')
        with self.assertRaises(ContractError):replace(self.catalog.parking['synthetic:parking'],baseline_enabled=1)

    def test_statuses_capped_sums_counts_and_echo_validation(self):
        self.assertEqual([r.status for r in self.evaluation.od_results],['reachable','over_cap','no_path'])
        self.assertEqual([r.capped_minutes for r in self.evaluation.od_results],[30,120,120])
        self.assertEqual(self.evaluation.od_results[1].minutes,130)
        for changes in ({'capped_time_sum':20},{'od_results':()},{'within_counts':{40:2,45:1,50:1}},
                        {'duration_ms':-1},{'within_counts':{40:1,50:1}},{'cap_min':140}):
            with self.subTest(changes=changes),self.assertRaises(ContractError):replace(self.evaluation,**changes)
        for row in self.evaluation.od_results:
            with self.assertRaises(ContractError):replace(row,minutes=None if row.minutes is not None else 0)
        bad=replace(self.evaluation.od_results[1],capped_minutes=130)
        with self.assertRaises(ContractError):replace(self.evaluation,od_results=(self.evaluation.od_results[0],bad,self.evaluation.od_results[2]))
        with self.assertRaises(ContractError):self.evaluation.validate_request(replace(self.request,primary_t_min=50))
        raw=self.evaluation.to_dict();raw['within_counts']['040']=raw['within_counts'].pop('40')
        with self.assertRaises(ContractError):EvaluationResult.from_dict(raw)

    def test_no_path_over_cap_point_and_gapped_shared_journeys(self):
        j=self.journey
        no_path=replace(j,status='no_path',total_min=None,legs=(),geometry=None)
        over_cap=replace(j,status='over_cap',total_min=130,legs=(replace(j.legs[0],walk_min=130),))
        point=Point(coordinates=(49.8,40.4))
        zero=replace(j,total_min=0,geometry=point,legs=(replace(j.legs[0],geometry=point,walk_min=0),))
        second=replace(j.legs[0],from_id='synthetic:middle',geometry=LineString(coordinates=((49.9,40.5),(49.91,40.51))),walk_min=10)
        first=replace(j.legs[0],to_id='synthetic:middle',walk_min=20)
        geometry,metadata=engine._assemble_geometry((first,second),j.provenance[0])
        gapped=replace(j,geometry=geometry,geometry_metadata=metadata,legs=(first,second),warnings=('GEOMETRY_GAPS',))
        self.assertEqual(geometry.type,'MultiLineString');self.assertEqual(metadata.gap_count,1)
        self.assertEqual(geometry.coordinates,(first.geometry.coordinates,second.geometry.coordinates))
        for value in (no_path,over_cap,zero,gapped):self.assertEqual(JourneyResult.from_json(value.to_json()),value)
        for changes in ({'total_min':31},{'geometry':None},{'status':'no_path','total_min':None}):
            with self.assertRaises(ContractError):replace(j,**changes)
        with self.assertRaises(ContractError):replace(gapped,warnings=())
        with self.assertRaises(ContractError):replace(gapped,geometry_metadata=j.geometry_metadata)
        with self.assertRaises(ContractError):replace(no_path,geometry=point)
        with self.assertRaises(ContractError):LineString(coordinates=((181,40),(49,40)))
        with self.assertRaises(ContractError):Point.from_dict({'coordinates':[49,40]})
        with self.assertRaises(ContractError):MultiLineString(coordinates=(((49,40),),))

    def test_clean_python_imports_and_invalid_adapter_inputs(self):
        script=f'''
import sys
sys.path.insert(0,{str(ROOT/'src')!r})
from citypilot import routing_engine as r
from citypilot.contracts import ContractError, CONTRACT_VERSION
assert CONTRACT_VERSION=='1.0'
for function,args in ((r.load_model,('missing','missing')),(r.get_catalog,(None,)),(r.evaluate_package,(None,None)),(r.inspect_journey,(None,None,'a','b'))):
    try: function(*args)
    except ContractError: pass
    else: raise AssertionError(function.__name__)
assert 'citypilot.decision_engine' not in sys.modules
assert not any(n.startswith(('IPython','matplotlib','numpy')) for n in sys.modules)
print('clean imports and four invalid adapter inputs OK')
'''
        with tempfile.TemporaryDirectory() as temp:run=subprocess.run([sys.executable,'-I','-c',script],cwd=temp,text=True,capture_output=True)
        self.assertEqual(run.returncode,0,run.stderr)


if __name__=='__main__':unittest.main()
