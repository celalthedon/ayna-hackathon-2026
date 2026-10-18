/** Display labels and list summaries only. Routing and playback keep every leg. */
const MODES={walk:'Piyada',bike:'Velosiped',bus:'Avtobus',metro:'Metro',transfer:'Keçid',wait:'Gözləmə',park:'Parklanma',gap:'Həndəsə boşluğu'};
export const modeLabel=mode=>MODES[mode]||'Digər mərhələ';

function compatibleWalks(left,right) {
  if(left.mode!=='walk'||right.mode!=='walk'||left.gap||right.gap||left.layer!==right.layer||left.end!==right.start)return false;
  for(const leg of [left,right])if(['wait_min','ride_min','transfer_min'].some(k=>(leg.physical?.[k]||0)!==0))return false;
  const end=left.geometry?.at(-1),start=right.geometry?.[0];
  if(!end||!start||end[0]!==start[0]||end[1]!==start[1])return false;
  const to=left.physical?.to_id,from=right.physical?.from_id;
  return !to||!from||to===from;
}

export function summarizeLegs(legs) {
  const summaries=[];
  for(const leg of legs) {
    let summary=summaries.at(-1);
    if(!summary||!compatibleWalks(summary.legs.at(-1),leg)) {
      summary={id:leg.id,mode:leg.mode,title:leg.mode==='walk'&&!leg.gap?'Piyada':leg.title,
        start:leg.start,end:leg.end,seconds:0,gap:!!leg.gap,legIds:[],legs:[]};
      summaries.push(summary);
    }
    summary.end=leg.end;summary.seconds+=leg.seconds;
    summary.legIds.push(leg.id);summary.legs.push(leg);
  }
  return summaries;
}
