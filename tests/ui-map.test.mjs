import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import zlib from 'node:zlib';
import {csv,clipLine,simplify,utm39,sha} from '../tools/build_ui_map.mjs';
import {projectCoordinate} from '../web/static/citypilot/routing-adapter.js';
const map=JSON.parse(fs.readFileSync(new URL('../web/static/citypilot/pilot-map.json',import.meta.url)));

test('complete pilot layers, stable IDs and independent directions',()=>{
  assert.equal(map.stations.length,15);assert.equal(map.exits.length,53);assert.equal(map.origins.length,302);assert.equal(map.destinations.length,9);assert.equal(map.parking.length,639);assert.equal(map.metro.filter(m=>m.closed).length,1);
  for(const key of ['stations','exits','origins','destinations','parking','roads','buildings','parks','buses'])assert.equal(new Set(map[key].map(i=>i.id)).size,map[key].length,key+' IDs');
  for(const route of ['R2','R14','M1','M2','M3','M5','M6'])for(const direction of ['A','B'])assert.ok(map.buses.some(b=>b.route===route&&b.direction===direction),route+direction);
  assert.ok(map.roads.length>40000);assert.ok(map.buildings.length>17000);assert.ok(map.parks.length>4000);
  assert.equal(map.meta.bundle_hash,'9457bfe95125b1d8bddb1be662ad6f0bbd1a00c0ac8f8abcc2fbecf872d53066');
});

test('CSV quoted newlines and escaping, line clipping without missing-piece bridges',()=>{
  assert.deepEqual(csv('a,b\n"x,y","z""w"\n"line\nnext",last\n'),[{a:'x,y',b:'z"w'},{a:'line\nnext',b:'last'}]);
  const clipped=clipLine([[-2,0],[0,0],[2,0],[2,2],[0,0]],[-1,-1,1,1]);assert.equal(clipped.length,2);assert.deepEqual(clipped[0],[[-1,0],[0,0],[1,0]]);
  assert.deepEqual(simplify([[0,0],[1,.1],[2,0]],.2),[[0,0],[2,0]]);
});

const bundle=process.env.CITYPILOT_TEST_BUNDLE;
test('saved station/OD coordinates use one transform; UTM display conversion agrees with saved exits',{skip:!bundle},()=>{
  const read=n=>JSON.parse(fs.readFileSync(bundle+'/'+n));
  for(const [name,id]of [['stations','station_id'],['od/origins','origin_id'],['od/destinations','destination_id']]) {
    const layer=name.split('/').at(-1);for(const f of read(name+'.geojson').features){const item=map[layer].find(i=>i.id===f.properties[id]),p=projectCoordinate(f.geometry.coordinates,map.meta);assert.ok(Math.hypot(p[0]-item.p[0],p[1]-item.p[1])<.008);}
  }
  const nodes=new Map(csv(zlib.gunzipSync(fs.readFileSync(bundle+'/nodes.csv.gz')).toString()).map(n=>[n.node_id,n]));
  for(const f of read('od/destinations.geojson').features){const n=nodes.get(String(f.properties.walk_node_id)),p=utm39([+n.x,+n.y]),q=f.geometry.coordinates;assert.ok(Math.hypot((p[0]-q[0])*85000,(p[1]-q[1])*111320)<.005);}
});

test('approved original and immutable payloads remain unchanged',{skip:!bundle},()=>{
  const manifest=JSON.parse(fs.readFileSync(bundle+'/manifest.json'));for(const[n,h]of Object.entries(manifest.files))assert.equal(sha(fs.readFileSync(bundle+'/'+n)),h,n);
  const original=process.env.CITYPILOT_APPROVED_HTML;if(original)assert.equal(sha(fs.readFileSync(original)),'eb4db9aef28fd2bf463bba0ec1ecd4aa9e6baa64bc961b5ed58634d5f402382b');
});
