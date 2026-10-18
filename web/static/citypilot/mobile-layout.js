// Move the existing controls, never clone them: values, listeners and playback
// references survive breakpoint changes. The map canvas stays in its container.
export const PHONE_QUERY='(max-width: 760px), (max-width: 960px) and (max-height: 500px)';

export function mountMobileLayout({document:doc=globalThis.document,media=matchMedia(PHONE_QUERY),activatePlanning,onResize}) {
  const $=id=>doc.getElementById(id);
  const create=(tag,attrs={},text)=>{const node=doc.createElement(tag);for(const [key,value] of Object.entries(attrs))node.setAttribute(key,value);if(text)node.textContent=text;return node;};
  const button=(id,text)=>create('button',{id,type:'button','aria-controls':'mobile-sheet-body','aria-expanded':'false'},text);
  const menuButton=button('mobile-menu','Menyu');
  doc.querySelector('.header-actions').append(menuButton);
  const sheet=create('section',{id:'mobile-sheet','aria-label':'Səfər və xəritə paneli'});
  const heading=create('div',{class:'mobile-sheet-heading'});
  const toggle=button('mobile-sheet-toggle','Səfər və nəticələr');
  const close=create('button',{id:'mobile-sheet-close',type:'button','aria-label':'Paneli yığ'},'Yığ ↓');
  heading.append(toggle,close);
  const body=create('div',{id:'mobile-sheet-body',hidden:'',tabindex:'-1',role:'region','aria-label':'Səfər və xəritə idarəetməsi'});
  sheet.append(heading,body);$('map-workspace').append(sheet);
  const menu=create('nav',{'aria-label':'İş sahəsi menyusu',id:'mobile-menu-content'});
  const details=create('section',{'aria-label':'Ssenari haqqında',id:'mobile-disruption-details'});
  const legend=create('section',{'aria-label':'Xəritə işarələri',id:'mobile-legend-content'});
  const badge=button('mobile-disruption','Nizami – 28 May · məlumat');
  const legendButton=button('mobile-legend','İşarələr');
  $('map-workspace').append(badge,legendButton);
  const playbackOptions=create('div',{class:'mobile-playback-options'});
  const optionsLabel=create('h3',{},'Simulyasiya idarəetməsi');
  playbackOptions.append(optionsLabel);
  const sections={planning:$('planning-panel'),results:$('results-drawer'),menu,details,legend};
  let active=false,current=null,opener=null;
  const moves=[];
  function move(node,parent){const placeholder=doc.createComment('desktop position');node.before(placeholder);moves.push({node,placeholder});parent.append(node);}
  const triggers=[menuButton,toggle,badge,legendButton,$('open-results')];
  const updateBadge=()=>{badge.textContent=doc.querySelector('[data-scenario="normal"]').getAttribute('aria-pressed')==='true'?'Normal şəbəkə · məlumat':'Nizami – 28 May · kəsinti';};
  const scenarioObserver=new MutationObserver(updateBadge);
  scenarioObserver.observe($('scenario-description'),{childList:true});updateBadge();
  function render(){
    body.hidden=!current;
    close.hidden=!current;
    sheet.classList.toggle('expanded',!!current);
    for(const [key,node] of Object.entries(sections)){node.hidden=key!==current;node.inert=key!==current;}
    $('results-drawer').setAttribute('aria-hidden',String(current!=='results'));
    for(const trigger of triggers)trigger.setAttribute('aria-expanded',String(!!current&&(trigger===opener||trigger===toggle)));
    toggle.textContent=current?({planning:'Səfər və tədbirlər',results:'Nəticələr',menu:'Menyu',details:'Ssenari haqqında',legend:'Xəritə işarələri'}[current]):'Səfər və nəticələr ↑';
    body.scrollTop=0;
    onResize();
  }
  function open(section,trigger=toggle){if(!active)return;current=section;opener=trigger;render();body.focus({preventScroll:true});}
  function collapse(){if(!active)return;const focus=opener;current=null;render();if(focus?.isConnected)focus.focus({preventScroll:true});}
  function planning(tab='journey',trigger=toggle){activatePlanning(tab);open('planning',trigger);}
  const action=(text,handler)=>{const b=create('button',{type:'button'},text);b.onclick=handler;menu.append(b);return b;};
  action('Səfər və simulyasiya',()=>planning('journey',menuButton));
  action('Xəritə qatları',()=>planning('layers',menuButton));
  action('Tədbirlər',()=>planning('actions',menuButton));
  action('Nəticələr',()=>open('results',menuButton));
  action('Ssenari haqqında',()=>open('details',menuButton));
  action('Xəritə işarələri',()=>open('legend',menuButton));
  menuButton.onclick=()=>current==='menu'?collapse():open('menu',menuButton);
  toggle.onclick=()=>current?collapse():planning();close.onclick=collapse;
  badge.onclick=()=>current==='details'?collapse():open('details',badge);
  legendButton.onclick=()=>current==='legend'?collapse():open('legend',legendButton);
  const oldControls=new Map();
  function enter(){
    // Close the desktop drawer before intercepting its controls.
    $('close-results').click();
    active=true;current=null;
    for(const node of Object.values(sections))body.append(node);
    // Planning/results must also return to their exact original positions.
  }
  function update(next=media.matches){
    if(typeof next!=='boolean')next=media.matches;
    if(next===active)return;
    if(next){
      // Record all original positions before moving either container.
      for(const id of ['planning-panel','results-drawer']){const node=$(id),placeholder=doc.createComment('desktop position');node.before(placeholder);moves.push({node,placeholder});}
      enter();
      move(doc.querySelector('.map-heading'),details);
      move(doc.querySelector('.map-legend'),legend);
      move($('stage-card'),$('pane-journey'));
      $('pane-journey').append(playbackOptions);
      move($('restart'),playbackOptions);move(doc.querySelector('.speed-control'),playbackOptions);
      for(const node of [$('theme-toggle'),$('show-info'),$('focus-closure'),$('reset-camera')])move(node,menu);
      for(const id of ['show-info','rail-info']){const b=$(id);oldControls.set(b,b.onclick);b.onclick=()=>{collapse();oldControls.get(b)();};}
      $('open-results').setAttribute('aria-controls','mobile-sheet-body');
      doc.documentElement.classList.add('mobile-layout');
      render();
    }else{
      active=false;current=null;
      // Reverse order restores children before their containing panel.
      for(const {node,placeholder} of moves.reverse()){placeholder.replaceWith(node);}
      moves.length=0;
      playbackOptions.remove();
      for(const [node,handler] of oldControls)node.onclick=handler;oldControls.clear();
      for(const node of Object.values(sections)){node.hidden=false;node.inert=false;}
      $('results-drawer').inert=true;$('results-drawer').classList.remove('open');$('results-drawer').setAttribute('aria-hidden','true');
      $('open-results').setAttribute('aria-controls','results-drawer');$('open-results').setAttribute('aria-expanded','false');
      doc.documentElement.classList.remove('mobile-layout');
      onResize();
    }
  }
  const escape=e=>{if(active&&current&&e.key==='Escape'){e.preventDefault();e.stopImmediatePropagation();collapse();}};
  doc.addEventListener('keydown',escape,true);
  media.addEventListener('change',update);update();
  return {get active(){return active;},planning,collapse,results:openResults=>openResults?open('results',$('open-results')):collapse(),
    destroy(){update(false);scenarioObserver.disconnect();media.removeEventListener('change',update);doc.removeEventListener('keydown',escape,true);sheet.remove();menuButton.remove();badge.remove();legendButton.remove();}};
}
