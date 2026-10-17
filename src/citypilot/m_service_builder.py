"""Offline preparation of constructed M cycles; never modifies routing or a bundle."""
from __future__ import annotations

import csv
from dataclasses import dataclass
import hashlib
import json
import math
from pathlib import Path
import shutil

LINES = ('M1', 'M2', 'M3', 'M5', 'M6')
BUNDLE_HASH = '9457bfe95125b1d8bddb1be662ad6f0bbd1a00c0ac8f8abcc2fbecf872d53066'
COLUMNS = ('line','direction','seq','stop_key','stop_name','lat','lon','point_id',
           'google_stop_id','order_status','coord_status','checked_by','notes')
ORDERS = {
    'M1': ('M_ELMLER','M_28MAY_NMM'),
    'M2': ('M_INSAATCILAR','M_NIZAMI','M_28MAY_NMM'),
    'M3': ('M_ZERDABI_TBILISI','M_NIZAMI','M_28MAY_NMM'),
    'M5': ('M_20YANVAR_VELOTREK','M_GENCLIK_NMM'),
    'M6': ('M_ELMLER','M_GENCLIK_NMM'),
}


def require(condition, message):
    if not condition:
        raise ValueError(message)


def positive(value, name):
    require(type(value) in (int,float) and math.isfinite(value) and value > 0,
            name+' must be positive and finite')


def canonical(value):
    return json.dumps(value, sort_keys=True, ensure_ascii=False,
                      separators=(',', ':'), allow_nan=False).encode('utf-8')


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def read_stops(path):
    """CSV values remain strings (including leading zero IDs and Ali's notes)."""
    with Path(path).open(encoding='utf-8-sig', newline='') as stream:
        reader = csv.DictReader(stream)
        require(tuple(reader.fieldnames or ()) == COLUMNS, 'Unexpected/missing CSV columns')
        rows = list(reader)
    require(len(rows) == 24, 'Expected 24 stop rows')
    physical = {}
    for row in rows:
        require(set(row) == set(COLUMNS) and all(type(v) is str for v in row.values()), 'Malformed CSV row')
        for field in ('line','direction','seq','stop_key','point_id'):
            require(bool(row[field]) and row[field].strip() == row[field], 'Invalid string ID: '+field)
        require(row['line'] in LINES and row['direction'] in ('A','B'), 'Unexpected line/direction (M9 excluded)')
        require(row['seq'].isdigit(), 'Invalid seq')
        lat,lon = float(row['lat']),float(row['lon'])
        require(math.isfinite(lat) and math.isfinite(lon) and -90 <= lat <= 90 and -180 <= lon <= 180,
                'Invalid/non-finite stop coordinates')
        require(row['coord_status'] == 'approximate', 'Expected approximate coordinate status')
        require(row['order_status'] == ('published' if row['direction']=='A' else 'assumption'), 'Unexpected order provenance')
        identity = tuple(row[k] for k in ('lat','lon','point_id','google_stop_id','stop_name'))
        require(row['stop_key'] not in physical or physical[row['stop_key']] == identity,
                'Inconsistent coordinates/IDs/name per stop_key')
        physical[row['stop_key']] = identity
    require(len(physical) == 7, 'Expected 7 physical stops')
    for line in LINES:
        for direction in ('A','B'):
            selected = sorted((r for r in rows if (r['line'],r['direction'])==(line,direction)), key=lambda r:int(r['seq']))
            order = ORDERS[line] if direction=='A' else ORDERS[line][::-1]
            require([int(r['seq']) for r in selected] == list(range(1,len(order)+1)), 'Missing/duplicate/nonconsecutive seq')
            require(tuple(r['stop_key'] for r in selected) == order, 'Unexpected A order or B is not reversed A')
    return rows


@dataclass(frozen=True)
class Anchor:
    edge_id: str
    fraction: float
    displacement_m: float
    xy: tuple
    directions: tuple


class BusRoadNetwork:
    """Source road flags are the bundle's bus-access approximation, busways included."""
    def __init__(self, nodes, edges):
        import numpy as np
        from scipy.sparse import csr_matrix
        from shapely.geometry import LineString
        from shapely.strtree import STRtree
        edges = edges.reset_index(drop=True)
        require(nodes.index.is_unique and np.array_equal(nodes.index, np.arange(len(nodes))), 'Invalid node IDs')
        require(edges.edge_id.is_unique, 'Duplicate edge IDs')
        require(np.isfinite(nodes[['x','y']]).all().all(), 'Non-finite nodes')
        require(np.isfinite(edges[['x0','y0','x1','y1','length_m']]).all().all() and (edges.length_m >= 0).all(), 'Invalid road lengths/coordinates')
        for flag in ('drive_forward','drive_reverse','walk_forward','walk_reverse'):
            require(all(type(v) in (bool,np.bool_) for v in edges[flag]), 'Invalid permission flags: '+flag)
        self.nodes = nodes
        self.all_edges = edges
        self.edges = edges.loc[(edges.edge_type=='road') & (edges.drive_forward|edges.drive_reverse)].sort_values('edge_id').reset_index(drop=True)
        for endpoint,suffix in (('u','0'),('v','1')):
            require(self.edges[endpoint].between(0,len(nodes)-1).all(), 'Unknown road endpoint')
            require(np.allclose(nodes.loc[self.edges[endpoint],['x','y']], self.edges[['x'+suffix,'y'+suffix]], rtol=0,atol=1e-6), 'Node/road coordinate mismatch')
        self.by_id = self.edges.set_index('edge_id')
        arcs = []
        for e in self.edges.itertuples(index=False):
            if e.drive_forward: arcs.append((int(e.u),int(e.v),float(e.length_m),str(e.edge_id),0.,1.))
            if e.drive_reverse: arcs.append((int(e.v),int(e.u),float(e.length_m),str(e.edge_id),1.,0.))
        self.arcs = {}
        for arc in sorted(arcs,key=lambda a:(a[0],a[1],a[2],a[3],a[4])):
            self.arcs.setdefault(arc[:2],arc)
        chosen = list(self.arcs.values())
        self.graph = csr_matrix(([a[2] for a in chosen],([a[0] for a in chosen],[a[1] for a in chosen])),shape=(len(nodes),len(nodes)))
        self.graph.sort_indices()
        self.cache = {}
        self.snap_edges = self.edges.loc[(self.edges.x0!=self.edges.x1)|(self.edges.y0!=self.edges.y1)].reset_index(drop=True)
        self.shapes = [LineString(((e.x0,e.y0),(e.x1,e.y1))) for e in self.snap_edges.itertuples(index=False)]
        self.tree = STRtree(self.shapes) if self.shapes else None

    @staticmethod
    def nearest(xy, edges):
        """Used for loader-equivalent pedestrian audit; no reachable-component preference."""
        from shapely.geometry import LineString, Point
        from shapely.strtree import STRtree
        edges = edges.sort_values('edge_id').reset_index(drop=True)
        if edges.empty: return None
        shapes = [LineString(((e.x0,e.y0),(e.x1,e.y1))) for e in edges.itertuples(index=False)]
        matches,distances = STRtree(shapes).query_nearest(Point(xy),all_matches=True,return_distance=True)
        idx,dist = min(zip(matches,distances),key=lambda p:(float(p[1]),str(edges.iloc[int(p[0])].edge_id)))
        return {'edge_id':str(edges.iloc[int(idx)].edge_id),'displacement_m':float(dist)}

    def snap(self, xy, limit):
        from shapely.geometry import Point
        positive(limit,'max_snap_m')
        require(all(math.isfinite(v) for v in xy), 'Invalid snap coordinates')
        if self.tree is None: return None
        matches,distances = self.tree.query_nearest(Point(xy),all_matches=True,return_distance=True)
        idx,dist = min(zip(matches,distances),key=lambda p:(float(p[1]),str(self.snap_edges.iloc[int(p[0])].edge_id)))
        e = self.snap_edges.iloc[int(idx)];shape = self.shapes[int(idx)]
        f = float(shape.project(Point(xy),normalized=True))
        if f*shape.length < 1e-8: f=0.
        elif (1-f)*shape.length < 1e-8: f=1.
        point = shape.interpolate(f,normalized=True)
        directions = tuple(d for d,ok in ((1,e.drive_forward),(-1,e.drive_reverse)) if ok)
        # Retain excessive snap evidence; callers block it rather than retry elsewhere.
        return Anchor(str(e.edge_id), f, float(dist), (float(point.x),float(point.y)), directions)

    def shortest_nodes(self, source, target):
        from scipy.sparse.csgraph import dijkstra
        if source not in self.cache:
            self.cache[source] = dijkstra(self.graph,directed=True,indices=source,return_predecessors=True)
        distances,predecessors = self.cache[source]
        if not math.isfinite(distances[target]): return None
        nodes = [target]
        while nodes[-1] != source:
            previous = int(predecessors[nodes[-1]])
            require(previous >= 0 and len(nodes) <= len(self.nodes), 'Invalid shortest path predecessor')
            nodes.append(previous)
        nodes.reverse()
        pieces = [(self.arcs[(u,v)][3],self.arcs[(u,v)][4],self.arcs[(u,v)][5]) for u,v in zip(nodes,nodes[1:])]
        return float(distances[target]),pieces

    def leg(self, a, da, b, db):
        """Directed partial lengths, plus source-node shortest distance; no off-road ride."""
        ea,eb = self.by_id.loc[a.edge_id],self.by_id.loc[b.edge_id]
        out_f = 1. if da==1 else 0.; in_f = 0. if db==1 else 1.
        out_node = int(ea.v if da==1 else ea.u); in_node = int(eb.u if db==1 else eb.v)
        candidates = []
        delta = b.fraction-a.fraction
        if a.edge_id==b.edge_id and da==db and delta*da>=0:
            candidates.append((abs(delta)*float(ea.length_m),[(a.edge_id,a.fraction,b.fraction)]))
        # At source endpoints an exact node anchor has zero partial cost.
        if a.fraction in (0.,1.): out_node=int(ea.u if a.fraction==0 else ea.v);out_f=a.fraction
        if b.fraction in (0.,1.): in_node=int(eb.u if b.fraction==0 else eb.v);in_f=b.fraction
        middle = self.shortest_nodes(out_node,in_node)
        if middle is not None:
            cost = abs(out_f-a.fraction)*float(ea.length_m)+middle[0]+abs(b.fraction-in_f)*float(eb.length_m)
            pieces = [(a.edge_id,a.fraction,out_f)]+middle[1]+[(b.edge_id,in_f,b.fraction)]
            candidates.append((cost,pieces))
        if not candidates: return None
        cost,pieces = min(candidates,key=lambda c:(c[0],c[1]))
        pieces = [p for p in pieces if p[1]!=p[2]]
        require(math.isclose(cost,math.fsum(abs(y-x)*float(self.by_id.loc[e].length_m) for e,x,y in pieces),abs_tol=1e-7), 'Partial path length mismatch')
        return cost,pieces

    def pattern(self, anchors):
        """DP over each stop's traversal orientation; arrival and departure agree."""
        states = {d:(0.,[],[d]) for d in anchors[0].directions}
        for a,b in zip(anchors,anchors[1:]):
            next_states = {}
            for db in b.directions:
                choices = []
                for da,(cost,legs,directions) in sorted(states.items()):
                    leg = self.leg(a,da,b,db)
                    if leg is not None: choices.append((cost+leg[0],legs+[leg],directions+[db]))
                if choices: next_states[db]=min(choices,key=lambda c:(c[0],c[2],c[1]))
            states = next_states
        return min(states.values(),key=lambda c:(c[0],c[2],c[1])) if states else None

    def geometry(self, pieces, backward, anchor):
        coordinates = []
        for eid,f0,f1 in pieces:
            e = self.by_id.loc[eid]
            points = [(float(e.x0+f*(e.x1-e.x0)),float(e.y0+f*(e.y1-e.y0))) for f in (f0,f1)]
            if coordinates:
                require(math.dist(coordinates[-1],points[0]) < 1e-6, 'Disconnected road path geometry')
                coordinates.append(points[1])
            else: coordinates.extend(points)
        if not coordinates: return {'type':'Point','coordinates':list(backward.transform(*anchor.xy))}
        return {'type':'LineString','coordinates':[list(backward.transform(*xy)) for xy in coordinates]}


def provenance(source_id, evidence, status='assumption'):
    return {'source_id':source_id,'status':status,'source':'Supplied m_stops_directed.csv and immutable C4 road model','evidence':evidence}


def prepare(model, rows, max_snap_m, detour_ratio):
    from pyproj import Transformer
    positive(max_snap_m,'max_snap_m');positive(detour_ratio,'detour_ratio')
    network = BusRoadNetwork(model['nodes'],model['edges'])
    forward = Transformer.from_crs('EPSG:4326',model['runtime']['metric_crs'],always_xy=True)
    backward = Transformer.from_crs(model['runtime']['metric_crs'],'EPSG:4326',always_xy=True)
    walk = network.all_edges.loc[(network.all_edges.edge_type=='road') & (network.all_edges.walk_forward|network.all_edges.walk_reverse) & (network.all_edges.length_m>0)]
    stops,anchors,audit = {},{},{}
    for row in sorted(rows,key=lambda r:(r['stop_key'],r['line'],r['direction'],int(r['seq']))):
        sid = row['stop_key']
        if sid in stops: continue
        coordinates = [float(row['lon']),float(row['lat'])];xy=forward.transform(*coordinates)
        bounds = model['nodes']
        inside = bounds.x.min()-1e-6<=xy[0]<=bounds.x.max()+1e-6 and bounds.y.min()-1e-6<=xy[1]<=bounds.y.max()+1e-6
        anchor = network.snap(xy,max_snap_m); pedestrian = network.nearest(xy,walk)
        status = ('outside_model' if not inside else 'no_bus_snap' if anchor is None else
                  'excessive_bus_snap' if anchor.displacement_m>max_snap_m else
                  'excessive_walk_snap' if pedestrian is None or pedestrian['displacement_m']>max_snap_m else 'ready')
        anchors[sid] = anchor
        audit[sid] = {'status':status,'coordinates':coordinates,'bus_snap':None if anchor is None else {
            'edge_id':anchor.edge_id,'fraction':anchor.fraction,'displacement_m':anchor.displacement_m,
            'snapped_coordinates':list(backward.transform(*anchor.xy)),'permitted_directions':list(anchor.directions)},'walk_snap':pedestrian}
        originals = sorted((r for r in rows if r['stop_key']==sid), key=lambda r:(r['line'],r['direction'],int(r['seq'])))
        stops[sid] = {'stop_id':sid,'coordinates':coordinates,'location_kind':'bus_stop',
            'provenance':provenance('m:stop:'+sid, 'Approximate ordinary-stop location, not a verified express platform. Original string fields and Ali notes: '+canonical(originals).decode())}
    speeds = model['services'].set_index('service_group_id')
    require({'SG_R2','SG_R14'} <= set(speeds.index), 'Missing curated R2/R14 speed inputs')
    calibrated = [float(speeds.loc[s,'speed_kmh']) for s in ('SG_R2','SG_R14')]
    for speed in calibrated: positive(speed,'curated speed')
    speed = math.fsum(calibrated)/2
    with (model['root']/'curated/assumptions.csv').open(encoding='utf-8-sig',newline='') as stream:
        assumptions = list(csv.DictReader(stream))
    p5 = [r for r in assumptions if r['param_id']=='P5']
    require(len(p5)==1 and p5[0]['unit']=='min', 'Missing/invalid P5 terminal layover')
    layover = 2*float(p5[0]['value_default']);positive(layover,'full-cycle layover')
    patterns,groups,directions,blocked = [],[],{},{}
    for line in LINES:
        built=[];failures=[]
        for direction in ('A','B'):
            pid=line+'_'+direction;order=ORDERS[line] if direction=='A' else ORDERS[line][::-1]
            bad = [s for s in order if audit[s]['status']!='ready']
            result = None if bad else network.pattern([anchors[s] for s in order])
            if bad or result is None:
                reason={'status':'blocked_stop' if bad else 'no_path','stops':bad}
                directions[pid]=reason;failures.append(pid);continue
            total,legs,orientations=result
            segments=[];geometries=[]
            for i,(length,pieces) in enumerate(legs):
                a,b=order[i:i+2];straight=math.dist(anchors[a].xy,anchors[b].xy)
                ratio=length/straight if straight>0 else (1. if length==0 else None)
                segments.append({'from_stop_id':a,'to_stop_id':b,'segment_m':length,
                    'snap_chord_m':straight,'detour_ratio':ratio,'suspicious_detour':(ratio is None or ratio>detour_ratio),
                    'directed_pieces':[{'edge_id':e,'from_fraction':x,'to_fraction':y,'length_m':abs(y-x)*float(network.by_id.loc[e].length_m)} for e,x,y in pieces]})
                geometries.append(network.geometry(pieces,backward,anchors[a]))
            directions[pid]={'status':'built','distance_m':total,'anchor_directions':orientations,'stop_ids':list(order),'segments':segments}
            order_evidence='Published forward stop order supplied by Ali.' if direction=='A' else 'Return stop order assumed by reversing A; not published.'
            prov=provenance('m:pattern:'+pid,order_evidence+' Coordinates approximate; street path and segment_m are assumed/modelled shortest DISTANCE on bundle bus-eligible directed roads, busways retained. B solved independently, no coordinate shift. Grade transitions and bus permissions remain uncertain; not an official street route.', 'modelled')
            built.append({'pattern':{'pattern_id':pid,'route_id':line,'direction_id':direction,'stop_ids':list(order),'provenance':prov},
                          'segment_m':[s['segment_m'] for s in segments],'segment_geometry':geometries})
        if failures:
            blocked[line]={'failed_patterns':failures,'excluded_variants':['SVC_'+line+'_A','SVC_'+line+'_B']};continue
        patterns.extend(built)
        cycle=math.fsum(math.fsum(p['segment_m']) for p in built)/1000
        dwell_count=sum(max(len(p['pattern']['stop_ids'])-2,0) for p in built)
        for suffix,headway in (('A',6.),('B',9.)):
            group={'service_group_id':'SVC_'+line+'_'+suffix,'pattern_ids':[p['pattern']['pattern_id'] for p in built],
                   'base_headway_min':headway,'full_cycle_km':cycle,'speed_kmh':speed,'stops_per_cycle':dwell_count,
                   'dwell_s':25.,'layover_min':layover,'coverage':'full'}
            group['field_status']={k:('modelled' if k in ('full_cycle_km','stops_per_cycle') else 'assumption') for k in group if k!='service_group_id'}
            group['provenance']=provenance('m:service:'+group['service_group_id'],
                'Complete CONSTRUCTED model cycle only; coverage=full does not verify official M-route coverage. A/B service suffix means design headway 6/9 minutes, independent of pattern direction. Both directed patterns included. Speed transferred as arithmetic mean of actual curated SG_R2/SG_R14 calibrated speeds '+str(calibrated)+' km/h; dwell=25 s at intermediate stops only; full-cycle layover=2*P5='+str(layover)+' min. No verified express platforms/street routes. Grade assumptions and uncertain bus access retained.')
            groups.append(group)
    used={s for p in patterns for s in p['pattern']['stop_ids']}
    assets={'access_policy':{'max_snap_m':max_snap_m,'excessive_snap':'unreachable'},'stops':[stops[s] for s in sorted(used)],
            'patterns':patterns,'prebuilt_services':groups}
    report={'policy_version':'constructed-m-bus-roads-1','max_snap_m':max_snap_m,'suspicious_detour_ratio_above':detour_ratio,
            'bus_eligibility':'edge_type=road AND (drive_forward OR drive_reverse); includes permitted busways; approximate class permissions, not verified bus access',
            'grade_policy':'Source node IDs and directed costs preserved, no geometric crossing joins. Source endpoint grade transitions include assumptions.',
            'anchor_policy':'Nearest edge by metric distance, exact ties by edge_id; no component preference. Shared orientation through intermediate stops; B independently solved at original coordinates. Turns at original source nodes follow bundle topology; no new turns at artificial anchors.',
            'coverage_warning':'Full is a complete CONSTRUCTED model cycle, not verified official M-route coverage.',
            'input_rows':rows,'stops':audit,'directions':directions,'blocked_lines':blocked,
            'ready_service_ids':[g['service_group_id'] for g in groups],
            'cycles':{g['service_group_id']: {k:g[k] for k in ('full_cycle_km','stops_per_cycle','speed_kmh','dwell_s','layover_min','base_headway_min')} for g in groups},
            'network':{'bus_road_segments':len(network.edges),'directed_connections':network.graph.nnz,
                       'busway_segments':int(network.edges.fclass.fillna('').str.startswith('busway').sum())}}
    return assets,report


def build_supplement(artifact_dir, csv_path, output_dir, *, max_snap_m, detour_ratio=3.):
    from citypilot.routing_engine import load_model
    bundle=Path(artifact_dir).resolve();output=Path(output_dir).resolve();csv_path=Path(csv_path).resolve()
    require(not output.is_relative_to(bundle) and not bundle.is_relative_to(output), 'Output must be separate from bundle')
    require(not output.exists(), 'Output exists; use a new empty output path')
    rows=read_stops(csv_path)
    manifest_bytes=(bundle/'manifest.json').read_bytes()
    model=load_model(bundle,bundle/'config')
    require(model['manifest']['bundle_hash']==BUNDLE_HASH, 'Unexpected baseline bundle binding')
    assets,report=prepare(model,rows,max_snap_m,detour_ratio)
    report.update(bundle_hash=BUNDLE_HASH,source_csv_sha256=sha(csv_path),bundle_manifest_sha256=sha(bundle/'manifest.json'))
    # Every directory gets a report; entirely blocked builds have no registry.
    output.mkdir(parents=True)
    (output/'source_stops.csv').write_bytes(csv_path.read_bytes())
    if assets['prebuilt_services']:
        config=output/'config';shutil.copytree(bundle/'config',config)
        registry=config/'prebuilt_services';registry.mkdir()
        payload=canonical(assets)+b'\n';(registry/'assets.json').write_bytes(payload)
        manifest={'asset_version':'prebuilt-services-1','bundle_hash':BUNDLE_HASH,'files':{'assets.json':hashlib.sha256(payload).hexdigest()}}
        # Match CURRENT loader: default ensure_ascii=True in identity serialization.
        manifest['supplement_hash']=hashlib.sha256(json.dumps(manifest,sort_keys=True,separators=(',',':'),allow_nan=False).encode()).hexdigest()
        (registry/'manifest.json').write_bytes(canonical(manifest)+b'\n')
        report['supplement_manifest']=manifest
        registered=load_model(bundle,config)
        require(set(registered['prebuilt_services'])==set(report['ready_service_ids']), 'Registry/catalog mismatch')
        for sid,stop in registered['prebuilt_stops'].items():
            require(stop['status']=='attached', 'Ready stop failed loader access: '+sid)
            require(abs(stop['snap_m']-report['stops'][sid]['walk_snap']['displacement_m'])<1e-7, 'Loader snap audit mismatch')
    require((bundle/'manifest.json').read_bytes()==manifest_bytes, 'Bundle manifest changed')
    (output/'build_report.json').write_bytes(canonical(report)+b'\n')
    return report
