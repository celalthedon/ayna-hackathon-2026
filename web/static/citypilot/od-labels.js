/** Display-only fixed-OD labels. Values are always the original saved IDs. */
const natural=new Intl.Collator('az',{numeric:true,sensitivity:'base'});
const GROUPS=[['metro','Metro çıxışları'],['terminal','Avtovağzal'],['network','Şəbəkə nöqtələri']];
const kind=item=>item.properties?.origin_kind==='terminal'||item.id.startsWith('origin:terminal:')?'terminal':
  item.properties?.origin_kind==='metro_exit'||/^(origin|destination):metro_exit:/.test(item.id)?'metro':'network';

export function groupODOptions(items,exits) {
  // The approved map asset is identity-checked against the API before use.
  // Match stable access IDs, never row indices or coordinates.
  const names=new Map(exits.map(exit=>[exit.id,exit.name]));
  const network=items.filter(item=>kind(item)==='network').slice().sort((a,b)=>natural.compare(a.id,b.id));
  const numbers=new Map(network.map((item,index)=>[item.id,index+1]));
  const options=items.map(item=>{
    const group=kind(item),properties=item.properties||{};
    let heading;
    if(group==='terminal')heading='Bakı Beynəlxalq Avtovağzal';
    else if(group==='metro') {
      const access=item.id.replace(/^(origin|destination):/,'');
      heading=properties.station_name&&properties.exit_name?[properties.station_name,properties.exit_name].join(' · '):names.get(access)||'Metro çıxışı · adı mövcud deyil';
    } else heading='Şəbəkə nöqtəsi '+numbers.get(item.id);
    const coordinates=item.coordinates;
    const suffix=group==='network'&&Array.isArray(coordinates)&&coordinates.length===2&&coordinates.every(Number.isFinite)?
      ` · ${coordinates[1].toFixed(5)}, ${coordinates[0].toFixed(5)}`:'';
    return {value:item.id,group,label:heading+suffix,heading};
  });
  return GROUPS.map(([key,label])=>({key,label,options:options.filter(option=>option.group===key).sort((a,b)=>natural.compare(a.heading,b.heading)||natural.compare(a.value,b.value))})).filter(group=>group.options.length);
}

export function odJourneyHeading(origin,destination) {
  return origin&&destination?origin+' → '+destination:'Bir səfər, bir neçə mərhələ.';
}
