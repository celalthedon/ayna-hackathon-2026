/** Browser-only smoke check when Python is unavailable. No application server.
 * CDP intercepts the real static assets; /routing/ready explicitly returns 503.
 * This is NOT FastAPI or real routing end-to-end evidence.
 */
import fs from 'node:fs';
import path from 'node:path';
import os from 'node:os';
import {spawn} from 'node:child_process';
import {setTimeout as delay} from 'node:timers/promises';
import {fileURLToPath} from 'node:url';
import assert from 'node:assert/strict';

const repo=path.resolve(path.dirname(fileURLToPath(import.meta.url)),'..');
const live=process.argv.includes('--live');
const liveURL=process.env.CITYPILOT_LIVE_URL||'http://127.0.0.1:8000/';
const output=path.join(repo,'docs/ui-verification');fs.mkdirSync(output,{recursive:true});
const profile=fs.mkdtempSync(path.join(os.tmpdir(),'citypilot-ui-browser-'));
const chrome=process.env.CITYPILOT_CHROME||'C:/Program Files/Google/Chrome/Application/chrome.exe';
const only2D=process.env.CITYPILOT_BROWSER_2D_ONLY==='1';
const browser=spawn(chrome,['--headless=new','--no-first-run','--no-default-browser-check','--disable-background-networking','--disable-component-update','--disable-sync',...(only2D?['--disable-gpu','--disable-software-rasterizer']:['--enable-unsafe-swiftshader']),'--remote-debugging-port=0','--user-data-dir='+profile,'--window-size=1366,900','about:blank'],{windowsHide:true,stdio:['ignore','ignore','pipe']});
let stderr='';browser.stderr.on('data',d=>stderr+=d.toString());
let ws,browserWS,sequence=0;const pending=new Map(),exceptions=[],consoleErrors=[],requests=[],checks=[];
const keepAlive=setInterval(()=>{},1000);
const send=(method,params={})=>new Promise((resolve,reject)=>{const id=++sequence;const timer=setTimeout(()=>{pending.delete(id);reject(Error('CDP timeout: '+method));},15000);pending.set(id,{resolve:v=>{clearTimeout(timer);resolve(v);},reject:e=>{clearTimeout(timer);reject(e);}});ws.send(JSON.stringify({id,method,params}));});
const mime=file=>file.endsWith('.js')?'text/javascript':file.endsWith('.css')?'text/css':file.endsWith('.json')?'application/json':file.endsWith('.html')?'text/html':'text/plain';
let port;
async function connect(url){const socket=new WebSocket(url);await new Promise((resolve,reject)=>{socket.onopen=resolve;socket.onerror=reject;});return socket;}
async function intercept(params) {
  const url=new URL(params.request.url);requests.push(url.href);
  let body,status=200,type='application/json';
  if(url.hostname!=='citypilot-ui.test'){body=Buffer.from('{}');status=404;}
  else if(url.pathname==='/routing/ready'){status=503;body=Buffer.from(JSON.stringify({error:{code:'model_not_ready',message:'Browser smoke check: real Python API unavailable in this execution session'}}));}
  else if(url.pathname==='/citypilot-capabilities'){body=Buffer.from('{"decision_available":false,"decision_status":"pending_real_backend"}');}
  else {
    const file=url.pathname==='/'?path.join(repo,'web/citypilot.html'):url.pathname.startsWith('/citypilot-assets/')?path.resolve(repo,'web/static',url.pathname.slice('/citypilot-assets/'.length)):null;
    if(file&&(file===path.join(repo,'web/citypilot.html')||file.startsWith(path.join(repo,'web/static')+path.sep))&&fs.existsSync(file)&&fs.statSync(file).isFile()){body=fs.readFileSync(file);type=mime(file);}
    else {status=404;body=Buffer.from('{}');}
  }
  await send('Fetch.fulfillRequest',{requestId:params.requestId,responseCode:status,responseHeaders:[{name:'Content-Type',value:type+'; charset=utf-8'},{name:'Cache-Control',value:'no-store'}],body:body.toString('base64')});
}
const evaluate=async expression=>{
  const r=await send('Runtime.evaluate',{expression,returnByValue:true,awaitPromise:true});
  if(r.exceptionDetails)throw Error(r.exceptionDetails.exception?.description||r.exceptionDetails.text);return r.result.value;
};
async function until(expression,timeout=90000){const start=Date.now();while(Date.now()-start<timeout){if(await evaluate(expression))return;await delay(250);}throw Error('Timed out: '+expression);}
async function screenshot(name){const result=await send('Page.captureScreenshot',{format:'png',captureBeyondViewport:false});fs.writeFileSync(path.join(output,name+'.png'),Buffer.from(result.data,'base64'));}
async function click(selector){await evaluate(`document.querySelector(${JSON.stringify(selector)}).click()`);await delay(800);}
try {
  const portFile=path.join(profile,'DevToolsActivePort');
  for(let i=0;i<80;i++){if(fs.existsSync(portFile))break;if(browser.exitCode!==null)throw Error('Chrome exited: '+stderr.slice(-1800));await delay(250);}
  const lines=fs.readFileSync(portFile,'utf8').trim().split(/\r?\n/);port=Number(lines[0]);browserWS=await connect('ws://127.0.0.1:'+port+lines[1]);
  const target=await fetch('http://127.0.0.1:'+port+'/json/new?about:blank',{method:'PUT'}).then(r=>r.json());
  ws=await connect(target.webSocketDebuggerUrl);
  ws.onmessage=event=>{const m=JSON.parse(event.data);if(m.id){const p=pending.get(m.id);pending.delete(m.id);if(p)m.error?p.reject(Error(JSON.stringify(m.error))):p.resolve(m.result);}
    else if(m.method==='Fetch.requestPaused')intercept(m.params).catch(e=>exceptions.push({intercept:e.message}));
    else if(m.method==='Runtime.exceptionThrown')exceptions.push(m.params.exceptionDetails);
    else if(m.method==='Runtime.consoleAPICalled'&&m.params.type==='error')consoleErrors.push(m.params.args.map(a=>a.value||a.description));
    else if(live&&m.method==='Network.requestWillBeSent')requests.push(m.params.request.url);};
  await send('Page.enable');await send('Runtime.enable');
  if(live)await send('Network.enable');else await send('Fetch.enable',{patterns:[{urlPattern:'*',requestStage:'Request'}]});
  await send('Emulation.setDeviceMetricsOverride',{width:1366,height:900,deviceScaleFactor:1,mobile:false});
  const initialTheme=await send('Page.addScriptToEvaluateOnNewDocument',{source:"try{localStorage.setItem('citypilot.theme','dark')}catch{}"});
  await send('Page.navigate',{url:live?liveURL:'http://citypilot-ui.test/'+(only2D?'?renderer=2d':'')});
  await send('Page.removeScriptToEvaluateOnNewDocument',{identifier:initialTheme.identifier});
  await until("document.getElementById('scene-loading')?.hidden===true");
  await until("['ready','error','busy'].includes(document.getElementById('routing-status')?.dataset.state)");
  assert.equal(await evaluate("document.getElementById('render-error').hidden"),true);
  assert.equal(await evaluate(only2D?"!!document.querySelector('#viewport>svg')":"!!document.querySelector('#viewport canvas')"),true);
  if(live) {
    assert.equal(await evaluate("document.getElementById('routing-status').dataset.state"),'ready');
    assert.equal(await evaluate("document.getElementById('origin').options.length"),302);
    assert.equal(await evaluate("document.getElementById('destination').options.length"),9);
    assert.equal(await evaluate("document.getElementById('play').disabled"),false);
    const row=scenario=>evaluate(`Array.from(document.querySelectorAll('#count-table tr')).find(r=>r.cells[0].textContent.startsWith(${JSON.stringify({normal:'Normal',disrupted:'Kəsinti',mitigated:'Tədbirlərdən sonra'}[scenario])}))?.textContent`);
    assert.match(await row('disrupted'),/63611911697/);
    await click('[data-scenario="normal"]');await until("document.getElementById('routing-status').dataset.state==='ready'");assert.match(await row('normal'),/206023392496/);
    await click('[data-tool="actions"]');
    const service=await evaluate("Array.from(document.querySelectorAll('[data-service]')).find(b=>b.dataset.service.startsWith('SVC_M1')&&Number.parseFloat(b.textContent)===6)?.dataset.service");
    assert.ok(service);await click('[data-service="'+service+'"]');await until("document.getElementById('routing-status').dataset.state==='ready'");
    const totals=await evaluate("({total:Number(document.getElementById('journey-facts').dataset.totalMin),sum:Number(document.getElementById('journey-facts').dataset.legSumMin),seconds:Number(document.getElementById('timeline').max)})");
    assert.ok(totals.total>0);assert.ok(Math.abs(totals.total-totals.sum)<1e-6);assert.ok(Math.abs(totals.total*60-totals.seconds)<1e-4);
    await click('#play');assert.equal(await evaluate("document.getElementById('play').dataset.playing"),'true');await click('#play');await click('#restart');assert.equal(await evaluate("document.getElementById('elapsed').textContent"),'00:00');
    await evaluate("const t=document.getElementById('timeline');t.value=String(Number(t.max)/2);t.dispatchEvent(new Event('input',{bubbles:true}))");
    assert.notEqual(await evaluate("document.getElementById('elapsed').textContent"),'00:00');await click('#restart');
    checks.push('Real API: 302/9 selectors, known P normal/disrupted counts, one catalogued M1 6-minute activation, exact physical leg/total/playback sum, play/pause/restart/seek.');
  } else {
    assert.equal(await evaluate("document.getElementById('play').disabled"),true);
    assert.equal(await evaluate("document.getElementById('origin').disabled"),true);
    checks.push('Approved UI/'+(only2D?'2D fallback':'Three.js')+' renders full local pilot; unavailable real API disables OD/playback and shows retry error.');
  }
  await screenshot(live?'dark-full-pilot-real-api':'dark-full-pilot-api-unavailable');
  await click('#focus-closure');await screenshot('dark-closure');
  if(!only2D){await click('[data-view="both"]');await screenshot('dark-exploded');}
  await click('[data-view="underground"]');checks.push(only2D?'Surface/underground controls respond in 2D; exploded view explicitly unavailable.':'Surface/both/underground controls respond in Three.js.');
  await click('#theme-toggle');assert.equal(await evaluate("document.documentElement.dataset.theme"),'light');await screenshot('light-underground');
  await click('[data-view="surface"]');
  await click('#open-results');await click('[data-result-tab="decision"]');
  assert.equal(await evaluate("document.querySelector('#decision-slot .pending-tag')!==null"),true);
  await screenshot('light-decision-pending');checks.push('Light/dark themes, laptop results drawer and honest decision-pending state inspected.');
  await click('#close-results');await click('[data-tool="layers"]');
  for(const layer of ['M1','M2','M3','M5','M6','parking','exits','origins'])await click('[data-layer="'+layer+'"]');
  await click('#reset-camera');await screenshot('light-full-pilot-all-layers');
  await send('Page.navigate',{url:live?new URL('?renderer=2d',liveURL).href:'http://citypilot-ui.test/?renderer=2d'});
  await until("document.getElementById('scene-loading')?.hidden===true");await until("['ready','error','busy'].includes(document.getElementById('routing-status')?.dataset.state)");
  assert.equal(await evaluate("!!document.querySelector('#viewport>svg')"),true);
  assert.equal(await evaluate("document.querySelector('[data-view=both]').disabled"),true);
  await screenshot('light-2d-fallback');checks.push('2D SVG fallback renders full pilot with batched paths and disclosed lack of exploded layers.');
  await send('Emulation.setDeviceMetricsOverride',{width:1280,height:800,deviceScaleFactor:1,mobile:false});await screenshot('laptop-1280-2d');
  assert.equal(exceptions.length,0,JSON.stringify(exceptions));assert.equal(consoleErrors.length,0,JSON.stringify(consoleErrors));
  assert.ok(requests.every(u=>!u.startsWith('file:')));
  assert.ok(requests.filter(u=>u.includes('/routing/ready')).length===2,'No automatic routing retry storm');
  const report={kind:live?'live-integrated-app':'browser-static-assets-with-CDP-interception',real_api_end_to_end:live,api_response:live?'Actual local API':'503 deliberately supplied: Python runtime unavailable',browser:await send('Browser.getVersion'),checks,exceptions,consoleErrors,request_count:requests.length,file_requests:requests.filter(u=>u.startsWith('file:')),screenshots:fs.readdirSync(output).filter(n=>n.endsWith('.png'))};
  fs.writeFileSync(path.join(output,'browser-smoke.json'),JSON.stringify(report,null,2));console.log(JSON.stringify(report,null,2));
} catch(error) {
  console.error('Browser smoke failed:',error?.message||String(error),'Chrome exit:',browser.exitCode,'Chrome log:',stderr.slice(-3000));
  fs.writeFileSync(path.join(output,'browser-blocked.json'),JSON.stringify({passed:false,only2D,live_attempted:live,real_api_end_to_end:false,error:error?.message||String(error),chrome_exit:browser.exitCode,chrome_log:stderr.slice(-3000),exceptions,consoleErrors},null,2));
  throw error;
} finally {
  if(browserWS?.readyState===WebSocket.OPEN){browserWS.send(JSON.stringify({id:1,method:'Browser.close'}));await delay(1000);browserWS.close();}
  ws?.close();
  clearInterval(keepAlive);
  // Only this check's isolated temporary browser profile is removed.
  if(profile.startsWith(path.join(os.tmpdir(),'citypilot-ui-browser-')))try{fs.rmSync(profile,{recursive:true,force:true});}catch{}
}
