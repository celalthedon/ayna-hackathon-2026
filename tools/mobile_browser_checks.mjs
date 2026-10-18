import assert from 'node:assert/strict';

// Exercise the real DOM and layout through the existing isolated CDP harness.
// Static mode deliberately has no routing backend; it never invents journeys.
export async function checkMobileLayout({send,evaluate,click,screenshot,until,checks}) {
  const rect=selector=>evaluate(`(()=>{const r=document.querySelector(${JSON.stringify(selector)}).getBoundingClientRect();return {x:r.x,y:r.y,width:r.width,height:r.height}})()`);
  const tap=async selector=>{
    await evaluate(`document.querySelector(${JSON.stringify(selector)}).scrollIntoView({block:'nearest'})`);
    await evaluate('new Promise(resolve=>requestAnimationFrame(resolve))');
    const r=await rect(selector);assert.ok(r.width>=44&&r.height>=44,selector+' touch target');
    const x=r.x+r.width/2,y=r.y+r.height/2;
    assert.equal(await evaluate(`!!document.elementFromPoint(${x},${y})?.closest(${JSON.stringify(selector)})`),true,selector+' not obscured');
    await send('Input.dispatchMouseEvent',{type:'mousePressed',x,y,button:'left',clickCount:1});
    await send('Input.dispatchMouseEvent',{type:'mouseReleased',x,y,button:'left',clickCount:1});
  };
  const desktop=await evaluate(`['planning-panel','results-drawer','theme-toggle','restart','stage-card'].map(id=>{const n=document.getElementById(id);return [id,n.parentElement.className,n.previousElementSibling?.id||'']})`);
  await evaluate(`window.mobileCheckNodes=['origin','destination','speed','timeline','play','stage-card'].map(id=>document.getElementById(id));window.mobileCheckCanvas=document.querySelector('#viewport canvas');document.getElementById('speed').value='2';document.getElementById('speed').dispatchEvent(new Event('change'))`);
  for(const [width,height] of [[360,800],[390,844],[430,932],[844,390]]){
    await send('Emulation.setDeviceMetricsOverride',{width,height,deviceScaleFactor:1,mobile:true});
    await until("document.documentElement.classList.contains('mobile-layout')");
    await until(`Math.abs(document.querySelector('#viewport canvas')?.width/${await evaluate('devicePixelRatio')} - ${width}) < 2 || !!document.querySelector('#viewport>svg')`);
    assert.equal(await evaluate('document.documentElement.scrollWidth<=innerWidth'),true,'no page overflow');
    assert.equal(await evaluate("mobileCheckNodes.every(node=>node===document.getElementById(node.id)) && mobileCheckCanvas===document.querySelector('#viewport canvas') && document.getElementById('speed').value==='2'"),true,'control identity, speed and renderer survive resizing');
    const map=await rect('#viewport');assert.equal(map.x,0);assert.equal(map.width,width,'rail width reclaimed');
    assert.equal(await evaluate('document.getElementById("mobile-sheet-body").hidden'),true,'initially collapsed');
    const scenario=await rect('.scenario-bar'),layers=await rect('.map-top-controls'),badge=await rect('#mobile-disruption'),sheet=await rect('#mobile-sheet'),play=await rect('.playback-bar');
    assert.ok(sheet.y+sheet.height<=play.y,'sheet above playback');
    assert.ok(badge.y+badge.height<sheet.y,'usable map between controls');
    assert.ok(width>760?scenario.x+scenario.width<=layers.x:scenario.y+scenario.height<=layers.y,'scenario and layers do not overlap');
    for(const selector of ['#mobile-menu','#open-results','#mobile-sheet-toggle','#mobile-disruption','#mobile-legend','[data-view="surface"]','[data-view="underground"]','[data-view="both"]','[data-projection="2d"]','[data-projection="3d"]','[data-scenario="normal"]','[data-scenario="disrupted"]','[data-scenario="mitigated"]']){
      const r=await rect(selector);assert.ok(r.width>=44&&r.height>=44,selector+' 44px');assert.ok(r.x>=0&&r.x+r.width<=width,selector+' inside viewport');
    }
    await screenshot(`mobile-${width}-collapsed`);
    await tap('#mobile-sheet-toggle');
    assert.equal(await evaluate('document.getElementById("mobile-sheet-body").scrollWidth<=document.getElementById("mobile-sheet-body").clientWidth'),true,'no sheet overflow');
    assert.equal(await evaluate('document.getElementById("planning-panel").inert'),false);
    assert.equal(await evaluate('document.getElementById("results-drawer").inert'),true);
    assert.equal(await evaluate('document.getElementById("stage-card").closest("#pane-journey")!==null'),true);
    assert.equal(await evaluate('document.getElementById("speed").closest("#mobile-sheet-body")!==null'),true);
    await screenshot(`mobile-${width}-journey`);
    await tap('#open-results');
    assert.equal(await evaluate('document.getElementById("planning-panel").hidden'),true);
    assert.equal(await evaluate('document.getElementById("results-drawer").inert'),false);
    await screenshot(`mobile-${width}-results`);
    await tap('#mobile-menu');
    assert.equal(await evaluate('document.getElementById("results-drawer").hidden'),true);
    await tap('#theme-toggle');
    await tap('#mobile-sheet-close');
    await tap('#mobile-disruption');assert.equal(await evaluate('document.querySelector(".map-heading").closest("#mobile-disruption-details")!==null'),true);
    await tap('#mobile-sheet-close');
    await tap('#mobile-legend');assert.equal(await evaluate('document.querySelector(".map-legend").closest("#mobile-legend-content")!==null'),true);
    await send('Input.dispatchKeyEvent',{type:'keyDown',key:'Escape',code:'Escape'});
    assert.equal(await evaluate('document.getElementById("mobile-sheet-body").hidden'),true);
    assert.equal(await evaluate('document.activeElement.id'),'mobile-legend','Escape restores focus');
    await tap('[data-view="underground"]');await tap('[data-view="both"]');await tap('[data-view="surface"]');
    assert.equal(await evaluate('document.querySelector("[data-view=surface]").getAttribute("aria-pressed")'),'true');
    await tap('[data-projection="2d"]');await tap('[data-projection="3d"]');
    assert.equal(await evaluate('document.querySelector(\'[data-projection="3d"]\').getAttribute("aria-pressed")'),'true');
    assert.equal(await evaluate('document.getElementById("play").disabled'),true,'no fake journey when API unavailable');
    checks.push(`${width}×${height}: full-width map, 44px controls, no overflow/overlap, one sheet, inputs/results/details/menu/legend, Escape/focus, themes, layer/projection controls.`);
  }
  await send('Emulation.setDeviceMetricsOverride',{width:1366,height:900,deviceScaleFactor:1,mobile:false});
  await until("!document.documentElement.classList.contains('mobile-layout')");
  const restored=await evaluate(`['planning-panel','results-drawer','theme-toggle','restart','stage-card'].map(id=>{const n=document.getElementById(id);return [id,n.parentElement.className,n.previousElementSibling?.id||'']})`);
  assert.deepEqual(restored,desktop,'desktop DOM positions restored exactly');
  assert.equal(await evaluate("mobileCheckNodes.every(node=>node===document.getElementById(node.id)) && mobileCheckCanvas===document.querySelector('#viewport canvas') && document.getElementById('speed').value==='2'"),true,'same controls and playback speed restored to desktop');
  assert.equal((await rect('#viewport')).x,360);
  assert.equal(await evaluate('getComputedStyle(document.getElementById("mobile-sheet")).display'),'none');
  assert.equal(await evaluate('document.querySelector(".timeline-caption>span").textContent'),'Səfər simulyasiyası');
  await screenshot('desktop-restored');
  checks.push('Desktop control positions restored; rail/sidebar widths unchanged; renderer resized without replacing map DOM. Correct UTF-8 playback caption. Routing unavailable deliberately; no live journey evidence.');
  await send('Emulation.setDeviceMetricsOverride',{width:390,height:844,deviceScaleFactor:1,mobile:true});
  await send('Emulation.setEmulatedMedia',{features:[{name:'prefers-reduced-motion',value:'reduce'}]});
  await send('Page.navigate',{url:'http://citypilot-ui.test/?renderer=2d'});
  await until('document.getElementById("scene-loading")?.hidden===true');
  await until('document.getElementById("routing-status")?.dataset.state==="error"');
  assert.equal(await evaluate('!!document.querySelector("#viewport>svg")'),true,'direct phone load with 2D fallback');
  assert.equal(await evaluate('document.querySelector("[data-view=both]").disabled'),true,'2D retains disclosed exploded-view limitation');
  await tap('#mobile-sheet-toggle');
  const viewBox=await evaluate('document.querySelector("#viewport>svg").getAttribute("viewBox")');
  await evaluate('document.getElementById("mobile-sheet-body").scrollTop=150');
  await send('Input.dispatchMouseEvent',{type:'mouseWheel',x:190,y:400,deltaY:120,deltaX:0});
  assert.equal(await evaluate('document.querySelector("#viewport>svg").getAttribute("viewBox")'),viewBox,'panel scrolling leaves map camera alone');
  await tap('#mobile-sheet-close');
  await send('Input.dispatchMouseEvent',{type:'mouseWheel',x:190,y:400,deltaY:120,deltaX:0});
  await until(`document.querySelector('#viewport>svg').getAttribute('viewBox')!==${JSON.stringify(viewBox)}`);
  const zoomed=await evaluate('document.querySelector("#viewport>svg").getAttribute("viewBox")');
  await tap('#mobile-legend');await tap('#mobile-sheet-close');
  assert.equal(await evaluate('document.querySelector("#viewport>svg").getAttribute("viewBox")'),zoomed,'sheet changes preserve map camera');
  await screenshot('mobile-390-2d-reduced-motion');
  checks.push('Direct phone load: 2D fallback and reduced-motion preference; panel wheel scroll does not zoom map; map zoom works outside sheet; toggling sheet preserves camera.');
}
