"""Offline, modelled private-car OD distances; no transit/CO2/decision changes."""
from __future__ import annotations

import csv
from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
import io
import json
import math
from pathlib import Path
import time
from typing import Any

POLICY_VERSION = 'private-car-approx-v1'
ENDPOINT_TOLERANCE_M = 1e-8
COLUMNS = ('od_id','origin_id','destination_id','profile','car_distance_km',
           'status','snap_m','origin_snap_m','destination_snap_m')


class DistanceError(ValueError):
    """Invalid or inconsistent immutable inputs, parameters or derived output."""


def require(condition, message):
    if not condition:
        raise DistanceError(message)


def positive(value, name):
    require(type(value) in (float,int) and math.isfinite(value) and value>0,
            name+' must be positive and finite')


def canonical(value):
    return json.dumps(value,sort_keys=True,ensure_ascii=False,separators=(',',':'),allow_nan=False).encode('utf-8')


def sha_file(path):
    digest=hashlib.sha256()
    with Path(path).open('rb') as stream:
        for chunk in iter(lambda:stream.read(1024*1024),b''):digest.update(chunk)
    return digest.hexdigest()


def graph_hash(graph):
    """Portable CSR identity: shape then sorted little-endian int64/float64 arrays."""
    digest=hashlib.sha256(canonical({'shape':list(graph.shape),'encoding':'csr-le-i8-i8-f8-v1'}))
    for array,dtype in ((graph.indptr,'<i8'),(graph.indices,'<i8'),(graph.data,'<f8')):
        digest.update(array.astype(dtype,copy=False).tobytes(order='C'))
    return digest.hexdigest()


def minimum_graph(arcs, node_count):
    from scipy.sparse import csr_matrix
    # Stable minimum per pair before CSR construction; preserve explicit zeros.
    selected=arcs.sort_values('length_m',kind='stable').drop_duplicates(['u','v'])
    return csr_matrix((selected.length_m.to_numpy(dtype=float),
        (selected.u.to_numpy(dtype='int64'),selected.v.to_numpy(dtype='int64'))),
        shape=(node_count,node_count))


@dataclass(frozen=True)
class Snap:
    edge_id: str
    u: int
    v: int
    fraction: float
    length_m: float
    forward: bool
    reverse: bool
    displacement_m: float
    xy: tuple[float,float]
    eligible: bool

    def outgoing(self):
        options={}
        if self.fraction==0:options[self.u]=0.
        if self.fraction==1:options[self.v]=0.
        if self.forward:options[self.v]=min(options.get(self.v,math.inf),(1-self.fraction)*self.length_m)
        if self.reverse:options[self.u]=min(options.get(self.u,math.inf),self.fraction*self.length_m)
        return options

    def incoming(self):
        options={}
        if self.fraction==0:options[self.u]=0.
        if self.fraction==1:options[self.v]=0.
        if self.forward:options[self.u]=min(options.get(self.u,math.inf),self.fraction*self.length_m)
        if self.reverse:options[self.v]=min(options.get(self.v,math.inf),(1-self.fraction)*self.length_m)
        return options


class CarNetwork:
    """Filter source edges without inventing nodes, intersection or grade links."""

    def __init__(self,nodes,edges,drive_arcs,source_graph=None):
        import numpy as np
        from shapely.geometry import LineString
        from shapely.strtree import STRtree
        # C4 keeps edge_id as both index and column; normalise a local copy only.
        edges=edges.reset_index(drop=True)
        require(nodes.index.is_unique and np.array_equal(nodes.index.to_numpy(),np.arange(len(nodes))),
                'Contiguous source node IDs required')
        require(edges.edge_id.is_unique,'Duplicate source edge IDs')
        require(np.isfinite(nodes[['x','y']]).all().all(),'Non-finite source nodes')
        require(np.isfinite(edges[['x0','y0','x1','y1','length_m']]).all().all() and
                (edges.length_m>=0).all(),'Invalid source segment geometry/length')
        for name in ('drive_forward','drive_reverse'):
            require(all(type(v) in (bool,np.bool_) for v in edges[name]),'Invalid drive flags: '+name)
        require(set(drive_arcs.edge_id)<=set(edges.edge_id),'Unknown drive arc edge')
        require(np.isfinite(drive_arcs.length_m).all() and (drive_arcs.length_m>=0).all(),'Invalid drive lengths')
        require(drive_arcs.u.between(0,len(nodes)-1).all() and drive_arcs.v.between(0,len(nodes)-1).all(),
                'Unknown source drive endpoint')
        require(not drive_arcs.duplicated(['edge_id','direction']).any(),'Duplicate source drive directions')
        indexed=edges.set_index('edge_id')
        aligned=indexed.loc[drive_arcs.edge_id].reset_index(drop=True)
        forward=drive_arcs.direction.to_numpy()=='forward'
        reverse=drive_arcs.direction.to_numpy()=='reverse'
        require((forward|reverse).all(),'Unknown source drive direction')
        require(np.array_equal(drive_arcs.u,np.where(forward,aligned.u,aligned.v)) and
                np.array_equal(drive_arcs.v,np.where(forward,aligned.v,aligned.u)), 'Drive arc direction disagrees with segment')
        require(np.allclose(drive_arcs.length_m,aligned.length_m,rtol=0,atol=1e-7),'Drive arc length mismatch')
        require(np.where(forward,aligned.drive_forward,aligned.drive_reverse).all(),'Source drive arc violates flags')
        require(len(drive_arcs)==int(edges.drive_forward.sum()+edges.drive_reverse.sum()),'Missing source drive directions')
        if source_graph is not None:
            require(source_graph.shape==(len(nodes),len(nodes)) and source_graph.has_canonical_format,'Invalid source drive matrix')
            reference=minimum_graph(drive_arcs,len(nodes))
            require(np.array_equal(reference.indptr,source_graph.indptr) and
                    np.array_equal(reference.indices,source_graph.indices) and
                    np.allclose(reference.data,source_graph.data,rtol=0,atol=1e-7),'Source graph/arcs mismatch')
        drive=edges.drive_forward|edges.drive_reverse
        road=edges.edge_type=='road'
        busway=edges.fclass.fillna('').str.strip().str.casefold().str.startswith('busway')
        self.edges=edges.loc[drive&road&~busway].copy().sort_values('edge_id',kind='stable').reset_index(drop=True)
        # Validate endpoint identities, but never merge coincident XY nodes.
        for endpoint in ('u','v'):
            points=nodes.loc[self.edges[endpoint],['x','y']].to_numpy()
            suffix='0' if endpoint=='u' else '1'
            require(np.allclose(points,self.edges[['x'+suffix,'y'+suffix]].to_numpy(),rtol=0,atol=1e-6),
                    'Segment/source-node coordinate mismatch')
        self.arcs=drive_arcs.loc[drive_arcs.edge_id.isin(self.edges.edge_id)].copy()
        self.graph=minimum_graph(self.arcs,len(nodes))
        require(np.isfinite(self.graph.data).all() and (self.graph.data>=0).all(),'Invalid filtered graph')
        self.snap_edges=self.edges.loc[((self.edges.x1-self.edges.x0)**2+(self.edges.y1-self.edges.y0)**2)>0].reset_index(drop=True)
        self.shapes=[LineString(((r.x0,r.y0),(r.x1,r.y1))) for r in self.snap_edges.itertuples(index=False)]
        self.tree=STRtree(self.shapes) if self.shapes else None
        active=np.unique(np.concatenate((self.arcs.u.to_numpy(),self.arcs.v.to_numpy())))
        self.summary={'source_nodes':len(nodes),'source_drive_arcs':len(drive_arcs),
            'source_drive_segments':int(drive.sum()),'excluded_busway_segments':int((drive&busway).sum()),
            'excluded_nonroad_drive_segments':int((drive&~road&~busway).sum()),
            'car_segments':len(self.edges),'car_directed_arcs':len(self.arcs),
            'car_minimum_directed_connections':self.graph.nnz,'car_active_nodes':len(active),
            'degenerate_segments_not_used_for_snapping':len(self.edges)-len(self.snap_edges),
            'preserved_assumed_endpoint_transition_nodes':int(nodes.loc[active,'endpoint_transition_assumed'].fillna(False).sum()) if len(active) and 'endpoint_transition_assumed' in nodes else 0,
            'csr_sha256':graph_hash(self.graph)}

    def snap(self,xy,max_snap_m):
        from shapely.geometry import Point
        positive(max_snap_m,'max_snap_m')
        require(len(xy)==2 and all(math.isfinite(v) for v in xy),'Invalid projected OD coordinate')
        if self.tree is None:return None
        point=Point(xy)
        matches,distances=self.tree.query_nearest(point,all_matches=True,return_distance=True)
        # Exact distance ties: sorted opaque source edge ID; no component preference.
        index,distance=min(zip(matches,distances),key=lambda pair:(float(pair[1]),str(self.snap_edges.iloc[int(pair[0])].edge_id)))
        edge=self.snap_edges.iloc[int(index)];a=(float(edge.x0),float(edge.y0));b=(float(edge.x1),float(edge.y1))
        dx,dy=b[0]-a[0],b[1]-a[1]
        fraction=max(0.,min(1.,((xy[0]-a[0])*dx+(xy[1]-a[1])*dy)/(dx*dx+dy*dy)))
        if math.hypot(fraction*dx,fraction*dy)<=ENDPOINT_TOLERANCE_M:fraction=0.
        elif math.hypot((1-fraction)*dx,(1-fraction)*dy)<=ENDPOINT_TOLERANCE_M:fraction=1.
        snapped=(a[0]+fraction*dx,a[1]+fraction*dy)
        displacement=math.hypot(xy[0]-snapped[0],xy[1]-snapped[1])
        return Snap(str(edge.edge_id),int(edge.u),int(edge.v),float(fraction),float(edge.length_m),
                    bool(edge.drive_forward),bool(edge.drive_reverse),displacement,snapped,displacement<=max_snap_m)


def direct_distance(origin,destination):
    if origin.edge_id!=destination.edge_id:return math.inf
    delta=destination.fraction-origin.fraction
    if delta==0:return 0.
    if delta>0 and origin.forward:return delta*origin.length_m
    if delta<0 and origin.reverse:return -delta*origin.length_m
    return math.inf


def physical_distances(network,origins,destinations):
    """Nine reverse searches; weighted directional endpoints plus same-segment path."""
    import numpy as np
    from scipy.sparse import coo_matrix
    from scipy.sparse.csgraph import dijkstra
    base=network.graph;size=base.shape[0];coo=base.tocoo()
    u=list(coo.row);v=list(coo.col);weights=list(coo.data)
    for i,(_,snap) in enumerate(destinations.items()):
        if snap is not None and snap.eligible:
            for endpoint,cost in snap.incoming().items():u.append(endpoint);v.append(size+i);weights.append(cost)
    # Distinct virtual destination sinks prevent mixing the individual exits.
    augmented=coo_matrix((weights,(u,v)),shape=(size+len(destinations),size+len(destinations))).tocsr()
    distances=dijkstra(augmented.T.tocsr(),directed=True,indices=np.arange(size,size+len(destinations)))
    result={}
    for i,(destination_id,destination) in enumerate(destinations.items()):
        for origin_id,origin in origins.items():
            km=None
            if origin is None or destination is None or not origin.eligible or not destination.eligible:
                status='snap_failed'
            else:
                best=direct_distance(origin,destination)
                for endpoint,cost in origin.outgoing().items():best=min(best,cost+float(distances[i,endpoint]))
                if math.isinf(best):status='no_path'
                else:
                    require(math.isfinite(best) and best>=0,'Invalid calculated network distance')
                    status='modelled';km=best/1000
            origin_snap=None if origin is None else origin.displacement_m
            destination_snap=None if destination is None else destination.displacement_m
            result[origin_id,destination_id]={'car_distance_km':km,'status':status,
                'snap_m':None if origin_snap is None or destination_snap is None else max(origin_snap,destination_snap),
                'origin_snap_m':origin_snap,'destination_snap_m':destination_snap}
    return result


def build_supplement(artifact_dir,output_dir,*,max_snap_m):
    """Explicit immutable inputs, external supplement, exact canonical evaluator IDs."""
    from collections import Counter
    import numpy as np
    from pyproj import CRS,Transformer
    from scipy.sparse import load_npz
    from citypilot import routing_engine as routing
    start=time.perf_counter();positive(max_snap_m,'max_snap_m')
    root=Path(artifact_dir).resolve();output=Path(output_dir).resolve()
    require(not output.is_relative_to(root),'Supplement output must be outside immutable bundle')
    csv_path=output/'od_car_distances.csv';manifest_path=output/'manifest.json'
    require(not csv_path.exists() and not manifest_path.exists(),'Output already exists; choose a new output directory; existing files are never overwritten')
    model=routing.load_model(root,root/'config')
    crs=CRS.from_user_input(model['runtime']['metric_crs'])
    require(crs.is_projected and all(a.unit_name=='metre' for a in crs.axis_info),'Metric projected CRS required')
    transformer=Transformer.from_crs('EPSG:4326',crs,always_xy=True)
    drive_arcs=routing._table(root,'drive_arcs.csv.gz')
    network=CarNetwork(model['nodes'],model['edges'],drive_arcs,load_npz(root/'drive_distance_graph.npz').tocsr())
    snaps={};snap_records={}
    for role,features in (('origin',model['origins']),('destination',model['destinations'])):
        local={}
        for identifier,feature in features.items():
            require(feature['geometry']['type']=='Point','Actual OD Point geometry required')
            lonlat=feature['geometry']['coordinates'];xy=transformer.transform(*lonlat)
            snap=network.snap(xy,max_snap_m);local[identifier]=snap
            snap_records[identifier]={'role':role,'input_wgs84':lonlat,'projected_xy_m':list(xy),
                'snap':None if snap is None else {'edge_id':snap.edge_id,'u':snap.u,'v':snap.v,'fraction':snap.fraction,
                    'snapped_xy_m':list(snap.xy),'distance_m':snap.displacement_m,'within_limit':snap.eligible}}
        snaps[role]=local
    physical=physical_distances(network,snaps['origin'],snaps['destination'])
    require(len(physical)==2718 and len(model['origins'])==302 and len(model['destinations'])==9,'Unexpected fixed OD dimensions')
    rows=[];id_checks={};references=[]
    for profile in ('P','B'):
        mapping=routing.get_od_table(model,profile)
        evaluation=routing.evaluate_package(model,routing.baseline_request(model,'normal',profile))
        expected={row.od_id for row in evaluation.od_results}
        require({ref.od_id for ref in mapping}==expected and len(expected)==2718,'Canonical OD/evaluator ID mismatch')
        for ref in mapping:
            row={'od_id':ref.od_id,'origin_id':ref.origin_id,'destination_id':ref.destination_id,'profile':profile,
                 **physical[ref.origin_id,ref.destination_id]}
            rows.append(row);references.append(ref.to_dict())
        id_checks[profile]={'state':'normal','rows':len(mapping),'exact_id_set_match':True,
                            'evaluator_config_hash':evaluation.config_hash,'od_id_sha256':hashlib.sha256(canonical(sorted(expected))).hexdigest()}
    require(len(rows)==5436 and len({r['od_id'] for r in rows})==5436,'Profile row/ID dimension mismatch')
    require(all(r['car_distance_km'] is None or (math.isfinite(r['car_distance_km']) and r['car_distance_km']>=0) for r in rows),'Non-finite output')
    buffer=io.StringIO(newline='')
    writer=csv.DictWriter(buffer,fieldnames=COLUMNS,lineterminator='\n');writer.writeheader()
    for row in rows:writer.writerow({k:format(v,'.15g') if type(v) is float else v for k,v in row.items()})
    csv_bytes=buffer.getvalue().encode('utf-8')
    source_files=('nodes.csv.gz','edges.csv.gz','drive_arcs.csv.gz','drive_distance_graph.npz',
                  'runtime_parameters.json','od/manifest.json','od/origins.geojson','od/destinations.geojson')
    policy={'version':POLICY_VERSION,'description':'Modelled directed private-car approximation; not observed taxi routes or fully verified car legality',
        'eligible_edges':'edge_type=road AND (drive_forward OR drive_reverse) AND NOT lower(trim(fclass)).startswith(busway)',
        'direction':'Preserve saved drive flags/arcs exactly; no reverse permission invented',
        'grade':'Preserve source node IDs/layer/bridge/tunnel topology; never join geometric crossings or coincident XY nodes',
        'snap':'Actual OD coordinates; nearest eligible straight segment; exact distance ties by lexicographic edge_id; no reachable-component preference',
        'max_snap_m':float(max_snap_m),'max_snap_status':'assumption',
        'endpoint_tolerance_m':ENDPOINT_TOLERANCE_M,
        'routing':'Directional partial origin/destination segment costs and explicit direct same-segment option; nine reverse virtual-sink shortest-distance searches',
        'distance_excludes_snap_displacement':True,'degenerate_segment_snap':'Zero-extent segments retained as graph links but excluded as snap targets',
        'limitations':['Detailed private/access/motor_vehicle restrictions are absent from saved bus-oriented inputs.',
            'Turn restrictions, time-dependent restrictions, taxi observations and parking/dropoff legality are not modelled.',
            'Original assumed endpoint/grade transitions are retained, not independently verified.',
            'OD coordinates have no grade; coincident geometric grade ties select one source edge deterministically without connecting levels.',
            'No path recovery by farther snapping, straight-line substitution or another component.']}
    counts=dict(Counter(r['status'] for r in rows));physical_counts=dict(Counter(r['status'] for r in physical.values()))
    manifest={'supplement_version':'od_car_distances_v1','retrieved_at_utc':datetime.now(timezone.utc).isoformat(),
        'bundle_hash':model['manifest']['bundle_hash'],'artifact_version':model['manifest']['artifact_version'],
        'od_hash':model['od']['od_hash'],'model_version':routing.baseline_request(model).model_version,
        'od_set_id':routing.baseline_request(model).od_set_id,'bundle_manifest_sha256':sha_file(root/'manifest.json'),
        'input_sha256':{name:sha_file(root/name) for name in source_files},
        'source_graph':{'file':'drive_distance_graph.npz','sha256':sha_file(root/'drive_distance_graph.npz'),'purpose':'saved bus-oriented directed drive-distance graph'},
        'filtered_car_graph':network.summary,'crs':crs.to_string(),'coordinate_crs':'EPSG:4326',
        'units':{'internal_distance':'m','car_distance_km':'km','snap_m':'m','origin_snap_m':'m','destination_snap_m':'m'},
        'policy':policy,'policy_sha256':hashlib.sha256(canonical(policy)).hexdigest(),
        'physical_pair_count':len(physical),'physical_distances_calculated_once':True,'profile_row_count':len(rows),
        'physical_status_counts':physical_counts,'profile_status_counts':counts,'evaluator_id_verification':id_checks,
        'profile_od_mapping_sha256':hashlib.sha256(canonical(references)).hexdigest(),
        'snap_records_sha256':hashlib.sha256(canonical(snap_records)).hexdigest(),'snap_records':snap_records,
        'successful_zero_distance_pairs':[{'origin_id':o,'destination_id':d,'reason':'coincident snapped position or zero-length directed network path; off-network displacement excluded'} for (o,d),r in physical.items() if r['car_distance_km']==0],
        'output_sha256':{'od_car_distances.csv':hashlib.sha256(csv_bytes).hexdigest()},'output_size_bytes':{'od_car_distances.csv':len(csv_bytes)},
        'runtime_seconds':time.perf_counter()-start,
        'implementation_sha256':sha_file(Path(__file__))}
    # Validate finite JSON before creating manifest; shortest-path Infinity never escapes.
    encoded=json.dumps(manifest,ensure_ascii=False,sort_keys=True,indent=2,allow_nan=False)+'\n'
    output.mkdir(parents=True,exist_ok=True)
    with csv_path.open('xb') as stream:stream.write(csv_bytes)
    with manifest_path.open('x',encoding='utf-8') as stream:stream.write(encoded)
    return manifest
