import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import {modeLabel,summarizeLegs} from '../web/static/citypilot/journey-presentation.js';
import {journeyLegs} from '../web/static/citypilot/routing-adapter.js';
import {Playback} from '../web/static/citypilot/playback.js';

const walk=(id,a,b,seconds=30,extra={})=>({id,mode:'walk',title:'Piyada',layer:'surface',geometry:[a,b],seconds,...extra});
const a=[0,0],b=[10,0],c=[20,0],d=[30,0];

test('walking summaries preserve every playback leg, physical duration and seek mapping',()=>{
  const playback=new Playback([walk('one',a,b),walk('two',b,c),walk('three',c,d)]);
  const original=JSON.stringify(playback.legs),rows=summarizeLegs(playback.legs);
  assert.equal(rows.length,1);assert.equal(rows[0].title,'Piyada');assert.equal(rows[0].seconds,90);
  assert.deepEqual(rows[0].legIds,['one','two','three']);
  for(let i=0;i<3;i++)assert.strictEqual(rows[0].legs[i],playback.legs[i]);
  assert.equal(JSON.stringify(playback.legs),original);assert.equal(playback.duration,90);
  playback.seek(rows[0].start);assert.equal(playback.current().leg.id,'one');
  playback.seek(45);assert.equal(playback.current().leg.id,'two');assert.ok(rows[0].legIds.includes(playback.current().leg.id));
  assert.deepEqual(playback.current().position,[15,0]);
});

test('gaps, waits, mode/layer changes and incompatible endpoints remain separate',()=>{
  const cases=[
    [walk('one',a,b),{id:'gap',mode:'gap',gap:true,seconds:0,geometry:null,layer:'surface'},walk('two',b,c)],
    [walk('one',a,b),{id:'wait',mode:'wait',seconds:15,geometry:[b],layer:'surface'},walk('two',b,c)],
    [walk('one',a,b),walk('two',b,c,30,{layer:'metro'})],
    [walk('one',a,b),walk('two',[b[0]+1e-9,0],c)],
    [walk('one',a,b),walk('two',b,c,30,{mode:'bike'})],
    [walk('one',a,b,30,{physical:{to_id:'x'}}),walk('two',b,c,30,{physical:{from_id:'y'}})],
    [walk('one',a,b),walk('two',b,c,30,{physical:{wait_min:1}})],
  ];
  for(const legs of cases){const playback=new Playback(legs),rows=summarizeLegs(playback.legs);assert.equal(rows.length,legs.length);assert.equal(rows.reduce((s,r)=>s+r.seconds,0),playback.duration);}
  const playback=new Playback(cases[0]);playback.toggle();playback.tick(40);assert.equal(playback.blockedGap.id,'gap');assert.equal(playback.elapsed,30);
});

test('zero-time access legs can share a walking summary without changing timing',()=>{
  const playback=new Playback([walk('access',a,a,0),walk('road',a,b,60),walk('exit',b,b,0)]),rows=summarizeLegs(playback.legs);
  assert.equal(rows.length,1);assert.equal(rows[0].seconds,60);assert.equal(rows[0].legs.length,3);assert.equal(playback.current().leg.id,'road');
});

test('mode titles are Azerbaijani while original routing modes remain unchanged',()=>{
  assert.deepEqual(['walk','bike','bus','metro','transfer','wait'].map(modeLabel),['Piyada','Velosiped','Avtobus','Metro','Keçid','Gözləmə']);
  const raw={status:'reachable',total_min:2,legs:[{mode:'walk',geometry:{type:'LineString',coordinates:[[49.84,40.4],[49.841,40.4]]},walk_min:1,wait_min:0,ride_min:0,transfer_min:0,provenance:[]},{mode:'bus',route_id:'R2',geometry:{type:'Point',coordinates:[49.841,40.4]},walk_min:0,wait_min:1,ride_min:0,transfer_min:0,provenance:[]}]};
  const original=JSON.stringify(raw),legs=journeyLegs(raw,{center:[49.84,40.4],transform:{radius_m:6378137}});
  assert.equal(legs[0].title,'Piyada');assert.equal(legs[1].title,'Gözləmə · Avtobus · R2');assert.equal(legs[0].mode,'walk');assert.equal(JSON.stringify(raw),original);
});

test('user-facing assets are valid UTF-8 without mojibake or replacement characters',()=>{
  for(const file of ['web/citypilot.html','web/static/citypilot/app.js','web/static/citypilot/journey-presentation.js','web/static/citypilot/routing-adapter.js','web/static/citypilot/routing-ui.js','web/static/citypilot/playback.js']) {
    const text=new TextDecoder('utf-8',{fatal:true}).decode(fs.readFileSync(new URL('../'+file,import.meta.url)));
    assert.doesNotMatch(text,/\ufffd|Ã|Â|Ä|Å|É|â€|Æ/,file);
  }
});
