// Check the seven Puro GitHub Pages backup feeds in offline and network-failure cases.
"use strict";
const assert=require("node:assert/strict");
const fs=require("node:fs");
const vm=require("node:vm");
const js=fs.readFileSync("slamvision-direct-fallback.js","utf8");
const html=fs.readFileSync("slamvision-feed.html","utf8");
const ids=["battlarts","big-japan","kaientai-dojo","michinoku-pro","osaka-pro","muta","fmw"];
const now=Date.now(),ts=n=>new Date(now+n).toISOString();
const prog=id=>({id:id+"-show",title:id+" live wrestling",stream_url:"https://archive.org/download/test/"+id+".mp4",start:ts(-60000),end:ts(3600000)});
function page(id,{age=50000,wrong=false,expired=false,duplicate=false}={}){
 const p=prog(id);if(expired)p.end=ts(-5000);
 const entry={id:wrong?"unrelated-feed":id,name:id,current:p,up_next:[]};
 const obj={generated_at:ts(-age),channels:{"33":entry}};
 if(duplicate)obj.channels["84"]={...entry};
 return obj;
}
function direct(id){
 return {channel:{id,name:id,number:999},current:{start:ts(-60000),end:ts(3600000),
          program:{id:"upstream",title:id+" upstream",stream_url:"https://archive.org/download/test/"+id+".mp4"}},
         up_next:[],server_time:ts(0)};
}
async function run(id,{saved=page(id),apiFail=true}={}){
 const urls=[];
 const fetch=async url=>{
  urls.push(String(url));
  if(String(url).includes("ring-channel-tv")){
   if(apiFail)throw Error("upstream temporarily unavailable");
   return {ok:true,status:200,json:async()=>direct(id)};
  }
  return {ok:true,status:200,json:async()=>saved};
 };
 const ctx={window:{fetch},AbortController,Date,setTimeout,clearTimeout,Map};
 vm.runInNewContext(js,ctx);
 try{
  const result=await ctx.window.SlamVisionDirect.resolve({
   cachedUrl:"./slamvision/puro-live.json?t=123",channel:id,sourceId:id
  });
  return {result,urls};
 }catch(e){return {error:String(e),urls}}
}
(async()=>{
 assert(html.includes("puro-live.json") && ids.every(id=>html.includes("'"+id+"'")),"All seven Puro embeds must use the cached JSON");
 for(const id of ids){
  const r=await run(id);
  assert(!r.error,id+" should tune from Pages with API down: "+r.error);
  assert.equal(r.result.channels[id].id,id);
  assert.equal(r.urls.length,1,"Fresh backup must bypass upstream");
 }
 let r=await run("battlarts",{saved:page("battlarts",{age:3600000})});
 assert(!r.error && r.urls.length===2,"Stale but still-current program should survive API outage");
 r=await run("battlarts",{saved:page("battlarts",{age:3600000,expired:true})});
 assert(r.error && r.error.includes("upstream temporarily unavailable"),"Expired backup must not show as live");
 r=await run("battlarts",{saved:page("battlarts",{wrong:true})});
 assert(r.error,"Unrelated feed substitution must be refused");
 r=await run("battlarts",{saved:page("battlarts",{duplicate:true})});
 assert(r.error,"Duplicate identity in Pages must be refused");
 r=await run("battlarts",{saved:page("battlarts",{age:3600000}),apiFail:false});
 assert(!r.error && r.result.channels.battlarts.current.title==="battlarts upstream","Direct API should refresh aged backup");
 console.log("PASS: seven Puro cached fallbacks, expiry, exact feed identity, duplicate rejection and live recovery");
})().catch(e=>{console.error(e);process.exit(1)});
