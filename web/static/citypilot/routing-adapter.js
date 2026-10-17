/** Exact contract 1.0 requests and a single queued worker on the client. */
import {modeLabel} from './journey-presentation.js';
export function projectCoordinate([lon,lat],meta) {
  const d=Math.PI/180,r=meta.transform.radius_m;
  return [(lon-meta.center[0])*d*r*Math.cos(meta.center[1]*d),-(lat-meta.center[1])*d*r];
}
export function assertIdentity(value,ready) {
  for(const k of ['contract_version','model_version','od_set_id'])if(value[k]!==ready[k])throw Error('Model identity mismatch: '+k);
}
export function buildRequest(ready,catalog,selection) {
  assertIdentity(catalog,ready);
  if(!['normal','disrupted','mitigated'].includes(selection.scenario)||!['P','B'].includes(selection.profile))throw Error('Invalid routing selection');
  const patches=[];
  if(selection.scenario==='mitigated') {
    for(const [id,value]of Object.entries(selection.headways||{}))if(value!==''&&value!=null) {
      if(!catalog.service_groups[id]||!Number.isFinite(Number(value))||Number(value)<=0)throw Error('Unknown headway choice');
      patches.push({kind:'set_service_headway',target_id:id,headway_min:Number(value)});
    }
    const lines=new Set();
    for(const id of Object.values(selection.services||{}).filter(Boolean)) {
      const group=catalog.prebuilt_services[id];if(!group)throw Error('Unknown prebuilt service');
      const routes=new Set(catalog.patterns.filter(p=>group.pattern_ids.includes(p.pattern_id)).map(p=>p.route_id));
      for(const line of routes){if(lines.has(line))throw Error('Mutually exclusive M service variants');lines.add(line);}
      patches.push({kind:'activate_service',target_id:id,headway_min:null});
    }
  }
  return {contract_version:ready.contract_version,model_version:ready.model_version,od_set_id:ready.od_set_id,
    state:selection.scenario,profile:selection.profile,closure_id:selection.scenario==='normal'?null:ready.closure_id,
    patches,speed_factor:1,headway_factor_by_group:null,thresholds_min:[40,45,50],primary_t_min:45,cap_min:120,candidate_ids:[]};
}
export async function fetchJSON(url,body,fetcher=fetch) {
  let response;
  try {
    const signal=AbortSignal.timeout(120000);
    response=await fetcher(url,body===undefined?{cache:'no-store',signal}:{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body),signal});
  } catch(error) {
    if(error.name==='TimeoutError')throw Error('Routing request timed out. The server may still be busy; wait, then press Retry.');
    throw error;
  }
  let data;try{data=await response.json();}catch{throw Error('Server returned unreadable JSON');}
  if(!response.ok){const error=Error(data.error?.message||data.detail||response.statusText);error.status=response.status;error.code=data.error?.code;throw error;}
  return data;
}
export class RoutingController {
  constructor({ready,catalog,onStatus,onEvaluation,onJourney,fetcher=fetchJSON,delay=350}) {
    Object.assign(this,{ready,catalog,onStatus,onEvaluation,onJourney,fetcher,delay});
    this.generation=0;this.running=false;this.pending=null;this.timer=null;this.evaluation=null;this.evaluationKey=null;this.disposed=false;
  }
  select(selection,{immediate=false}={}) {
    const snapshot=structuredClone(selection),key=JSON.stringify(snapshot);
    if(key===this.selectionKey&&!immediate)return;
    this.selectionKey=key;const generation=++this.generation;
    clearTimeout(this.timer);this.pending=null;
    this.onStatus('outdated','Selections changed; previous results are outdated.');
    this.timer=setTimeout(()=>{this.pending={snapshot,generation};this.drain();},immediate?0:this.delay);
  }
  async drain() {
    if(this.running||!this.pending||this.disposed)return;
    this.running=true;const{snapshot,generation}=this.pending;this.pending=null;
    const current=()=>!this.disposed&&generation===this.generation;
    try {
      const request=buildRequest(this.ready,this.catalog,snapshot),key=JSON.stringify(request);
      if(!snapshot.origin||!snapshot.destination)throw Error('Select a saved origin and individual destination exit');
      if(current())this.onStatus('loading','Computing accessibility and the selected journey…');
      let evaluation=this.evaluationKey===key?this.evaluation:null;
      if(!evaluation) {
        evaluation=await this.fetcher('./routing/evaluate_package',request);
        assertIdentity(evaluation,this.ready);
        if(evaluation.state!==request.state||evaluation.profile!==request.profile||!evaluation.config_hash)throw Error('Evaluation identity mismatch');
        if(current()){this.evaluation=evaluation;this.evaluationKey=key;}
      }
      if(!current())return;
      this.onEvaluation(evaluation);
      const query=new URLSearchParams({origin_id:snapshot.origin,destination_id:snapshot.destination});
      const journey=await this.fetcher('./routing/inspect_journey?'+query,request);
      if(!current())return;
      assertIdentity(journey,this.ready);
      if(journey.config_hash!==evaluation.config_hash||journey.state!==request.state||journey.profile!==request.profile||journey.origin_id!==snapshot.origin||journey.destination_id!==snapshot.destination)throw Error('Journey identity mismatch');
      this.onJourney(journey);this.onStatus(journey.status==='no_path'?'empty':'ready',journey.status==='no_path'?'No path for this fixed OD pair.':'Results current. Simulation uses physical model time.');
    } catch(error) {
      if(current())this.onStatus(error.status===429?'busy':'error',error.status===429?'Routing is busy. Wait, then press Retry.':error.message);
    } finally {
      this.running=false;if(this.pending&&!this.disposed)this.drain();
    }
  }
  dispose(){this.disposed=true;this.generation++;this.pending=null;clearTimeout(this.timer);}
}

export function journeyLegs(journey,meta) {
  if(!journey||journey.status==='no_path')return [];
  if(!Number.isFinite(journey.total_min)||journey.total_min<0)throw Error('Invalid physical journey total');
  const result=[];let previous=null;
  const close=(a,b)=>a&&b&&a[0]===b[0]&&a[1]===b[1];
  const gap=(id,layer)=>result.push({id,mode:'gap',title:'Həndəsə boşluğu · davam etmək üçün təsdiqləyin',seconds:0,geometry:null,layer,gap:true});
  let sum=0;
  journey.legs.forEach((leg,index)=>{
    const values=['walk_min','wait_min','ride_min','transfer_min'].map(k=>leg[k]);
    if(values.some(x=>!Number.isFinite(x)||x<0))throw Error('Invalid physical leg time');
    const seconds=values.reduce((s,v)=>s+v,0)*60;sum+=seconds;
    const raw=leg.geometry;let pieces;
    if(raw?.type==='Point')pieces=[[raw.coordinates]];
    else if(raw?.type==='LineString')pieces=[raw.coordinates];
    else if(raw?.type==='MultiLineString')pieces=raw.coordinates;
    else throw Error('Journey geometry missing or unsupported');
    const projected=pieces.map(p=>p.map(c=>projectCoordinate(c,meta)));
    if(projected.some(p=>!p.length||p.some(c=>!c.every(Number.isFinite))))throw Error('Invalid journey coordinates');
    const layer=leg.mode==='metro'||leg.mode==='transfer'&&(journey.legs[index-1]?.mode==='metro'||journey.legs[index+1]?.mode==='metro')?'metro':'surface';
    if(previous&&!close(previous,projected[0][0]))gap('gap-before-'+index,layer);
    const lengths=projected.map(p=>p.slice(1).reduce((s,c,i)=>s+Math.hypot(c[0]-p[i][0],c[1]-p[i][1]),0)),length=lengths.reduce((s,v)=>s+v,0);
    if(leg.wait_min&&length>0)throw Error('Waiting leg has moving geometry; explicit stationary timing geometry required');
    projected.forEach((p,piece)=>{
      if(piece&&!close(projected[piece-1].at(-1),p[0]))gap('gap-'+index+'-'+piece,layer);
      const stationary=lengths[piece]===0,wait=leg.wait_min>0;
      const mode=wait?'wait':leg.mode;
      const suffix=stationary&&leg.ride_min>0?' · modeldə verilmiş dayanma':stationary&&leg.mode==='transfer'?' · stasionar keçid':'';
      result.push({id:'leg-'+index+'-'+piece,mode,title:(wait?'Gözləmə · '+modeLabel(leg.mode):modeLabel(leg.mode))+(leg.route_id?' · '+leg.route_id:'')+suffix,
        seconds:length?seconds*lengths[piece]/length:seconds/projected.length,geometry:p,layer,stationary,
        provenance:leg.provenance,sourceLeg:index,physical:leg,interpolation:projected.length>1?'Time distributed across known geometry by length; gap has unknown geometry.':null});
    });previous=projected.at(-1).at(-1);
  });
  if(Math.abs(sum-journey.total_min*60)>1e-4)throw Error('Journey total does not equal physical leg sum');
  return result;
}
