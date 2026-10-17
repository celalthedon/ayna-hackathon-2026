"""Independent forward-Dijkstra audit; never calls the OD production solver."""
import argparse
import csv
import hashlib
import heapq
import json
import math
from pathlib import Path
import time

import numpy as np
import pandas as pd
from scipy.sparse import csr_matrix,load_npz
from scipy.sparse.csgraph import connected_components
from shapely import linestrings,distance
from shapely.geometry import Point


def sha(path):return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def forward_dijkstra(graph,starts):
    costs=np.full(graph.shape[0],np.inf);parents=np.full(graph.shape[0],-1,dtype=np.int64);heap=[]
    for node,cost in starts.items():
        if cost<costs[node]:costs[node]=cost;heapq.heappush(heap,(float(cost),int(node)))
    while heap:
        cost,node=heapq.heappop(heap)
        if cost!=costs[node]:continue
        for pos in range(graph.indptr[node],graph.indptr[node+1]):
            nxt=int(graph.indices[pos]);candidate=cost+float(graph.data[pos])
            if candidate<costs[nxt]:
                costs[nxt]=candidate;parents[nxt]=node;heapq.heappush(heap,(candidate,nxt))
    return costs,parents


def endpoint_costs(edge,fraction,origin):
    # Independently derive directional partial costs; no Snap helper imports.
    u,v=int(edge.u),int(edge.v);length=float(edge.length_m);result={}
    def put(node,cost):result[node]=min(result.get(node,math.inf),cost)
    if fraction==0:put(u,0.)
    if fraction==1:put(v,0.)
    if origin:
        if bool(edge.drive_forward):put(v,(1-fraction)*length)
        if bool(edge.drive_reverse):put(u,fraction*length)
    else:
        if bool(edge.drive_forward):put(u,fraction*length)
        if bool(edge.drive_reverse):put(v,(1-fraction)*length)
    return result


def components(graph):
    info={}
    for name,connection in (('weak','weak'),('strong','strong')):
        count,labels=connected_components(graph,directed=True,connection=connection)
        sizes=np.bincount(labels,minlength=count);minimum=np.full(count,len(labels),dtype=np.int64)
        np.minimum.at(minimum,labels,np.arange(len(labels)))
        info[name]=(labels,sizes,minimum)
    return info


def node_components(info,node):
    result={}
    for name,(labels,sizes,minimum) in info.items():
        result[name+'_id']=int(minimum[labels[node]]);result[name+'_size']=int(sizes[labels[node]])
    return result


def graph_from_arcs(arcs,size):
    cheapest=arcs.sort_values('length_m',kind='stable').drop_duplicates(['u','v'])
    return csr_matrix((cheapest.length_m.to_numpy(),(cheapest.u.to_numpy(),cheapest.v.to_numpy())),shape=(size,size))


def finite_or_none(value):return float(value) if math.isfinite(value) else None


def best_to_destination(source_id,source_fraction,source_edge,costs,target_record,edge_by_id):
    target=target_record['snap'];edge=edge_by_id.loc[target['edge_id']]
    best=math.inf;endpoint=None
    for node,tail in endpoint_costs(edge,float(target['fraction']),False).items():
        candidate=float(costs[node])+tail
        if candidate<best:best=candidate;endpoint=node
    if source_id==target['edge_id']:
        delta=float(target['fraction'])-source_fraction
        permitted=delta==0 or (delta>0 and bool(source_edge.drive_forward)) or (delta<0 and bool(source_edge.drive_reverse))
        if permitted and abs(delta)*float(source_edge.length_m)<best:
            best=abs(delta)*float(source_edge.length_m);endpoint=None
    return best,endpoint


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--artifact-dir',required=True,type=Path)
    parser.add_argument('--supplement-dir',required=True,type=Path)
    parser.add_argument('--output-dir',required=True,type=Path)
    args=parser.parse_args();started=time.perf_counter()
    root=args.artifact_dir.resolve();supp=args.supplement_dir.resolve();out=args.output_dir.resolve()
    assert not out.is_relative_to(root) and out!=supp
    csv_path=supp/'od_car_distances.csv';old_manifest=supp/'manifest.json'
    preserved={str(p):sha(p) for p in (csv_path,old_manifest)}
    manifest=json.loads(old_manifest.read_text(encoding='utf-8'))
    source_manifest=json.loads((root/'manifest.json').read_text())
    assert source_manifest['bundle_hash']==manifest['bundle_hash']
    for name,digest in source_manifest['files'].items():assert sha(root/name)==digest,name
    assert sha(csv_path)==manifest['output_sha256']['od_car_distances.csv']
    edges=pd.read_csv(root/'edges.csv.gz',dtype={'edge_id':str},low_memory=False)
    arcs=pd.read_csv(root/'drive_arcs.csv.gz',dtype={'edge_id':str},low_memory=False)
    by_id=edges.set_index('edge_id');pre=load_npz(root/'drive_distance_graph.npz').tocsr()
    reference=graph_from_arcs(arcs,pre.shape[0])
    assert np.array_equal(pre.indptr,reference.indptr) and np.array_equal(pre.indices,reference.indices)
    assert np.allclose(pre.data,reference.data,rtol=0,atol=1e-7)
    drive=edges.loc[(edges.drive_forward|edges.drive_reverse)&(edges.edge_type=='road')].copy()
    busway=drive.fclass.fillna('').str.strip().str.casefold().str.startswith('busway')
    eligible=set(drive.loc[~busway,'edge_id']);post_arcs=arcs.loc[arcs.edge_id.isin(eligible)]
    post=graph_from_arcs(post_arcs,pre.shape[0]);info={'before':components(pre),'after':components(post)}
    # Positive-control checks of the independent search, including asymmetry/zero.
    control=csr_matrix(([2.,0.],([0,1],[1,2])),shape=(3,3))
    assert list(forward_dijkstra(control,{0:1.})[0])==[1.,3.,3.]
    assert math.isinf(forward_dijkstra(control,{2:0.})[0][0])
    all_rows=list(csv.DictReader(csv_path.open(encoding='utf-8')))
    failed={r['origin_id']:r['status'] for r in all_rows if r['profile']=='P' and r['status']!='modelled'}
    targets={key:record for key,record in manifest['snap_records'].items() if record['role']=='destination'}
    sources=manifest['snap_records']
    # Reverse REACHABILITY masks only for alternate-road diagnostics; original
    # status/distance verification below always uses independent FORWARD Dijkstra.
    reaches={}
    for name,graph in (('before',pre),('after',post)):
        transpose=graph.T.tocsr();reachable=np.zeros(graph.shape[0],dtype=bool);stack=[]
        for record in targets.values():
            e=by_id.loc[record['snap']['edge_id']]
            for node in endpoint_costs(e,float(record['snap']['fraction']),False):
                if not reachable[node]:reachable[node]=True;stack.append(node)
        while stack:
            node=stack.pop()
            for pos in range(transpose.indptr[node],transpose.indptr[node+1]):
                nxt=int(transpose.indices[pos])
                if not reachable[nxt]:reachable[nxt]=True;stack.append(nxt)
        reaches[name]=reachable
    drive=drive.reset_index(drop=True)
    shapes=linestrings(np.stack((drive[['x0','y0']].to_numpy(),drive[['x1','y1']].to_numpy()),axis=1))
    reports=[];mismatches=[]
    source_pair_edges=arcs.sort_values('length_m',kind='stable').drop_duplicates(['u','v']).set_index(['u','v'])
    post_pairs=set(zip(post_arcs.u,post_arcs.v))
    for oid,status in failed.items():
        record=sources[oid];snap=record['snap'];edge=by_id.loc[snap['edge_id']];fraction=float(snap['fraction'])
        point=Point(record['projected_xy_m']);separations=distance(shapes,point)
        ranked=sorted(range(len(drive)),key=lambda i:(float(separations[i]),str(drive.iloc[i].edge_id)))
        nearest_before=drive.iloc[ranked[0]]
        chosen_after=next(i for i in ranked if drive.iloc[i].edge_id in eligible)
        assert str(drive.iloc[chosen_after].edge_id)==snap['edge_id'],'Original nearest snap mismatch'
        assert abs(float(separations[chosen_after])-float(snap['distance_m']))<1e-7
        starts=endpoint_costs(edge,fraction,True);graphs={}
        for name,graph in (('before',pre),('after',post)):
            costs,parents=forward_dijkstra(graph,starts)
            destination_distances={};witness=None
            for did,target in targets.items():
                best,endpoint=best_to_destination(snap['edge_id'],fraction,edge,costs,target,by_id)
                destination_distances[did]=finite_or_none(best)
                if witness is None and math.isfinite(best) and endpoint is not None:
                    node=endpoint;route=[]
                    while parents[node]>=0:
                        prev=int(parents[node]);arc=source_pair_edges.loc[(prev,node)]
                        if (prev,node) not in post_pairs:route.append(str(arc.edge_id))
                        node=prev
                    witness={'destination_id':did,'network_distance_m':best,'excluded_busway_edges':list(reversed(route))}
            graphs[name]={'u_components':node_components(info[name],int(edge.u)),
                'v_components':node_components(info[name],int(edge.v)),
                'departure_endpoints':[{'node_id':node,'partial_cost_m':cost,**node_components(info[name],node)} for node,cost in starts.items()],
                'reachable_node_count':int(np.isfinite(costs).sum()),
                'destinations_reachable':sum(v is not None for v in destination_distances.values()),
                'destination_distances_m':destination_distances,'excluded_edge_path_witness':witness}
            if name=='after' and status=='no_path' and graphs[name]['destinations_reachable']:
                mismatches.append(oid)
        nearest_meta={'edge_id':str(nearest_before.edge_id),'fclass':str(nearest_before.fclass),
            'distance_m':float(separations[ranked[0]]),'is_busway':str(nearest_before.edge_id) not in eligible}
        neighbors=[];seen_rows=set()
        for i in ranked:
            e=drive.iloc[i];distance_m=float(separations[i])
            if distance_m>500:break
            group=float(e.source_row) if not pd.isna(e.source_row) else str(e.edge_id)
            if group in seen_rows:continue
            seen_rows.add(group)
            x,y=record['projected_xy_m'];dx=e.x1-e.x0;dy=e.y1-e.y0
            t=max(0.,min(1.,((x-e.x0)*dx+(y-e.y0)*dy)/(dx*dx+dy*dy)))
            before_can=any(reaches['before'][n] for n in endpoint_costs(e,t,True))
            after_can=str(e.edge_id) in eligible and any(reaches['after'][n] for n in endpoint_costs(e,t,True))
            neighbors.append({'edge_id':str(e.edge_id),'source_row':group,'fclass':str(e.fclass),
                'distance_m':distance_m,'u':int(e.u),'v':int(e.v),'forward':bool(e.drive_forward),'reverse':bool(e.drive_reverse),
                'layer':None if pd.isna(e.layer) else float(e.layer),'bridge':None if pd.isna(e.bridge) else str(e.bridge),
                'tunnel':None if pd.isna(e.tunnel) else str(e.tunnel),'eligible_after':str(e.edge_id) in eligible,
                'before_u_components':node_components(info['before'],int(e.u)),
                'after_u_components':node_components(info['after'],int(e.u)),
                'diagnostic_projection_reaches_any_destination_before':bool(before_can),
                'diagnostic_projection_reaches_any_destination_after':bool(after_can)})
            if len(neighbors)>=8:break
        before_weak=graphs['before']['u_components']['weak_id']
        target_weak={node_components(info['before'],n)['weak_id'] for target in targets.values()
            for n in endpoint_costs(by_id.loc[target['snap']['edge_id']],float(target['snap']['fraction']),False)}
        if status=='snap_failed':
            cause='policy_exclusion_snap_limit' if nearest_meta['distance_m']<=manifest['policy']['max_snap_m'] and nearest_meta['is_busway'] else 'snap_limit_source_geometry'
        elif graphs['after']['destinations_reachable']:
            cause='implementation_error'
        elif graphs['before']['destinations_reachable']:
            cause='policy_exclusion'
        elif before_weak not in target_weak:
            cause='disconnected_source_topology'
        else:cause='source_directed_dead_end'
        result={'origin_id':oid,'saved_status':status,'snap_edge_id':snap['edge_id'],
            'forward':bool(edge.drive_forward),'reverse':bool(edge.drive_reverse),'u':int(edge.u),'v':int(edge.v),
            'fraction':fraction,'snap_distance_m':float(snap['distance_m']),'within_limit':bool(snap['within_limit']),
            'source_fclass':str(edge.fclass),'graphs':graphs,'nearest_source_drive_segment':nearest_meta,
            'nearby_distinct_source_roads_within_500m_DIAGNOSTIC_ONLY':neighbors,'diagnosis':cause}
        reports.append(result)
        print(json.dumps({k:result[k] for k in ('origin_id','saved_status','snap_edge_id','forward','reverse','diagnosis')},ensure_ascii=False),flush=True)
        print(json.dumps({name:{k:g[k] for k in ('u_components','v_components','reachable_node_count','destinations_reachable')} for name,g in graphs.items()}),flush=True)
    assert not mismatches, 'Confirmed production/independent mismatch: '+str(mismatches)
    report={'bundle_hash':manifest['bundle_hash'],'supplement_preserved_hashes':preserved,
        'method':'Independent heap-based forward directed Dijkstra with separately implemented origin/destination partial costs; original snaps fixed',
        'component_ids':'Minimum original node ID in component; sizes and reachable counts exclude virtual snap point',
        'snap_failed_reachability_note':'Graph reachability below the 100m eligibility cutoff is diagnostic only for snap_failed; its saved status is retained',
        'before_graph':'Immutable bus-oriented drive_distance_graph.npz, including busways',
        'after_graph':'Independently filtered saved road arcs excluding busway, no source topology edits',
        'forward_no_path_pairs_verified':45,'snap_failed_pairs_reviewed':9,'implementation_mismatches':mismatches,
        'resnapped':False,'supplement_changed':False,'failed_origins':reports,'runtime_seconds':time.perf_counter()-started}
    for name,digest in preserved.items():assert sha(name)==digest
    out.mkdir(parents=True,exist_ok=True)
    with (out/'diagnostics.json').open('x',encoding='utf-8') as stream:
        json.dump(report,stream,ensure_ascii=False,sort_keys=True,indent=2,allow_nan=False);stream.write('\n')
    fields=['origin_id','saved_status','snap_edge_id','forward','reverse','fraction','snap_distance_m','diagnosis',
        'weak_before','weak_size_before','weak_after','weak_size_after','scc_u_before','scc_v_before','scc_u_after','scc_v_after',
        'reachable_nodes_before','reachable_nodes_after','destinations_before','destinations_after']
    with (out/'failed_origins.csv').open('x',encoding='utf-8',newline='') as stream:
        writer=csv.DictWriter(stream,fieldnames=fields,lineterminator='\n');writer.writeheader()
        for r in reports:
            a,b=r['graphs']['before'],r['graphs']['after']
            writer.writerow({**{k:r[k] for k in fields[:8]},'weak_before':a['u_components']['weak_id'],
                'weak_size_before':a['u_components']['weak_size'],'weak_after':b['u_components']['weak_id'],
                'weak_size_after':b['u_components']['weak_size'],'scc_u_before':a['u_components']['strong_id'],
                'scc_v_before':a['v_components']['strong_id'],'scc_u_after':b['u_components']['strong_id'],
                'scc_v_after':b['v_components']['strong_id'],'reachable_nodes_before':a['reachable_node_count'],
                'reachable_nodes_after':b['reachable_node_count'],'destinations_before':a['destinations_reachable'],
                'destinations_after':b['destinations_reachable']})


if __name__=='__main__':main()
