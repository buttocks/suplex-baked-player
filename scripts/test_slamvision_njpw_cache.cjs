// Regression tests for original NJPW cached snapshots + seven new stable-ID pages.
"use strict";
const assert=require("node:assert/strict");
const fs=require("node:fs");
const vm=require("node:vm");
const code=fs.readFileSync("slamvision-direct-fallback.js","utf8");
const page=fs.readFileSync("slamvision-feed.html","utf8");
const ids=["njpw-destructi","njpw-g1climax","njpw-starrcade",
           "njpw-wp","njpw-wk","njpw-wrestling","ain"];
const now=Date.now(),clock=x=>new Date(now+x).toISOString();
const slot=id=>({id:id+"-program",title:id+" Live",start:clock(-120000),end:clock(3600000),
                 stream_url:"https://archive.org/download/test/"+id+".mp4"});
async function test(id,{age=30000,upstreamFail=true,cacheId=id,duplicate=false,expired=false}={}){
 const key="old-dial";
 const channel={id:cacheId,name:id,current:{...slot(id),end:clock(expired?-1000:3600000)},up_next:[]};
 const data={generated_at:clock(-age),channels:{[key]:channel}};
 if(duplicate)data.channels.duplicate={...channel};
 let calls=[];
 const fetch=async url=>{
   calls.push(String(url));
   if(url.includes("ring-channel-tv")){
     if(upstreamFail)throw new Error("Upstream network unavailable");
     return{ok:true,status:200,json:async()=>({
       channel:{id,name:id},current:{start:clock(-120000),end:clock(3600000),
       program:{id:"live",title:id,stream_url:"https://archive.org/download/test/"+id+".mp4"}},up_next:[]})};
   }
   return {ok:true,status:200,json:async()=>data};
 };
 const context={window:{fetch},Date,setTimeout,clearTimeout,AbortController,Map};
 vm.runInNewContext(code,context);
 const url="./slamvision/njpw-live.json?t=123";
 try{
 const result=await context.window.SlamVisionDirect.resolve({cachedUrl:url,channel:id,sourceId:id});
 return{success:true,result,calls};
 }catch(error){return{success:false,error:String(error),calls}};
}
(async()=>{
 assert(page.includes("'njpw-destructi'")&&page.includes("'ain'")&&page.includes("njpw-live.json"),"New NJPW pages must request a cached backup");
 for(const id of ids){
   const r=await test(id);
   assert(r.success,"Cached NJPW should work even while live API offline "+id+": "+r.error);
   assert.equal(r.result.channels[id].id,id);
   assert.equal(r.calls.length,1,"Fresh cache should bypass broken upstream");
 }
 let r=await test("njpw-wp",{age:3600000});
 assert(r.success,"Stale-but-still-playing snapshot must cover upstream outage");
 assert.equal(r.calls.length,2,"Stale data should also attempt API");
 r=await test("njpw-wp",{age:3600000,expired:true});
 assert(!r.success,"Expired backup cannot impersonate live program");
 r=await test("njpw-wp",{cacheId:"other-promotion"});
 assert(!r.success,"Wrong feed identity must never be substituted");
 r=await test("njpw-wp",{duplicate:true});
 assert(!r.success,"Ambiguous duplicated identities must not be substituted");
 r=await test("njpw-wp",{age:3600000,upstreamFail:false});
 assert(r.success,"Valid direct API should replace an old snapshot");
 console.log("PASS: seven NJPW cache fallbacks; stale current shows, expired rejection, wrong/duplicate identity and live recovery");
})().catch(e=>{console.error(e);process.exit(1)});
