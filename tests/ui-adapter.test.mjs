import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import {setTimeout as delay} from 'node:timers/promises';
import {buildRequest,journeyLegs,projectCoordinate,RoutingController,fetchJSON} from '../web/static/citypilot/routing-adapter.js';
import {Playback} from '../web/static/citypilot/playback.js';

const ready={contract_version:'1.0',model_version:'test-bound-model',od_set_id:'fixed-od',closure_id:'closure'};
const catalog={...ready,service_groups:{SG_R2:{},SG_R14:{}},prebuilt_services:{six:{pattern_ids:['east','west']},nine:{pattern_ids:['east','west']}},patterns:[{pattern_id:'east',route_id:'M1',direction_id:'A'},{pattern_id:'west',route_id:'M1',direction_id:'B'}]};
const selection={scenario:'disrupted',profile:'P',origin:'saved-o',destination:'saved-d',headways:{SG_R2:'6'},services:{M1:'six'}};
const meta={center:[49.84,40.4],transform:{radius_m:6378137}};
const provenance=[{source_id:'fixture',status:'assumption',source:'test only',evidence:'Synthetic adapter unit fixture',synthetic:true}];
const line=(a,b)=>({type:'LineString',coordinates:[a,b]});
const leg=(geometry,minutes=1,mode='walk')=>({geometry,mode,walk_min:mode==='walk'?minutes:0,wait_min:0,ride_min:mode==='bus'?minutes:0,transfer_min:mode==='transfer'?minutes:0,route_id:mode==='bus'?'R2':null,provenance});
const a=[49.84,40.4],b=[49.841,40.4],c=[49.842,40.4],d=[49.843,40.4];
const result=(request,extra={})=>({...ready,state:request.state,profile:request.profile,config_hash:request.state+'-'+request.profile,...extra});

test('closure semantics, catalogue identities, exact fields and exclusive variants',()=>{
  const disrupted=buildRequest(ready,catalog,selection);assert.equal(disrupted.closure_id,'closure');assert.deepEqual(disrupted.patches,[]);
  const normal=buildRequest(ready,catalog,{...selection,scenario:'normal',profile:'B'});assert.equal(normal.closure_id,null);assert.deepEqual(normal.patches,[]);
  const mitigated=buildRequest(ready,catalog,{...selection,scenario:'mitigated'});
  assert.deepEqual(mitigated.patches,[{kind:'set_service_headway',target_id:'SG_R2',headway_min:6},{kind:'activate_service',target_id:'six',headway_min:null}]);
  assert.deepEqual(Object.keys(mitigated).sort(),['candidate_ids','cap_min','closure_id','contract_version','headway_factor_by_group','model_version','od_set_id','patches','primary_t_min','profile','speed_factor','state','thresholds_min'].sort());
  assert.throws(()=>buildRequest(ready,catalog,{...selection,scenario:'mitigated',services:{M1:'six',other:'nine'}}),/exclusive/);
  assert.throws(()=>buildRequest(ready,{...catalog,model_version:'wrong'},selection),/identity/);
  assert.throws(()=>buildRequest(ready,catalog,{...selection,scenario:'mitigated',services:{M1:'invented'}}),/Unknown/);
});

test('physical time survives layer height, stationary wait, dwell and gap pauses',()=>{
  const wait={...leg({type:'Point',coordinates:b},0,'bus'),wait_min:2};
  const dwell=leg({type:'Point',coordinates:c},25/60,'bus');
  const journey={status:'reachable',total_min:1+2+1+25/60,legs:[leg(line(a,b)),wait,leg(line(c,d),1,'bus'),{...dwell,geometry:{type:'Point',coordinates:d}}]};
  const legs=journeyLegs(journey,meta),play=new Playback(legs);
  assert.ok(Math.abs(play.duration-journey.total_min*60)<1e-9);
  assert.equal(legs.filter(l=>l.gap).length,1);
  play.seek(61);assert.equal(play.current().leg.mode,'wait');const stationary=play.current().position;play.toggle();play.tick(30);assert.deepEqual(play.current().position,stationary);
  play.tick(200);assert.ok(play.blockedGap);assert.equal(play.elapsed,180);assert.equal(play.playing,false);assert.equal(play.current().position,null);
  play.skipGap();play.tick(30);assert.equal(play.current().leg.mode,'bus');
  const seconds=play.duration;for(const l of play.legs)l.displayHeight=10000;assert.equal(play.duration,seconds);
  play.seek(play.duration-10);assert.match(play.current().leg.title,/modeldə verilmiş dayanma/);assert.equal(play.current().leg.stationary,true);
});

test('MultiLineString pieces never gain connectors; duration remains physical',()=>{
  const journey={status:'reachable',total_min:4,legs:[leg({type:'MultiLineString',coordinates:[[a,b],[c,d]]},4)]};
  const legs=journeyLegs(journey,meta),play=new Playback(legs);assert.equal(legs.length,3);assert.equal(legs[1].gap,true);assert.equal(play.duration,240);
  assert.deepEqual(legs[0].geometry.at(-1),projectCoordinate(b,meta));assert.deepEqual(legs[2].geometry[0],projectCoordinate(c,meta));
  assert.throws(()=>journeyLegs({...journey,total_min:5},meta),/leg sum/);
  assert.deepEqual(journeyLegs({status:'no_path'},meta),[]);
  const empty=new Playback();empty.toggle();assert.equal(empty.playing,false);assert.equal(empty.current().position,null);
});

test('even sub-centimetre source gaps are disclosed and moving waits are rejected',()=>{
  const near=[b[0]+1e-9,b[1]];
  const tinyGap=journeyLegs({status:'reachable',total_min:2,legs:[leg(line(a,b)),leg(line(near,c))]},meta);
  assert.equal(tinyGap.filter(l=>l.gap).length,1);
  assert.throws(()=>journeyLegs({status:'reachable',total_min:1,legs:[{...leg(line(a,b),0),wait_min:1}]},meta),/stationary timing/);
});

test('pause, seek, speed, restart and explicit gap acknowledgement',()=>{
  const p=new Playback([{id:'one',mode:'walk',seconds:60,geometry:[[0,0],[10,0]]},{id:'gap',gap:true,seconds:0},{id:'two',mode:'walk',seconds:60,geometry:[[20,0],[30,0]]}]);
  p.speed=2;p.toggle();p.tick(10);assert.equal(p.elapsed,20);p.toggle();p.tick(10);assert.equal(p.elapsed,20);
  p.seek(50);p.toggle();p.tick(10);assert.equal(p.elapsed,60);assert.ok(p.blockedGap);p.skipGap();p.tick(30);assert.equal(p.elapsed,120);assert.equal(p.playing,false);
  p.restart();assert.equal(p.elapsed,0);assert.equal(p.speed,2);assert.equal(p.handled.size,0);
});

test('late evaluation discarded; changes queued without overlapping work',async()=>{
  let release,active=0,max=0;const calls=[],evaluations=[],journeys=[];
  const fetcher=async(url,request)=>{calls.push({url,request});active++;max=Math.max(max,active);if(calls.length===1)await new Promise(r=>release=r);active--;return result(request,url.includes('inspect')?{origin_id:'saved-o',destination_id:'saved-d'}:{});};
  const controller=new RoutingController({ready,catalog,delay:1,fetcher,onStatus:()=>{},onEvaluation:r=>evaluations.push(r),onJourney:r=>journeys.push(r)});
  controller.select(selection,{immediate:true});await delay(15);controller.select({...selection,scenario:'normal'});await delay(15);release();await delay(25);
  assert.equal(max,1);assert.equal(calls.length,3);assert.equal(evaluations.length,1);assert.equal(evaluations[0].state,'normal');assert.equal(journeys.length,1);controller.dispose();
});

test('late journey ignored; OD-only changes reuse current evaluation',async()=>{
  let release;const calls=[],journeys=[];
  const controller=new RoutingController({ready,catalog,delay:1,onStatus:()=>{},onEvaluation:()=>{},onJourney:r=>journeys.push(r),
    fetcher:async(url,request)=>{calls.push(url);if(calls.length===2)await new Promise(r=>release=r);const params=new URL('http://fixture/'+url).searchParams;return result(request,url.includes('inspect')?{origin_id:params.get('origin_id'),destination_id:params.get('destination_id')}:{});}});
  controller.select(selection,{immediate:true});await delay(15);controller.select({...selection,origin:'another-saved-o'});await delay(10);release();await delay(25);
  assert.equal(calls.filter(c=>c.includes('evaluate')).length,1);assert.equal(calls.filter(c=>c.includes('inspect')).length,2);assert.equal(journeys.length,1);assert.equal(journeys[0].origin_id,'another-saved-o');controller.dispose();
});

test('debounce, repeated choices, 429 and disposal do not create retry storms',async()=>{
  let calls=0;const statuses=[];
  const controller=new RoutingController({ready,catalog,delay:15,onStatus:(...s)=>statuses.push(s),onEvaluation:()=>{},onJourney:()=>{},fetcher:async()=>{calls++;const e=Error('busy');e.status=429;throw e;}});
  for(let i=0;i<5;i++)controller.select({...selection,origin:'saved-'+i});
  await delay(45);assert.equal(calls,1);assert.equal(statuses.at(-1)[0],'busy');
  controller.select({...selection,origin:'saved-4'});await delay(25);assert.equal(calls,1);
  controller.select(selection);controller.dispose();await delay(25);assert.equal(calls,1);
});

test('HTTP errors preserve structured busy status; unreadable responses fail',async()=>{
  await assert.rejects(fetchJSON('/fixture',{},async()=>({ok:false,status:429,json:async()=>({error:{code:'routing_busy',message:'wait'}})})),e=>e.status===429&&e.code==='routing_busy');
  await assert.rejects(fetchJSON('/fixture',undefined,async()=>({json:async()=>{throw Error();}})),/unreadable JSON/);
  await assert.rejects(fetchJSON('/fixture',undefined,async()=>{const e=Error();e.name='TimeoutError';throw e;}),/may still be busy/);
});

test('shipped assets use local same-origin URLs and no synthetic journey generator',()=>{
  const html=fs.readFileSync(new URL('../web/citypilot.html',import.meta.url),'utf8');
  assert.doesNotMatch(html,/file:\/\/|src="https?:|href="https?:\/\/.*\.css/);
  assert.equal([...html.matchAll(/id="([^"]+)"/g)].length,new Set([...html.matchAll(/id="([^"]+)"/g)].map(m=>m[1])).size);
  for(const name of ['app.js','playback.js','routing-ui.js'])assert.doesNotMatch(fs.readFileSync(new URL('../web/static/citypilot/'+name,import.meta.url),'utf8'),/demoLegs/);
});

test('all literal DOM references and local entry-point assets exist',()=>{
  const html=fs.readFileSync(new URL('../web/citypilot.html',import.meta.url),'utf8');
  const ids=new Set([...html.matchAll(/id="([^"]+)"/g)].map(m=>m[1]));ids.add('fallback-marker'); // created by the SVG renderer
  for(const file of ['app.js','routing-ui.js']) {
    const source=fs.readFileSync(new URL('../web/static/citypilot/'+file,import.meta.url),'utf8');
    for(const match of source.matchAll(/\$\('([^']+)'\)/g))assert.ok(ids.has(match[1]),file+': '+match[1]);
  }
  for(const match of html.matchAll(/(?:src|href)="\.\/citypilot-assets\/([^"]+)"/g))assert.ok(fs.existsSync(new URL('../web/static/'+match[1],import.meta.url)),match[1]);
});
