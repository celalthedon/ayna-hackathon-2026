import {RoutingController,fetchJSON,assertIdentity} from './routing-adapter.js';
const $=id=>document.getElementById(id);
const node=(tag,text,cls)=>{const n=document.createElement(tag);if(text!=null)n.textContent=text;if(cls)n.className=cls;return n;};

export class RoutingUI {
  constructor({state,data,onJourney,onInvalidate,onStatus}) {
    Object.assign(this,{state,data,onJourney,onInvalidate,onStatus});
    this.results={};this.listeners=new Set();this.phase='pending';this.message='Routing model is loading…';
    $('retry-routing').onclick=()=>this.controller?this.controller.select(this.selection(),{immediate:true}):this.start();
    $('origin').onchange=$('destination').onchange=()=>this.change();
    this.handle=null;this.starting=false;this.disposed=false;
    this.onPageHide=()=>this.dispose();window.addEventListener('pagehide',this.onPageHide,{once:true});
  }
  selection(){return {scenario:this.state.scenario,profile:this.state.profile,headways:this.state.headways||{},services:this.state.services||{},origin:$('origin').value,destination:$('destination').value};}
  async start() {
    if(this.starting||this.disposed)return;this.starting=true;
    this.status('loading','Checking routing model and fixed OD metadata…');
    try {
      this.ready=await fetchJSON('./routing/ready');
      if(this.ready.contract_version!=='1.0')throw Error('Unsupported routing contract');
      for(const k of ['bundle_hash','od_hash','supplement_hash','closure_id'])if(this.ready[k]!==this.data.meta[k])throw Error('Map / loaded model identity mismatch: '+k);
      this.catalog=await fetchJSON('./routing/catalog');assertIdentity(this.catalog,this.ready);
      this.metadata=await fetchJSON('./routing/od_metadata');assertIdentity(this.metadata.identity,this.ready);
      if(this.metadata.origins.length!==this.ready.origin_count||this.metadata.destinations.length!==this.ready.destination_count)throw Error('Fixed OD dimensions do not match readiness');
      if(this.disposed)return;
      this.populate();
      this.controller=new RoutingController({ready:this.ready,catalog:this.catalog,
        onStatus:(...a)=>this.status(...a),onEvaluation:r=>{this.evaluation=r;this.results[r.profile+':'+r.state]=r;this.renderCounts();},
        onJourney:r=>{this.onJourney(r);this.renderJourney(r);}});
      this.controller.select(this.selection(),{immediate:true});
      await this.decision();
    } catch(e){if(!this.disposed)this.status(e.status===429?'busy':'error',e.message);}
    finally{this.starting=false;}
  }
  populate() {
    for(const [id,items]of [['origin',this.metadata.origins],['destination',this.metadata.destinations]]) {
      const select=$(id),old=select.value;select.replaceChildren();
      for(const item of items) {
        const p=item.properties,label=id==='origin'?(p.origin_kind==='terminal'?'Bakı Beynəlxalq Avtovağzal':p.origin_kind==='metro_exit'?item.id:'Grid · '+item.id.split(':').slice(-2).join(':')):[p.station_name,p.exit_name].filter(Boolean).join(' · ');
        select.append(new Option(label+' · '+item.id,item.id));
      }
      select.disabled=false;
      select.value=items.some(i=>i.id===old)?old:id==='origin'&&items.some(i=>i.id==='origin:terminal:baku_international')?'origin:terminal:baku_international':items[0]?.id||'';
    }
    this.state.headways={};this.state.services={};
    for(const [id,group]of [['headway-r2','SG_R2'],['headway-r14','SG_R14']]) {
      const select=$(id),configured=this.metadata.headways[group];select.replaceChildren(new Option('Baza intervalı / dəyişməz',''));
      if(!configured||!this.catalog.service_groups[group])continue;
      if(configured.baseline_min!==this.catalog.service_groups[group].base_headway_min)throw Error('Configured headway/catalog mismatch');
      for(const minutes of configured.choices_min.filter(t=>t<configured.baseline_min))select.append(new Option(minutes+' min · '+configured.status,String(minutes)));
      select.disabled=false;select.onchange=()=>{this.state.headways[group]=select.value;this.state.scenario='mitigated';this.change();};
    }
    $('candidate-controls').replaceChildren();
    for(const line of ['M1','M2','M3','M5','M6']) {
      const variants=Object.values(this.catalog.prebuilt_services).filter(g=>this.catalog.patterns.some(p=>g.pattern_ids.includes(p.pattern_id)&&p.route_id===line)).sort((a,b)=>a.base_headway_min-b.base_headway_min);
      const row=node('div',null,'candidate'),title=node('div',null,'candidate-title');title.append(node('span',line,'route-badge'),node('small','Modelləşdirilmiş xətt · hər iki istiqamət','muted'));row.append(title);
      const choices=node('div',null,'candidate-variants');choices.setAttribute('role','radiogroup');choices.setAttribute('aria-label',line+' xidmət variantı');
      for(const option of [null,...variants]) {
        const id=option?.service_group_id||'',button=node('button',option?option.base_headway_min+' dəq':'Bağlı');
        button.type='button';button.setAttribute('role','radio');button.setAttribute('aria-checked',String(!option));button.dataset.service=id;button.title=option?.provenance.evidence||'Xidmət bağlıdır';
        button.onclick=()=>{this.state.services[line]=id;this.state.layers[line]=!!id;this.state.scenario='mitigated';choices.querySelectorAll('button').forEach(b=>b.setAttribute('aria-checked',String(b===button)));this.change();};choices.append(button);
      }
      row.append(choices);$('candidate-controls').append(row);
    }
  }
  change() {
    if(this.controller&&JSON.stringify(this.selection())===this.controller.selectionKey)return;
    this.onInvalidate();
    if(this.controller)this.controller.select(this.selection());
    this.listeners.forEach(f=>f());
  }
  status(phase,message) {
    this.phase=phase;this.message=message;
    if(phase==='outdated')this.evaluation=null;
    $('routing-status').textContent=message;$('routing-status').dataset.state=phase;
    $('retry-routing').hidden=phase!=='busy'&&phase!=='error';
    if(['outdated','loading','error','busy'].includes(phase))this.onStatus(phase,message);
    this.renderCounts();this.listeners.forEach(f=>f());
  }
  renderCounts() {
    const box=$('accessibility-state');box.dataset.state=this.phase;
    box.querySelector('h3').textContent=this.phase==='ready'?'Əlçatanlıq · '+this.state.profile:this.phase==='outdated'?'Yenilənməlidir':this.phase==='busy'?'Marşrut hesablaması məşğuldur':this.phase==='error'?'Marşrut xidməti əlçatan deyil':this.phase==='empty'?'Bu səfər üçün yol yoxdur':'Yüklənir…';
    box.querySelector('p').textContent=this.message;
    const table=node('table'),head=node('tr');for(const label of ['Ssenari','40','45','50'])head.append(node('th',label));table.append(head);
    const current=this.evaluation,threshold=Number(this.state.threshold),profile=this.state.profile;
    for(const scenario of ['normal','disrupted','mitigated']) {
      const result=this.results[profile+':'+scenario],tr=node('tr');
      const historical=result&&(!current||current.config_hash!==result.config_hash||this.phase==='outdated');
      tr.append(node('td',({normal:'Normal',disrupted:'Kəsinti',mitigated:'Tədbirlərdən sonra'}[scenario])+(historical?' · əvvəlki':'')));
      for(const t of [40,45,50])tr.append(node('td',result?String(result.within_counts[t]):'—'));
      if(result&&(!current||current.config_hash!==result.config_hash||this.phase==='outdated'))tr.title='Previously computed selection; use scenario controls to refresh';table.append(tr);
    }
    $('count-table').replaceChildren(node('p','Hesablanmış ssenarilər · OD cütləri, sərnişin sayı deyil','muted'),table);
    const currentValid=current&&current.profile===profile&&current.state===this.state.scenario&&!['outdated','error','busy'].includes(this.phase);
    document.querySelector('#impact-results small').textContent=currentValid?current.within_counts[threshold]+' / '+this.ready.origin_count*this.ready.destination_count+' OD · '+this.state.profile+' · '+this.state.scenario:this.message;
    const normal=this.results[profile+':normal'],disrupted=this.results[profile+':disrupted'],mitigated=this.results[profile+':mitigated'];
    const crossed=(a,b)=>{if(!a||!b)return '—';const times=new Map(b.od_results.map(r=>[r.od_id,r.minutes]));return a.od_results.filter(r=>r.minutes!==null&&r.minutes<=threshold&&(times.get(r.od_id)==null||times.get(r.od_id)>threshold)).length;};
    $('lost-ods').textContent=crossed(normal,disrupted);
    $('restored-ods').textContent=currentValid&&this.state.scenario==='mitigated'&&current.config_hash===mitigated?.config_hash?crossed(mitigated,disrupted):'—';
  }
  renderJourney(journey) {
    const root=$('journey-facts');root.replaceChildren();
    root.dataset.totalMin=journey.total_min==null?'':String(journey.total_min);
    root.dataset.legSumMin=String(journey.legs.reduce((sum,l)=>sum+l.walk_min+l.wait_min+l.ride_min+l.transfer_min,0));
    if(journey.status==='no_path'){root.append(node('p','Seçilmiş sabit OD cütü üçün yol yoxdur.','muted'));return;}
    const totals=Object.fromEntries(['walk_min','wait_min','ride_min','transfer_min'].map(k=>[k,journey.legs.reduce((sum,l)=>sum+l[k],0)]));
    root.append(node('p','Fiziki ümumi vaxt: '+journey.total_min.toFixed(3)+' min · '+journey.status,'muted'));
    for(const[k,v]of Object.entries(totals))root.append(node('p',({walk_min:'Piyada',wait_min:'Gözləmə',ride_min:'Nəqliyyatda / velosipedlə',transfer_min:'Keçid'}[k])+': '+v.toFixed(3)+' dəq','muted'));
    if(journey.generalised_cost_min!=null)root.append(node('p','Ümumiləşdirilmiş vaxt: '+journey.generalised_cost_min.toFixed(3)+' min','muted'));
    root.append(node('p','Geometry gaps: '+journey.geometry_metadata.gap_count+'. Missing connectors are not drawn. Animation within supplied shapes is interpolation. Multipart leg time is distributed across known pieces by length; gaps have no inferred geometry or timing.','muted'));
    const unique=new Map([...journey.provenance,...journey.legs.flatMap(l=>l.provenance)].map(p=>[p.source_id,p]));
    for(const p of unique.values()){const details=node('details'),summary=node('summary',p.source_id+' · '+p.status);details.append(summary,node('p',p.evidence,'muted'));root.append(details);}
    for(const warning of journey.warnings)root.append(node('p',warning,'muted'));
  }
  async decision() {
    try {
      const caps=await fetchJSON('./citypilot-capabilities');
      if(!caps.decision_available||this.handle||this.disposed)return;
      // The supplied panel owns its algorithms, checks and endpoints. No optimize
      // or precompute calls are initiated by this adapter.
      const server=await fetchJSON('./decision/state');
      if(this.disposed)return;
      this.decisionHash=server.config_hash;
      this.handle=window.CityPilotDecision.mount($('decision-slot'),{
        getAppState:()=>({profile:this.state.profile,configHash:this.decisionHash,routingConfigHash:this.evaluation?.config_hash,routingOutdated:this.phase!=='ready'}),
        onStateChange:callback=>{this.listeners.add(callback);return()=>this.listeners.delete(callback);},
      });
      document.querySelector('#result-decision .empty-state').hidden=true;
    } catch(e){$('decision-slot').replaceChildren(node('p','Qərar inteqrasiyası gözlənilir: '+e.message,'muted'));}
  }
  dispose(){this.disposed=true;this.controller?.dispose();this.handle?.unmount();this.handle=null;this.listeners.clear();window.removeEventListener('pagehide',this.onPageHide);}
}
