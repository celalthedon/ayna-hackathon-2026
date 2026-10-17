export function distance(a,b){return Math.hypot(a[0]-b[0],a[1]-b[1]);}
export function pointAt(path,t){if(!path?.length)return null;if(path.length===1)return [...path[0]];const lens=path.slice(1).map((p,i)=>distance(path[i],p));let remaining=Math.max(0,Math.min(1,t))*lens.reduce((a,b)=>a+b,0);for(let i=0;i<lens.length;i++){if(remaining<=lens[i]||i===lens.length-1){const f=lens[i]?remaining/lens[i]:0;return[path[i][0]+(path[i+1][0]-path[i][0])*f,path[i][1]+(path[i+1][1]-path[i][1])*f];}remaining-=lens[i];}return [...path.at(-1)];}
export function slicePath(path,a,b){const total=path.slice(1).reduce((s,p,i)=>s+distance(path[i],p),0);let len=0;const points=[pointAt(path,a)];for(let i=1;i<path.length;i++){len+=distance(path[i-1],path[i]);if(len>total*a&&len<total*b)points.push(path[i]);}points.push(pointAt(path,b));return points;}
export class Playback{
 constructor(legs=[]){this.speed=1;this.setLegs(legs);}
 setLegs(legs){let time=0;this.legs=legs.map(l=>{const result={...l,start:time,end:time+l.seconds};time+=l.seconds;return result;});this.duration=time;this.restart();}
 restart(){this.elapsed=0;this.playing=false;this.blockedGap=null;this.handled=new Set();}
 toggle(){if(!this.duration||this.blockedGap)return;if(this.elapsed>=this.duration)this.restart();this.playing=!this.playing;}
 seek(value){this.elapsed=Math.max(0,Math.min(this.duration,value));this.blockedGap=null;this.handled=new Set(this.legs.filter(l=>l.gap&&l.start<=this.elapsed).map(l=>l.id));if(this.elapsed>=this.duration)this.playing=false;}
 skipGap(){if(!this.blockedGap)return;this.handled.add(this.blockedGap.id);this.elapsed=this.blockedGap.start;this.blockedGap=null;this.playing=true;}
 tick(dt){if(!this.playing)return;const end=Math.min(this.duration,this.elapsed+Math.max(0,dt)*this.speed);const gap=this.legs.find(l=>l.gap&&!this.handled.has(l.id)&&l.start>=this.elapsed-1e-8&&l.start<=end);if(gap){this.elapsed=gap.start;this.blockedGap=gap;this.playing=false;return;}this.elapsed=end;if(end>=this.duration)this.playing=false;}
 current(){if(!this.legs.length)return{leg:{id:'empty',mode:'walk',title:'Marşrutdan səfər seçin',layer:'surface',seconds:0},progress:0,position:null};if(this.blockedGap)return{leg:this.blockedGap,progress:0,position:null};let leg=this.legs.find(l=>!l.gap&&this.elapsed<l.end)||this.legs.filter(l=>!l.gap).at(-1);const progress=leg.seconds?Math.max(0,Math.min(1,(this.elapsed-leg.start)/leg.seconds)):0;return{leg,progress,position:pointAt(leg.geometry,progress)};}
}
export const timeText=value=>`${Math.floor(value/60).toString().padStart(2,'0')}:${Math.floor(value%60).toString().padStart(2,'0')}`;
