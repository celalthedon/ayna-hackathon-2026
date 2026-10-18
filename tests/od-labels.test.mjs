import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import {groupODOptions,odJourneyHeading} from '../web/static/citypilot/od-labels.js';
import {RoutingUI} from '../web/static/citypilot/routing-ui.js';

const map=JSON.parse(fs.readFileSync(new URL('../web/static/citypilot/pilot-map.json',import.meta.url)));
const flat=groups=>groups.flatMap(group=>group.options);
const origin=(id,properties={},coordinates)=>({id,properties,coordinates});

test('metro names use stable exit IDs rather than source ordering or duplicated IDs',()=>{
  const items=[origin('origin:metro_exit:31',{origin_kind:'metro_exit'}),origin('origin:metro_exit:1',{origin_kind:'metro_exit'})];
  const original=JSON.stringify(items),options=flat(groupODOptions(items,[...map.exits].reverse()));
  assert.equal(options.find(o=>o.value==='origin:metro_exit:31').label,'20 Yanvar · Çıxış 5');
  assert.equal(options.find(o=>o.value==='origin:metro_exit:1').label,'Avtovağzal · Çıxış 1');
  assert.equal(JSON.stringify(items),original);
  assert.ok(options.every(o=>!o.label.includes('origin:')));
});

test('destination metadata is preferred and exits sort numerically within stations',()=>{
  const items=[10,2,1].map(n=>origin('destination:metro_exit:'+n,{station_name:'Sahil',exit_name:'Çıxış '+n}));
  const groups=groupODOptions(items,[{id:'metro_exit:1',name:'Fallback name'}]);
  assert.equal(groups[0].label,'Metro çıxışları');
  assert.deepEqual(flat(groups).map(o=>o.label),['Sahil · Çıxış 1','Sahil · Çıxış 2','Sahil · Çıxış 10']);
});

test('terminal and network labels are concise, stable, grouped and coordinate-aware',()=>{
  const items=[origin('origin:grid:10',{origin_kind:'grid'}),origin('origin:terminal:baku_international',{origin_kind:'terminal'}),origin('origin:metro_exit:31'),origin('origin:grid:2',{origin_kind:'grid'},[49.8123456,40.4234567])];
  const groups=groupODOptions(items,map.exits),network=groups.find(g=>g.key==='network');
  assert.deepEqual(groups.map(g=>g.key),['metro','terminal','network']);
  assert.equal(groups[1].options[0].label,'Bakı Beynəlxalq Avtovağzal');
  assert.equal(network.options[0].value,'origin:grid:2');
  assert.equal(network.options[0].label,'Şəbəkə nöqtəsi 1 · 40.42346, 49.81235');
  assert.equal(network.options[1].label,'Şəbəkə nöqtəsi 2');
  assert.deepEqual(groupODOptions([...items].reverse(),[...map.exits].reverse()),groups);
  assert.equal(odJourneyHeading(groups[1].options[0].heading,groups[0].options[0].heading),'Bakı Beynəlxalq Avtovağzal → 20 Yanvar · Çıxış 5');
});

test('missing names or coordinates never become invented neighborhoods or raw IDs',()=>{
  const options=flat(groupODOptions([origin('origin:metro_exit:999'),origin('origin:grid:1',{},[null,NaN])],map.exits));
  assert.equal(options[0].label,'Metro çıxışı · adı mövcud deyil');
  assert.equal(options[1].label,'Şəbəkə nöqtəsi 1');
  assert.equal(odJourneyHeading(null,null),'Bir səfər, bir neçə mərhələ.');
});

test('all 302 origins and 9 destinations retain exactly their original values',()=>{
  for(const key of ['origins','destinations']) {
    const items=map[key].map(({id})=>origin(id)),options=flat(groupODOptions(items,map.exits));
    assert.equal(options.length,key==='origins'?302:9);
    assert.deepEqual(new Set(options.map(o=>o.value)),new Set(items.map(i=>i.id)));
    assert.ok(options.every(o=>!/(origin:|destination:)/.test(o.label)));
  }
  const groups=groupODOptions(map.origins.map(({id})=>origin(id)),map.exits);
  assert.deepEqual(groups.map(g=>g.options.length),[44,1,257]);
});

test('dropdown integration preserves selected IDs and uses only readable headings',()=>{
  class Element {
    constructor(tag){this.tag=tag;this.children=[];this.dataset={};this.textContent='';this._value=undefined;}
    append(...children){this.children.push(...children);}
    replaceChildren(...children){this.children=[...children];}
    setAttribute(){}
    get options(){return this.children.flatMap(c=>c.tag==='option'?[c]:c.options);}
    get value(){return this._value??this.options[0]?.value??'';}
    set value(value){this._value=value;}
    get selectedOptions(){return this.options.filter(o=>o.value===this.value);}
  }
  const elements=new Map(['origin','destination','headway-r2','headway-r14','candidate-controls'].map(id=>[id,new Element('select')]));
  const heading=new Element('h2'),previousDocument=globalThis.document,previousOption=globalThis.Option;
  globalThis.document={createElement:tag=>new Element(tag),getElementById:id=>elements.get(id),querySelector:()=>heading};
  globalThis.Option=class extends Element {constructor(label,value){super('option');this.textContent=label;this.value=value;}};
  try {
    const metadata={origins:map.origins.map(({id})=>origin(id)),destinations:map.destinations.map(({id})=>origin(id)),headways:{}};
    const ui={metadata,data:map,state:{},catalog:{service_groups:{},prebuilt_services:{},patterns:[]},updateJourneyHeading(){RoutingUI.prototype.updateJourneyHeading.call(this);}};
    elements.get('origin').value='origin:metro_exit:31';elements.get('destination').value='destination:metro_exit:44';
    RoutingUI.prototype.populate.call(ui);
    assert.equal(elements.get('origin').options.length,302);assert.equal(elements.get('destination').options.length,9);
    assert.equal(elements.get('origin').children[0].tag,'optgroup');
    assert.equal(RoutingUI.prototype.selection.call(ui).origin,'origin:metro_exit:31');
    assert.equal(RoutingUI.prototype.selection.call(ui).destination,'destination:metro_exit:44');
    assert.equal(heading.textContent,'20 Yanvar · Çıxış 5 → 28 May · Çıxış 1');
    elements.get('origin').value='origin:terminal:baku_international';ui.updateJourneyHeading();
    assert.equal(heading.textContent,'Bakı Beynəlxalq Avtovağzal → 28 May · Çıxış 1');
    elements.get('origin').value='';elements.get('destination').value='';RoutingUI.prototype.populate.call(ui);
    assert.equal(elements.get('origin').value,'origin:terminal:baku_international');
    assert.equal(elements.get('destination').value,metadata.destinations[0].id);
  } finally {globalThis.document=previousDocument;globalThis.Option=previousOption;}
});
