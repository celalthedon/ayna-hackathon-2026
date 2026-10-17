"""CityPilot shared wire contract 1.0. No legacy payload inference or routing logic."""
from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, fields
import hashlib
import json
import math
from types import MappingProxyType, UnionType
from typing import Any, Literal, Union, get_args, get_origin, get_type_hints

CONTRACT_VERSION = '1.0'
Profile = Literal['P','B']
State = Literal['normal','disrupted','mitigated']
PathStatus = Literal['reachable','over_cap','no_path']
EvidenceStatus = Literal['observed','published','curated','modelled','assumption','unverified']
Mode = Literal['walk','bike','bus','metro','transfer']


class ContractError(ValueError):
    """Invalid or incompatible versioned payload."""


def _require(condition, message):
    if not condition:
        raise ContractError(message)


def _id(value, name='ID'):
    _require(type(value) is str and bool(value.strip()) and value==value.strip(), f'{name}: nonempty stable ID required')


def _number(value, name, positive=False):
    try:
        finite=type(value) in (int,float) and math.isfinite(value)
    except OverflowError:
        finite=False
    _require(finite and (value>0 if positive else value>=0), f'{name}: finite {"positive" if positive else "nonnegative"} number required')


def _hash(value):
    _require(type(value) is str and len(value)==64 and all(c in '0123456789abcdef' for c in value), 'Expected lowercase SHA-256')


def _unique(values,name):
    _require(len(values)==len(set(values)), name+': duplicates')


def _decode(annotation,value,path):
    origin,args=get_origin(annotation),get_args(annotation)
    if origin in (Union,UnionType):
        for option in args:
            try:return _decode(option,value,path)
            except ContractError:pass
        raise ContractError(path+': no matching typed variant')
    if origin is Literal:
        _require(any(type(value) is type(v) and value==v for v in args), path+': invalid literal')
        return value
    if origin is tuple:
        _require(type(value) in (tuple,list), path+': expected array')
        if len(args)==2 and args[1] is Ellipsis:
            return tuple(_decode(args[0],v,f'{path}[{i}]') for i,v in enumerate(value))
        _require(len(value)==len(args),path+': wrong coordinate/array length')
        return tuple(_decode(t,v,path) for t,v in zip(args,value))
    if origin is Mapping:
        _require(isinstance(value,Mapping),path+': expected object mapping')
        result={}
        for key,item in value.items():
            # JSON object keys are strings; only canonical integer strings are
            # accepted for the explicitly typed within_counts map.
            if args[0] is int and type(key) is str:
                _require(key.isdecimal() and str(int(key))==key,path+': noncanonical integer key')
                key=int(key)
            key=_decode(args[0],key,path+'.key')
            _require(key not in result,path+': duplicate mapping key')
            result[key]=_decode(args[1],item,path+'.'+str(key))
        return MappingProxyType(result)
    if isinstance(annotation,type) and issubclass(annotation,JsonContract):
        if type(value) is annotation:
            value.__post_init__();return value
        _require(type(value) is dict,path+': expected typed object')
        return annotation.from_dict(value)
    if annotation is float:
        try:valid=type(value) in (int,float) and math.isfinite(value)
        except OverflowError:valid=False
        _require(valid,path+': finite number required');return float(value)
    _require(type(value) is annotation,path+': wrong type')
    return value


def _wire(value):
    if isinstance(value,JsonContract):return {f.name:_wire(getattr(value,f.name)) for f in fields(value)}
    if isinstance(value,Mapping):return {str(k):_wire(v) for k,v in value.items()}
    if isinstance(value,tuple):return [_wire(v) for v in value]
    return value


def _object(pairs):
    result={}
    for key,value in pairs:
        _require(key not in result,'Duplicate JSON key: '+key);result[key]=value
    return result


def _constant(value):
    raise ContractError('Non-finite JSON: '+value)


@dataclass(frozen=True,kw_only=True)
class JsonContract:
    def __post_init__(self):
        hints=get_type_hints(type(self))
        for field in fields(self):
            object.__setattr__(self,field.name,_decode(hints[field.name],getattr(self,field.name),field.name))
        self._validate()

    def _validate(self):pass

    def to_dict(self):
        self.__post_init__();return _wire(self)

    def to_json(self):
        return json.dumps(self.to_dict(),sort_keys=True,ensure_ascii=False,separators=(',',':'),allow_nan=False)

    def content_hash(self):return hashlib.sha256(self.to_json().encode('utf-8')).hexdigest()

    @classmethod
    def from_dict(cls,value):
        _require(type(value) is dict,'Expected object')
        if issubclass(cls,Versioned):
            _require(value.get('contract_version')==CONTRACT_VERSION,'Explicit contract_version=1.0 required; legacy payloads rejected')
        if cls.__name__ in ('LineString','MultiLineString','Point'):
            _require('type' in value,'Explicit GeoJSON type required')
        _require(set(value)<={f.name for f in fields(cls)},'Unknown fields: '+str(sorted(set(value)-{f.name for f in fields(cls)})))
        try:return cls(**value)
        except TypeError as exc:raise ContractError(str(exc)) from exc

    @classmethod
    def from_json(cls,value):
        try:return cls.from_dict(json.loads(value,parse_constant=_constant,object_pairs_hook=_object))
        except (json.JSONDecodeError,TypeError) as exc:raise ContractError(str(exc)) from exc


@dataclass(frozen=True,kw_only=True)
class Versioned(JsonContract):
    model_version: str
    od_set_id: str
    contract_version: str = CONTRACT_VERSION

    def _validate(self):
        _require(self.contract_version==CONTRACT_VERSION,'Unsupported contract version')
        _id(self.model_version,'model_version');_id(self.od_set_id,'od_set_id')


@dataclass(frozen=True,kw_only=True)
class Provenance(JsonContract):
    source_id: str
    status: EvidenceStatus
    source: str
    evidence: str
    source_date: str | None = None
    synthetic: bool = False

    def _validate(self):
        for name in ('source_id','source','evidence'):_id(getattr(self,name),name)
        _require(not self.synthetic or self.status=='assumption','Synthetic evidence must remain assumption')


@dataclass(frozen=True,kw_only=True)
class RoutingPatch(JsonContract):
    kind: Literal['set_service_headway','activate_service','activate_link','enable_parking']
    target_id: str
    headway_min: float | None = None

    def _validate(self):
        _id(self.target_id,'target_id')
        if self.kind=='set_service_headway':_number(self.headway_min,'headway_min',True)
        else:_require(self.headway_min is None,'Only set_service_headway accepts headway_min')


@dataclass(frozen=True,kw_only=True)
class RoutingRequest(Versioned):
    state: State
    profile: Profile
    closure_id: str | None = None
    patches: tuple[RoutingPatch,...] = ()
    speed_factor: float = 1.0
    headway_factor_by_group: Mapping[str,float] | None = None
    thresholds_min: tuple[int,...] = (40,45,50)
    primary_t_min: int = 45
    cap_min: float = 120.0
    candidate_ids: tuple[str,...] = ()

    def _validate(self):
        super()._validate()
        if self.closure_id is not None:_id(self.closure_id,'closure_id')
        _require((self.state=='normal')==(self.closure_id is None),'normal requires null closure; disrupted/mitigated require declared closure')
        _require(self.state=='mitigated' or not self.patches,'Patches require mitigated state')
        _number(self.speed_factor,'speed_factor',True);_number(self.cap_min,'cap_min',True)
        _require(bool(self.thresholds_min),'Empty thresholds')
        for threshold in self.thresholds_min:_require(0<threshold<=self.cap_min,'Threshold outside cap')
        _unique(self.thresholds_min,'thresholds_min')
        _require(self.primary_t_min in self.thresholds_min,'primary_t_min must be a reported threshold')
        if self.headway_factor_by_group is not None:
            for key,value in self.headway_factor_by_group.items():_id(key);_number(value,'headway factor',True)
        by_target={}
        for patch in self.patches:
            key=(patch.kind,patch.target_id)
            _require(key not in by_target or by_target[key]==patch,'Conflicting patches')
            _require(self.profile=='B' or patch.kind!='enable_parking','Parking activation requires B')
            by_target[key]=patch
        for candidate in self.candidate_ids:_id(candidate,'candidate_id')
        _unique(self.candidate_ids,'candidate_ids')
        object.__setattr__(self,'patches',tuple(sorted(by_target.values(),key=lambda p:p.to_json())))
        object.__setattr__(self,'thresholds_min',tuple(sorted(self.thresholds_min)))
        object.__setattr__(self,'candidate_ids',tuple(sorted(self.candidate_ids)))

    @property
    def config_hash(self):return self.content_hash()


@dataclass(frozen=True,kw_only=True)
class ServicePattern(JsonContract):
    pattern_id: str
    route_id: str
    direction_id: str
    stop_ids: tuple[str,...]
    provenance: Provenance

    def _validate(self):
        for value in (self.pattern_id,self.route_id,self.direction_id,*self.stop_ids):_id(value)
        _require(len(self.stop_ids)>=2,'Pattern needs at least two ordered stops')


@dataclass(frozen=True,kw_only=True)
class ServiceGroup(JsonContract):
    service_group_id: str
    pattern_ids: tuple[str,...]
    base_headway_min: float
    full_cycle_km: float | None
    speed_kmh: float | None
    stops_per_cycle: int | None
    dwell_s: float | None
    layover_min: float | None
    coverage: Literal['full','partial']
    field_status: Mapping[str,EvidenceStatus]
    provenance: Provenance

    def _validate(self):
        _id(self.service_group_id);_require(bool(self.pattern_ids),'Empty service patterns')
        for value in self.pattern_ids:_id(value)
        _unique(self.pattern_ids,'pattern_ids');_number(self.base_headway_min,'base_headway_min',True)
        cycle=('full_cycle_km','speed_kmh','stops_per_cycle','dwell_s','layover_min')
        required={'pattern_ids','base_headway_min',*cycle,'coverage'}
        _require(set(self.field_status)==required,'field_status must explicitly cover every service value')
        for name in cycle:
            value=getattr(self,name)
            if value is None:
                _require(self.coverage=='partial','Full coverage requires all cycle facts')
                _require(self.field_status[name]=='unverified','Unknown values require unverified status')
            else:_number(value,name,name in ('full_cycle_km','speed_kmh'))


@dataclass(frozen=True,kw_only=True)
class Link(JsonContract):
    link_id: str
    kind: Literal['walk','bike']
    length_m: float
    requires_construction: bool
    status: EvidenceStatus
    provenance: Provenance

    def _validate(self):_id(self.link_id);_number(self.length_m,'length_m',True)


@dataclass(frozen=True,kw_only=True)
class Parking(JsonContract):
    parking_id: str
    status: EvidenceStatus
    baseline_enabled: bool
    provenance: Provenance

    def _validate(self):_id(self.parking_id)


@dataclass(frozen=True,kw_only=True)
class ModelCatalog(Versioned):
    service_groups: Mapping[str,ServiceGroup]
    prebuilt_services: Mapping[str,ServiceGroup]
    links: Mapping[str,Link]
    parking: Mapping[str,Parking]
    patterns: tuple[ServicePattern,...] = ()
    sources: tuple[Provenance,...] = ()
    closure_ids: tuple[str,...] = ()
    station_ids: tuple[str,...] = ()
    exit_ids: tuple[str,...] = ()
    stop_ids: tuple[str,...] = ()

    def _validate(self):
        super()._validate()
        _require(not (set(self.service_groups)&set(self.prebuilt_services)),'Existing/prebuilt service IDs must be disjoint')
        for mapping,attr in ((self.service_groups,'service_group_id'),(self.prebuilt_services,'service_group_id'),(self.links,'link_id'),(self.parking,'parking_id')):
            for key,value in mapping.items():_require(key==getattr(value,attr),'Catalog mapping key/ID mismatch')
        pattern_ids={p.pattern_id for p in self.patterns}
        _unique(tuple(p.pattern_id for p in self.patterns),'patterns')
        sources={p.source_id:p for p in self.sources}
        _unique(tuple(s.source_id for s in self.sources),'sources')
        for name in ('closure_ids','station_ids','exit_ids','stop_ids'):
            values=getattr(self,name);_unique(values,name)
            for value in values:_id(value)
        assets=[*self.patterns,*self.service_groups.values(),*self.prebuilt_services.values(),*self.links.values(),*self.parking.values()]
        for asset in assets:_require(sources.get(asset.provenance.source_id)==asset.provenance,'Missing/conflicting source registry entry')
        for pattern in self.patterns:_require(set(pattern.stop_ids)<=set(self.stop_ids),'Unknown pattern stop')
        for group in (*self.service_groups.values(),*self.prebuilt_services.values()):_require(set(group.pattern_ids)<=pattern_ids,'Unknown service pattern')

    def validate_request(self,request):
        _require(type(request) is RoutingRequest,'Expected v1 RoutingRequest')
        _require((self.model_version,self.od_set_id)==(request.model_version,request.od_set_id),'Catalog/request identity mismatch')
        _require(request.closure_id is None or request.closure_id in self.closure_ids,'Unknown declared closure')
        _require(set(request.headway_factor_by_group or {})<=set(self.service_groups),'Headway factors target existing groups only')
        for patch in request.patches:
            mapping={'set_service_headway':self.service_groups,'activate_service':self.prebuilt_services,
                     'activate_link':self.links,'enable_parking':self.parking}[patch.kind]
            _require(patch.target_id in mapping,'Unknown patch target')
            if patch.kind=='activate_link':_require(request.profile=='B' or self.links[patch.target_id].kind!='bike','P cannot activate bike-only link')


@dataclass(frozen=True,kw_only=True)
class ODReference(JsonContract):
    od_id: str
    origin_id: str
    destination_id: str
    profile: Profile

    def _validate(self):
        for value in (self.od_id,self.origin_id,self.destination_id):_id(value)


@dataclass(frozen=True,kw_only=True)
class ODResult(JsonContract):
    od_id: str
    status: PathStatus
    minutes: float | None
    capped_minutes: float

    def _validate(self):
        _id(self.od_id);_number(self.capped_minutes,'capped_minutes')
        _require((self.minutes is None)==(self.status=='no_path'),'minutes is null iff no_path')
        if self.minutes is not None:_number(self.minutes,'minutes')


def _time_status(status,minutes,cap):
    _number(cap,'cap_min',True)
    if status=='no_path':_require(minutes is None,'no_path requires null minutes')
    else:
        _number(minutes,'minutes');_require((minutes<=cap)==(status=='reachable'),'status disagrees with cap')


@dataclass(frozen=True,kw_only=True)
class EvaluationResult(Versioned):
    state: State
    profile: Profile
    config_hash: str
    od_results: tuple[ODResult,...]
    within_counts: Mapping[int,int]
    capped_time_sum: float
    primary_t_min: int
    cap_min: float
    duration_ms: float
    warnings: tuple[str,...] = ()

    def _validate(self):
        super()._validate();_hash(self.config_hash)
        _number(self.cap_min,'cap_min',True);_number(self.duration_ms,'duration_ms');_number(self.capped_time_sum,'capped_time_sum')
        _require(bool(self.od_results),'Empty OD set');_unique(tuple(r.od_id for r in self.od_results),'OD IDs')
        _require(self.primary_t_min in self.within_counts,'Primary threshold not reported')
        for result in self.od_results:
            _time_status(result.status,result.minutes,self.cap_min)
            expected=self.cap_min if result.minutes is None else min(result.minutes,self.cap_min)
            _require(math.isclose(result.capped_minutes,expected,rel_tol=0,abs_tol=1e-9),'Inconsistent capped_minutes')
        _require(math.isclose(math.fsum(r.capped_minutes for r in self.od_results),self.capped_time_sum,rel_tol=0,abs_tol=1e-6),'Capped sum mismatch')
        for threshold,count in self.within_counts.items():
            _require(0<threshold<=self.cap_min and count>=0,'Invalid threshold/count')
            expected=sum(r.minutes is not None and r.minutes<=threshold for r in self.od_results)
            _require(count==expected,'within_counts mismatch')

    def validate_request(self,request):
        for name in ('contract_version','model_version','od_set_id','state','profile','config_hash','primary_t_min','cap_min'):
            _require(getattr(self,name)==getattr(request,name),'Request/result mismatch: '+name)
        _require(set(self.within_counts)==set(request.thresholds_min),'Request/result thresholds mismatch')


def _coordinates(point):
    lon,lat=point
    _require(-180<=lon<=180 and -90<=lat<=90,'WGS84 coordinate outside range')


@dataclass(frozen=True,kw_only=True)
class LineString(JsonContract):
    coordinates: tuple[tuple[float,float],...]
    type: Literal['LineString'] = 'LineString'

    def _validate(self):
        _require(len(self.coordinates)>=2,'LineString requires two points')
        for point in self.coordinates:_coordinates(point)


@dataclass(frozen=True,kw_only=True)
class MultiLineString(JsonContract):
    coordinates: tuple[tuple[tuple[float,float],...],...]
    type: Literal['MultiLineString'] = 'MultiLineString'

    def _validate(self):
        _require(bool(self.coordinates),'Empty MultiLineString')
        for line in self.coordinates:
            _require(len(line)>=2,'MultiLineString piece requires two points')
            for point in line:_coordinates(point)


@dataclass(frozen=True,kw_only=True)
class Point(JsonContract):
    coordinates: tuple[float,float]
    type: Literal['Point'] = 'Point'

    def _validate(self):_coordinates(self.coordinates)


Geometry = LineString | MultiLineString | Point
PathGeometry = LineString  # retained Python detail-type name; not a legacy payload parser


@dataclass(frozen=True,kw_only=True)
class GeometryMetadata(JsonContract):
    partial: bool
    gap_count: int
    provenance: tuple[Provenance,...]

    def _validate(self):
        _require(self.gap_count>=0 and self.partial==(self.gap_count>0),'partial/gap_count mismatch')
        _require(bool(self.provenance),'Geometry provenance required')


@dataclass(frozen=True,kw_only=True)
class JourneyLeg(JsonContract):
    mode: Mode
    from_id: str
    to_id: str
    route_id: str | None
    pattern_id: str | None
    board_stop_id: str | None
    alight_stop_id: str | None
    geometry: Geometry
    walk_min: float
    wait_min: float
    ride_min: float
    transfer_min: float
    provenance: tuple[Provenance,...]

    def _validate(self):
        _id(self.from_id);_id(self.to_id)
        for name in ('walk_min','wait_min','ride_min','transfer_min'):_number(getattr(self,name),name)
        names=('route_id','pattern_id','board_stop_id','alight_stop_id')
        if self.mode in ('bus','metro'):
            for name in names:_id(getattr(self,name),name)
        else:_require(all(getattr(self,name) is None for name in names),'Non-transit leg cannot claim transit IDs')
        _require(bool(self.provenance),'Leg provenance required')

    @property
    def total_min(self):return math.fsum((self.walk_min,self.wait_min,self.ride_min,self.transfer_min))


@dataclass(frozen=True,kw_only=True)
class JourneyResult(Versioned):
    config_hash: str
    state: State
    profile: Profile
    od_id: str
    origin_id: str
    destination_id: str
    status: PathStatus
    cap_min: float
    total_min: float | None
    geometry: Geometry | None
    geometry_metadata: GeometryMetadata
    legs: tuple[JourneyLeg,...]
    provenance: tuple[Provenance,...]
    generalised_cost_min: float | None = None
    warnings: tuple[str,...] = ()

    def _validate(self):
        super()._validate();_hash(self.config_hash)
        for value in (self.od_id,self.origin_id,self.destination_id):_id(value)
        _time_status(self.status,self.total_min,self.cap_min)
        _require(bool(self.provenance),'Journey provenance required')
        if self.status=='no_path':
            _require(self.geometry is None and not self.legs and self.generalised_cost_min is None,'no_path has no geometry, legs or cost')
            _require(not self.geometry_metadata.partial,'no_path is not partial geometry')
        else:
            _require(self.geometry is not None and bool(self.legs),'Existing path requires geometry and legs')
            gaps=sum(a[-1]!=b[0] for a,b in zip(self.geometry.coordinates,self.geometry.coordinates[1:])) if type(self.geometry) is MultiLineString else 0
            _require(self.geometry_metadata.gap_count==gaps,'Geometry boundaries disagree with partial metadata')
            _require(('GEOMETRY_GAPS' in self.warnings)==self.geometry_metadata.partial,'Geometry gap warning/metadata mismatch')
            _require(math.isclose(math.fsum(l.total_min for l in self.legs),self.total_min,rel_tol=0,abs_tol=1e-6),'Leg sum mismatch')
            _require(self.legs[0].from_id==self.origin_id and self.legs[-1].to_id==self.destination_id,'Journey endpoint mismatch')
            _require(all(a.to_id==b.from_id for a,b in zip(self.legs,self.legs[1:])),'Disconnected semantic leg IDs')
            _require(self.profile=='B' or all(l.mode!='bike' for l in self.legs),'P cannot cycle')
            if self.geometry_metadata.partial:
                _require(type(self.geometry) is MultiLineString and 'GEOMETRY_GAPS' in self.warnings,'Partial geometry requires MultiLineString and GEOMETRY_GAPS')
            if self.generalised_cost_min is not None:
                _number(self.generalised_cost_min,'generalised_cost_min');_require(self.generalised_cost_min>=self.total_min,'Generalised cost cannot reduce physical time')

    def validate_request(self,request):
        for name in ('contract_version','model_version','od_set_id','state','profile','config_hash','cap_min'):
            _require(getattr(self,name)==getattr(request,name),'Journey/request mismatch: '+name)
