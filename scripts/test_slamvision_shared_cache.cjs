// Regression: every shared player always has a Pages fallback before direct API.
"use strict";
const assert = require("node:assert/strict");
const fs = require("node:fs");
const vm = require("node:vm");
const manifest=JSON.parse(fs.readFileSync("research/slamvision-current.json","utf8")).channels;
const html=fs.readFileSync("slamvision-feed.html","utf8");
const helper=fs.readFileSync("slamvision-direct-fallback.js","utf8");
const shared=manifest.filter(c=>c.player_type==="shared"&&c.availability==="available");
const present=new Set(["njpw-destructi","njpw-g1climax","njpw-starrcade","njpw-wp","njpw-wk","njpw-wrestling","ain",
  "battlarts","big-japan","kaientai-dojo","michinoku-pro","osaka-pro","muta","fmw"]);
const uncovered=shared.filter(x=>!present.has(x.id));
const stamp=x=>new Date(Date.now()+x).toISOString();
function fixture(id, options={}){
 const slot={id:"p-"+id,title:"Program for "+id,start:stamp(-120000),
             end:stamp(options.expired?-1000:3600000),stream_url:"https://archive.org/download/sample/"+id+".mp4"};
 const entry={id:options.wrong?"wrong-feed":id,name:id,current:slot,up_next:[]};
 const channels={[id]:entry};
 if(options.duplicate)channels.second={...entry};
 return {generated_at:stamp(options.stale?-3600000:-45000),channels};
}
async function check(id,opts={}){
 const urls=[];const snap=fixture(id,opts);
 const fetch=async url=>{
  urls.push(url);
  if(url.includes("/api/channels/")){
   if(opts.apiDown!==false)throw Error("API intentionally unavailable");
   return {ok:true,status:200,json:async()=>({
    channel:{id,name:id},current:{
     start:stamp(-60000),end:stamp(3500000),
     program:{id:"fresh",title:"Live "+id,stream_url:"https://archive.org/download/live/"+id+".mp4"}},up_next:[]})};
  }
  return {ok:true,status:200,json:async()=>snap};
 };
 const ctx={window:{fetch},AbortController,Date,setTimeout,clearTimeout,Map};
 vm.runInNewContext(helper,ctx);
 const cache="./slamvision/shared-live.json?t=123";
 try{
  const data=await ctx.window.SlamVisionDirect.resolve({cachedUrl:cache,channel:id,sourceId:id});
  return {data,urls};
 }catch(error){return {error:String(error),urls}}
}
(async()=>{
 assert(html.includes("'./slamvision/shared-live.json?t='+Date.now()"));
 assert.equal(shared.length,92,"Expected 92 shared player URLs from initial catalog");
 assert.equal(uncovered.length,78);
 for(const item of uncovered){
  const r=await check(item.id);
  assert(!r.error,"Pages fallback failed for "+item.id+": "+r.error);
  assert.equal(r.data.channels[item.id].id,item.id);
  assert.equal(r.urls.length,1,"Fresh Pages cache must prevent direct API for "+item.id);
  assert(r.urls[0].includes("shared-live.json"));
 }
 let r=await check("year-1985",{stale:true});
 assert(!r.error && r.urls.length===2,"Still-current Pages must survive live outage");
 r=await check("year-1985",{stale:true,expired:true});
 assert(r.error,"Expired Pages must be rejected");
 r=await check("year-1985",{wrong:true});
 assert(r.error,"Wrong ID must be rejected");
 r=await check("year-1985",{duplicate:true});
 assert.equal(r.data.channels['year-1985'].id,'year-1985',"Direct key should match expected");
 r=await check("year-1985",{stale:true,apiDown:false});
 assert(!r.error && r.data.channels['year-1985'].current.title==="Live year-1985");
 console.log("PASS: all 78 previously uncovered feeds load valid cached program with upstream API offline; stale/expired/wrong-feed recovery");
})().catch(e=>{console.error(e);process.exit(1)});
