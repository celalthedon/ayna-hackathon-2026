/** Read-only derivation of the existing pilot. Node built-ins only; no downloads. */
import fs from 'node:fs';
import path from 'node:path';
import zlib from 'node:zlib';
import crypto from 'node:crypto';
import {fileURLToPath} from 'node:url';

export const sha = b => crypto.createHash('sha256').update(b).digest('hex');
export function csv(text) {
  const rows=[]; let row=[], field='', quoted=false;
  for(let i=0;i<text.length;i++) {
    const c=text[i];
    if(c==='"') { if(quoted&&text[i+1]==='"'){field+='"';i++;}else quoted=!quoted; }
    else if(!quoted&&(c===','||c==='\n')) {row.push(field.replace(/\r$/,''));field='';if(c==='\n'){rows.push(row);row=[];}}
    else field+=c;
  }
  if(field||row.length){row.push(field.replace(/\r$/,''));rows.push(row);}
  const headers=rows.shift();return rows.filter(r=>r.length===headers.length).map(r=>Object.fromEntries(headers.map((h,i)=>[h,r[i]])));
}
// WGS84 inverse transverse Mercator, fixed UTM zone 39N (the model's EPSG:32639).
// This is used only to display saved metric access nodes; routing uses pyproj unchanged.
export function utm39([east,north]) {
  const a=6378137,e2=0.0066943799901413165,k=.9996,e1=(1-Math.sqrt(1-e2))/(1+Math.sqrt(1-e2));
  const mu=north/k/(a*(1-e2/4-3*e2**2/64-5*e2**3/256));
  const f=mu+(3*e1/2-27*e1**3/32)*Math.sin(2*mu)+(21*e1**2/16-55*e1**4/32)*Math.sin(4*mu)+151*e1**3/96*Math.sin(6*mu)+1097*e1**4/512*Math.sin(8*mu);
  const ep=e2/(1-e2),C=ep*Math.cos(f)**2,T=Math.tan(f)**2,N=a/Math.sqrt(1-e2*Math.sin(f)**2),R=a*(1-e2)/(1-e2*Math.sin(f)**2)**1.5,D=(east-500000)/(N*k);
  const lat=f-N*Math.tan(f)/R*(D**2/2-(5+3*T+10*C-4*C*C-9*ep)*D**4/24+(61+90*T+298*C+45*T*T-252*ep-3*C*C)*D**6/720);
  const lon=(D-(1+2*T+C)*D**3/6+(5-2*C+28*T-3*C*C+8*ep+24*T*T)*D**5/120)/Math.cos(f);
  return [51+lon*180/Math.PI,lat*180/Math.PI];
}
export function zipEntries(buffer) {
  let end=buffer.length-22;while(end>=0&&buffer.readUInt32LE(end)!==0x06054b50)end--;
  if(end<0)throw Error('Missing ZIP directory');
  const entries=new Map();let off=buffer.readUInt32LE(end+16);
  while(buffer.readUInt32LE(off)===0x02014b50) {
    const nl=buffer.readUInt16LE(off+28),el=buffer.readUInt16LE(off+30),cl=buffer.readUInt16LE(off+32);
    const name=buffer.subarray(off+46,off+46+nl).toString(),size=buffer.readUInt32LE(off+20),local=buffer.readUInt32LE(off+42),method=buffer.readUInt16LE(off+10);
    entries.set(name,()=>{const start=local+30+buffer.readUInt16LE(local+26)+buffer.readUInt16LE(local+28),data=buffer.subarray(start,start+size);if(method===0)return data;if(method===8)return zlib.inflateRawSync(data);throw Error('Unsupported ZIP method');});
    off+=46+nl+el+cl;
  }
  return entries;
}
function dbf(buffer) {
  const fields=[];for(let off=32;buffer[off]!==13;off+=32)fields.push({name:buffer.subarray(off,off+11).toString().replace(/\0.*/,''),length:buffer[off+16]});
  const start=buffer.readUInt16LE(8),size=buffer.readUInt16LE(10);
  return index=>{let off=start+index*size+1;return Object.fromEntries(fields.map(f=>{const value=buffer.subarray(off,off+f.length).toString('utf8').trim();off+=f.length;return[f.name,value];}));};
}
export function* shapes(buffer,attributes,bbox) {
  let index=0;
  for(let off=100;off<buffer.length;index++) {
    const size=buffer.readUInt32BE(off+4)*2,start=off+8;off=start+size;
    const type=buffer.readInt32LE(start);if(type!==3&&type!==5)continue;
    const b=[0,1,2,3].map(i=>buffer.readDoubleLE(start+4+i*8));
    if(b[2]<bbox[0]||b[0]>bbox[2]||b[3]<bbox[1]||b[1]>bbox[3])continue;
    const count=buffer.readUInt32LE(start+36),points=buffer.readUInt32LE(start+40),base=start+44+count*4;
    const begins=Array.from({length:count},(_,i)=>buffer.readUInt32LE(start+44+i*4));begins.push(points);
    const parts=begins.slice(0,-1).map((n,i)=>Array.from({length:begins[i+1]-n},(_,j)=>[buffer.readDoubleLE(base+(n+j)*16),buffer.readDoubleLE(base+(n+j)*16+8)]));
    yield {index,parts,properties:attributes(index),type};
  }
}
export function clipLine(points,b) {
  const pieces=[];let current=[];
  for(let i=1;i<points.length;i++) {
    const a=points[i-1],c=points[i],dx=c[0]-a[0],dy=c[1]-a[1];let low=0,high=1,ok=true;
    for(const [p,q] of [[-dx,a[0]-b[0]],[dx,b[2]-a[0]],[-dy,a[1]-b[1]],[dy,b[3]-a[1]]]) {
      if(p===0){if(q<0)ok=false;continue;}const r=q/p;if(p<0)low=Math.max(low,r);else high=Math.min(high,r);
    }
    if(!ok||low>high){if(current.length>1)pieces.push(current);current=[];continue;}
    const p=[a[0]+low*dx,a[1]+low*dy],q=[a[0]+high*dx,a[1]+high*dy];
    if(current.length&&Math.hypot(current.at(-1)[0]-p[0],current.at(-1)[1]-p[1])>1e-10){if(current.length>1)pieces.push(current);current=[];}
    if(!current.length)current.push(p);current.push(q);
  }
  if(current.length>1)pieces.push(current);return pieces;
}
function clipRing(ring,b) {
  let out=ring;for(const [axis,bound,sign] of [[0,b[0],1],[0,b[2],-1],[1,b[1],1],[1,b[3],-1]]) {
    const input=out;out=[];if(!input.length)break;
    for(let i=0;i<input.length;i++){const a=input[(i+input.length-1)%input.length],c=input[i],inside=p=>sign*(p[axis]-bound)>=0;
      if(inside(a)!==inside(c)){const t=(bound-a[axis])/(c[axis]-a[axis]);out.push([a[0]+t*(c[0]-a[0]),a[1]+t*(c[1]-a[1])]);}
      if(inside(c))out.push(c);
    }
  }return out;
}
// Iterative Douglas-Peucker in scene metres, visual copies only.
export function simplify(p,tolerance) {
  if(p.length<3)return p;const keep=new Set([0,p.length-1]),stack=[[0,p.length-1]];
  while(stack.length){const[a,b]=stack.pop(),u=p[a],v=p[b],dx=v[0]-u[0],dy=v[1]-u[1],length=dx*dx+dy*dy;let best=tolerance*tolerance,index=-1;
    for(let i=a+1;i<b;i++){const t=length?Math.max(0,Math.min(1,((p[i][0]-u[0])*dx+(p[i][1]-u[1])*dy)/length)):0,d=(p[i][0]-u[0]-t*dx)**2+(p[i][1]-u[1]-t*dy)**2;if(d>best){best=d;index=i;}}
    if(index>=0){keep.add(index);stack.push([a,index],[index,b]);}
  }return [...keep].sort((a,b)=>a-b).map(i=>p[i]);
}
export function build(bundle,config,osm,out) {
  const manifest=JSON.parse(fs.readFileSync(path.join(bundle,'manifest.json')));
  const read=n=>fs.readFileSync(path.join(bundle,n));
  for(const [n,h] of Object.entries(manifest.files))if(sha(read(n))!==h)throw Error('Bundle payload mismatch: '+n);
  const pythonJSON='{'+Object.keys(manifest.files).sort().map(k=>JSON.stringify(k)+': '+JSON.stringify(manifest.files[k])).join(', ')+'}';
  if(sha(pythonJSON)!==manifest.bundle_hash)throw Error('Bundle identity mismatch');
  const sm=JSON.parse(fs.readFileSync(path.join(config,'prebuilt_services/manifest.json')));
  if(sm.bundle_hash!==manifest.bundle_hash)throw Error('M bundle mismatch');
  for(const[n,h]of Object.entries(sm.files))if(sha(fs.readFileSync(path.join(config,'prebuilt_services',n)))!==h)throw Error('M payload mismatch');
  const assets=JSON.parse(fs.readFileSync(path.join(config,'prebuilt_services/assets.json')));
  const table=n=>csv(n.endsWith('.gz')?zlib.gunzipSync(read(n)).toString():read(n).toString()),features=n=>JSON.parse(read(n)).features;
  const nodes=table('nodes.csv.gz'),nodeMap=new Map(nodes.map(n=>[n.node_id,n]));
  let minX=Infinity,minY=Infinity,maxX=-Infinity,maxY=-Infinity;
  for(const n of nodes){minX=Math.min(minX,+n.x);minY=Math.min(minY,+n.y);maxX=Math.max(maxX,+n.x);maxY=Math.max(maxY,+n.y);}
  const corners=[[minX,minY],[maxX,minY],[minX,maxY],[maxX,maxY]].map(utm39);
  const bbox=[Math.min(...corners.map(p=>p[0])),Math.min(...corners.map(p=>p[1])),Math.max(...corners.map(p=>p[0])),Math.max(...corners.map(p=>p[1]))];
  const center=[(bbox[0]+bbox[2])/2,(bbox[1]+bbox[3])/2],R=6378137,deg=Math.PI/180;
  const project=p=>[Math.round((p[0]-center[0])*deg*R*Math.cos(center[1]*deg)*100)/100,Math.round(-(p[1]-center[1])*deg*R*100)/100];
  const mapNode=id=>{const n=nodeMap.get(String(id));if(!n)throw Error('Unknown display node '+id);return project(utm39([+n.x,+n.y]));};
  const result={meta:{schema_version:1,bundle_hash:manifest.bundle_hash,od_hash:manifest.od_hash,supplement_hash:sm.supplement_hash,center,bbox,metric_bounds:[minX,minY,maxX,maxY],transform:{name:'local-equirectangular-metres',radius_m:R,axes:'x east; z south; y illustrative height'},osmDate:'2026-10-16',license:'ODbL 1.0',attribution:'© OpenStreetMap contributors / Geofabrik',osm_sha256:sha(fs.readFileSync(osm)),illustrative_building_height_m:12},roads:[],buildings:[],parks:[],stations:[],metro:[],buses:[],stops:[],parking:[],exits:[],origins:[],destinations:[]};
  result.stations=features('stations.geojson').map(f=>({id:f.properties.station_id,name:f.properties.station_name,p:project(f.geometry.coordinates),review_status:f.properties.review_status}));
  const links=table('metro_links.csv.gz'),closure=links.find(l=>l.is_closure_link==='True');result.meta.closure_id=closure.link_id;
  result.metro=features('metro_routes.geojson').map(f=>({id:f.properties.link_id,from:f.properties.from_name,to:f.properties.to_name,p:f.geometry.coordinates.map(project),closed:f.properties.link_id===closure.link_id,review_status:f.properties.review_status}));
  for(const f of features('curated/bus_route_geometry.geojson')) {
    const props=f.properties,parts=f.geometry.type==='MultiLineString'?f.geometry.coordinates:[f.geometry.coordinates];
    for(let i=0;i<parts.length;i++)for(const[j,piece]of clipLine(parts[i],bbox).entries())result.buses.push({id:props.pattern_id+':'+i+':'+j,route:'R'+String(props.route).replace(/^R/,''),pattern_id:props.pattern_id,direction:props.direction,p:piece.map(project),source:props.source});
  }
  for(const item of assets.patterns)for(let i=0;i<item.segment_geometry.length;i++) {
    const g=item.segment_geometry[i];if(!g)continue;const parts=g.type==='MultiLineString'?g.coordinates:[g.coordinates];
    for(let j=0;j<parts.length;j++)result.buses.push({id:item.pattern.pattern_id+':'+i+':'+j,route:item.pattern.route_id,pattern_id:item.pattern.pattern_id,direction:item.pattern.direction_id,p:parts[j].map(project),source:'constructed M supplement; '+item.pattern.provenance.status});
  }
  result.stops=table('curated/bus_stops.csv').map(r=>({id:r.stop_id,name:r.name,p:project([+r.lon,+r.lat]),source:r.source}));
  result.stops.push(...assets.stops.map(r=>({id:r.stop_id,name:r.stop_id,p:project(r.coordinates),source:r.provenance.status})));
  result.exits=table('metro_exit_access.csv.gz').map(r=>({id:r.access_id,station_id:r.station_id,name:r.station_name+' · '+r.exit_name,p:mapNode(r.walk_node_id),source:'saved model street access node; schematic station access'}));
  result.parking=table('parking_access.csv.gz').map(r=>({id:r.parking_id,name:r.label,p:project(utm39([+r.source_x,+r.source_y])),source:'source-listed; operational availability assumed'}));
  for(const [key,id]of [['origins','origin_id'],['destinations','destination_id']])result[key]=features('od/'+key+'.geojson').map(f=>({id:f.properties[id],p:project(f.geometry.coordinates)}));
  const zip=zipEntries(fs.readFileSync(osm));
  for(const[kind,file]of [['roads','roads_free'],['buildings','buildings_a_free'],['parks','landuse_a_free']]) {
    const prefix='gis_osm_'+file+'_1',attributes=dbf(zip.get(prefix+'.dbf')());
    for(const f of shapes(zip.get(prefix+'.shp')(),attributes,bbox)) {
      if(kind==='parks'&&!['park','forest','grass','recreation_ground','meadow','nature_reserve'].includes(f.properties.fclass))continue;
      const id='osm:'+f.properties.osm_id+':'+f.index;
      if(kind==='roads')for(const [part,points]of f.parts.entries())for(const [piece,p]of clipLine(points,bbox).entries())result.roads.push({id:id+':'+part+':'+piece,kind:f.properties.fclass,p:simplify(p.map(project),1.5)});
      else {const rings=f.parts.map(r=>clipRing(r,bbox)).filter(r=>r.length>=4).map(r=>simplify(r.map(project),.6)).filter(r=>r.length>=4);if(rings.length)result[kind].push({id,rings});}
    }
  }
  result.meta.counts=Object.fromEntries(Object.entries(result).filter(([,v])=>Array.isArray(v)).map(([k,v])=>[k,v.length]));
  fs.writeFileSync(out,JSON.stringify(result));console.log(JSON.stringify({file:out,bytes:fs.statSync(out).size,meta:result.meta},null,2));
  return result;
}
if(process.argv[1]&&path.resolve(process.argv[1])===fileURLToPath(import.meta.url)) {
  if(process.argv.length!==6)throw Error('Usage: node tools/build_ui_map.mjs BUNDLE CONFIG OSM_ZIP OUTPUT_JSON');
  build(...process.argv.slice(2));
}
