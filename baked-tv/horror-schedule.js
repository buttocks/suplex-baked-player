// Shared self-updating Horror Nightshift catalog and deterministic TV clock.
// Each client reads the latest manifests already published in this repository.
// There is no dependency on YouTube or a Baked.live playlist extension.
const SOURCE_IDS=['daily-dread','graveyard-shift','it-came-from'];
const CACHE_KEY='bakedtv-horror-manifests-v1';
const REFRESH_MS=10*60*1000;
const ANCHOR=Date.UTC(2026,0,1);
const FALLBACK=[{"id":"night","name":"Night of the Living Dead (1968)","archive":"Night.Of.The.Living.Dead_1080p","file":"NightOfTheLivingDead.mp4","seconds":5753},{"id":"antimemetics","name":"There Is No Antimemetics Division (2024)","seconds":1000,"provider":"commons","url":"https://upload.wikimedia.org/wikipedia/commons/1/13/There_Is_No_Antimemetics_Division.webm","source":"https://commons.wikimedia.org/wiki/File:There_Is_No_Antimemetics_Division.webm"},{"id":"vampire-bat","name":"The Vampire Bat (1933)","seconds":3760,"provider":"commons","url":"https://upload.wikimedia.org/wikipedia/commons/5/5b/The_Vampire_Bat_(1933).webm","source":"https://commons.wikimedia.org/wiki/File:The_Vampire_Bat_(1933).webm"},{"id":"haunted","name":"House on Haunted Hill (1959)","archive":"The_House_On_Haunted_Hill","file":"The_House_On_Haunted_Hill.mp4","seconds":4483},{"id":"usher","name":"The Fall of the House of Usher (1928)","seconds":792,"provider":"commons","url":"https://upload.wikimedia.org/wikipedia/commons/1/19/The_Fall_of_the_House_of_Usher_(1928).webm","source":"https://commons.wikimedia.org/wiki/File:The_Fall_of_the_House_of_Usher_(1928).webm"},{"id":"night-ghouls","name":"Night of the Ghouls (1959)","seconds":4166,"provider":"commons","url":"https://upload.wikimedia.org/wikipedia/commons/6/6d/Night_of_the_Ghouls_(1959).webm","source":"https://commons.wikimedia.org/wiki/File:Night_of_the_Ghouls_(1959).webm"},{"id":"carnival","name":"Carnival of Souls (1962)","archive":"CarnivalofSouls","file":"CarnivalOfSouls.mp4","seconds":4980},{"id":"cat-canary","name":"The Cat and the Canary (1927)","seconds":5039,"provider":"commons","url":"https://upload.wikimedia.org/wikipedia/commons/9/96/The_Cat_and_the_Canary_(1927).webm","source":"https://commons.wikimedia.org/wiki/File:The_Cat_and_the_Canary_(1927).webm"},{"id":"dementia","name":"Dementia 13 (1963)","seconds":4496,"provider":"commons","url":"https://upload.wikimedia.org/wikipedia/commons/1/13/Dementia_13.webm","source":"https://commons.wikimedia.org/wiki/File:Dementia_13.webm"},{"id":"phantom","name":"The Phantom of the Opera (1925)","archive":"ThePhantomoftheOpera","file":"Phantom_of_the_Opera_512kb.mp4","seconds":6389},{"id":"haunted-keaton","name":"The Haunted House (1921)","seconds":1236,"provider":"commons","url":"https://upload.wikimedia.org/wikipedia/commons/b/bd/The_Haunted_House_(1921).webm","source":"https://commons.wikimedia.org/wiki/File:The_Haunted_House_(1921).webm"},{"id":"jekyll","name":"Dr. Jekyll and Mr. Hyde (1920)","seconds":4762,"provider":"commons","url":"https://upload.wikimedia.org/wikipedia/commons/0/0d/Dr._Jekyll_and_Mr._Hyde_(1920).webm","source":"https://commons.wikimedia.org/wiki/File:Dr._Jekyll_and_Mr._Hyde_(1920).webm"},{"id":"caligari","name":"The Cabinet of Dr. Caligari (1920)","archive":"DasKabinettdesDoktorCaligariTheCabinetofDrCaligari","file":"The_Cabinet_of_Dr._Caligari_512kb.mp4","seconds":3061},{"id":"nosferatu","name":"Nosferatu (1922, English intertitles)","seconds":5060,"provider":"commons","url":"https://upload.wikimedia.org/wikipedia/commons/0/02/Nosferatu_(1922%2C_English_titles_1947).webm","source":"https://commons.wikimedia.org/wiki/File:Nosferatu_(1922%2C_English_titles_1947).webm"},{"id":"plan9","name":"Plan 9 from Outer Space (1959)","seconds":4697,"provider":"commons","url":"https://upload.wikimedia.org/wikipedia/commons/e/e8/Plan_9_from_Outer_Space_(1959_film).webm","source":"https://commons.wikimedia.org/wiki/File:Plan_9_from_Outer_Space_(1959_film).webm"}];
const BROADCAST_ROOT=new URL('../broadcast/',import.meta.url);
let memo=null,loadedAt=0,inflight=null;

function sourceUrl(id,file){
 return 'https://archive.org/download/'+encodeURIComponent(id)+'/'+file.split('/').map(encodeURIComponent).join('/');
}
function normalizeTitle(title){
 return String(title||'').normalize('NFKD').replace(/[\u0300-\u036f]/g,'').toLowerCase()
  .replace(/\(\s*(?:18|19|20)\d{2}\s*\)/g,'').replace(/[^a-z0-9]+/g,'').trim();
}
function isValidFile(file){
 return typeof file==='string'&&file.length>3&&file.length<500
  &&/\.(?:mp4|webm|ogv|m4v)$/i.test(file)
  &&!file.startsWith('/')&&!file.includes('..')&&!file.includes('\\')&&!file.includes('://');
}
function fromItem(item,source){
 if(!item||typeof item!=='object'||!item.id||!item.title)return null;
 const file=item.mp4||item.file;
 if(!isValidFile(file)||!Number.isFinite(Number(item.duration)))return null;
 const start=Math.max(0,Number(item.inS)||0);
 const duration=Number(item.duration);
 const out=item.outS==null?duration:Number(item.outS);
 const length=Math.floor(Math.min(duration,out)-start);
 if(length<50||length>8*3600)return null;
 const year=/^(18|19|20)\d{2}$/.test(String(item.year||''))?String(item.year):'';
 const title=String(item.title).trim();
 return {
  id:'manifest:'+source+':'+String(item.id)+'|'+file,
  name:title+(year&&!title.includes(year)?' ('+year+')':''),
  seconds:length,
  archive:String(item.id),
  file,
  startSeconds:start,
  collection:source
 };
}
function readStored(){
 try{
  const cache=JSON.parse(localStorage.getItem(CACHE_KEY)||'{}');
  if(cache?.savedAt>Date.now()-7*86400000&&cache?.data&&typeof cache.data==='object')return cache.data;
 }catch{}
 return {};
}
function writeStored(data){
 try{localStorage.setItem(CACHE_KEY,JSON.stringify({savedAt:Date.now(),data}));}catch{}
}
async function jsonFrom(relative){
 if(!/^(?:lineup\.json|manifests\/[a-z0-9-]+\/v\d+\.json)$/.test(relative))throw Error('Invalid manifest path');
 const controller=new AbortController();
 const handle=setTimeout(()=>controller.abort(),14000);
 try{
  const url=new URL(relative,BROADCAST_ROOT);
  const response=await fetch(url,{cache:'no-store',signal:controller.signal});
  if(!response.ok)throw Error('HTTP '+response.status+' for '+relative);
  return await response.json();
 }finally{clearTimeout(handle);}
}
function combine(sourceSets){
 const seen=new Set();
 const films=[];
 // Preserve existing originals/Commons; prefer one copy of repeated movie titles.
 for(const f of FALLBACK){
  const key=normalizeTitle(f.name);
  if(!key||seen.has(key))continue;
  seen.add(key);
  films.push({...f,startSeconds:0,collection:f.provider||'archive'});
 }
 for(const source of SOURCE_IDS){
  const subset=(sourceSets[source]?.films||[]).slice().sort((a,b)=>a.name.localeCompare(b.name)||a.id.localeCompare(b.id));
  for(const f of subset){
   const key=normalizeTitle(f.name);
   if(!key||seen.has(key))continue;
   seen.add(key);
   films.push(f);
  }
 }
 const starts=[];
 let sum=0;
 for(const f of films){starts.push(sum);sum+=f.seconds*1000;}
 const versions=SOURCE_IDS.map(s=>s+':'+(sourceSets[s]?.version||'-')).join('|');
 return {films,starts,cycleMs:sum,anchorMs:ANCHOR,versions,sourceCount:SOURCE_IDS.filter(s=>sourceSets[s]?.films?.length).length,
   upstreamCount:SOURCE_IDS.reduce((n,s)=>n+(sourceSets[s]?.films?.length||0),0),
   signature:versions+'|'+films.map(f=>f.id+':'+f.seconds).join(';')};
}
export function fallbackHorrorCatalog(){return combine({});}
export async function loadHorrorCatalog({force=false}={}){
 if(!force&&memo&&Date.now()-loadedAt<REFRESH_MS)return memo;
 if(inflight)return inflight;
 inflight=(async()=>{
  const saved=readStored();
  const sourceSets={...saved};
  try{
   const lineup=await jsonFrom('lineup.json');
   if(!Array.isArray(lineup.channels))throw Error('Invalid lineup');
   const tasks=SOURCE_IDS.map(async source=>{
    const row=lineup.channels.find(c=>c.id===source);
    if(!row||!Array.isArray(row.versions)||!row.versions.length)throw Error(source+' not listed');
    const version=row.versions.reduce((best,v)=>!best||Number(v.v)>Number(best.v)?v:best,null);
    const path=String(version.manifest||'');
    if(!path.startsWith('manifests/'+source+'/'))throw Error(source+' invalid path');
    if(sourceSets[source]?.version===path&&Array.isArray(sourceSets[source].films))return;
    const manifest=await jsonFrom(path);
    if(!Array.isArray(manifest.items)||manifest.channel!==source)throw Error(source+' invalid manifest');
    const films=manifest.items.map(x=>fromItem(x,source)).filter(Boolean);
    if(films.length<5)throw Error(source+' empty catalog');
    sourceSets[source]={version:path,films};
   });
   await Promise.allSettled(tasks);
  }catch(err){
   console.warn('Horror Nightshift feed is temporarily unavailable:',err);
  }
  const combined=combine(sourceSets);
  if(combined.sourceCount)writeStored(sourceSets);
  memo=combined;loadedAt=Date.now();
  return combined;
 })().finally(()=>{inflight=null;});
 return inflight;
}
export function horrorAt(catalog,at=Date.now()){
 if(!catalog?.films?.length||!catalog.cycleMs)throw Error('Empty horror catalog');
 const offset=((at-catalog.anchorMs)%catalog.cycleMs+catalog.cycleMs)%catalog.cycleMs;
 const starts=catalog.starts;
 let lo=0,hi=starts.length-1;
 while(lo<hi){const mid=Math.floor((lo+hi+1)/2);if(starts[mid]<=offset)lo=mid;else hi=mid-1;}
 const film=catalog.films[lo],startMs=at-(offset-starts[lo]);
 return {film,startMs,endMs:startMs+film.seconds*1000,key:film.id+'|'+startMs,position:lo};
}
export function horrorUpcoming(catalog,count=12,at=Date.now()){
 const result=[];
 let cursor=at;
 for(let i=0;i<Math.min(count,catalog.films.length);i++){
  const position=horrorAt(catalog,cursor);
  result.push({title:position.film.name,film:position.film,startMs:position.startMs,endMs:position.endMs});
  cursor=position.endMs+1;
 }
 return result;
}
export function horrorVideoUrl(film){
 if(film.provider==='commons')return film.url;
 return sourceUrl(film.archive,film.file);
}
