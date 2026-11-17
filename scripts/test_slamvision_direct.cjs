// Regression tests for the browser-side SlamVision fallback; no network required.
"use strict";
const assert = require("node:assert/strict");
const fs = require("node:fs");
const vm = require("node:vm");
const js = fs.readFileSync("slamvision-direct-fallback.js", "utf8");
const now = Date.now();
const stamp = (offset) => new Date(now + offset).toISOString();
const slot = (start, end, id="show-1") => ({
  start:stamp(start), end:stamp(end),
  program:{id,title:"WWF Raw Is War",stream_url:"https://archive.org/download/example/show.mp4"}
});
function cached(age, start=-60000, end=3600000, id="wwf-90-00") {
  return {generated_at:stamp(-age),channels:{"52":{id,
    current:{id:"saved",title:"WWF Raw Is War",stream_url:"https://archive.org/download/example/show.mp4",
             start:stamp(start),end:stamp(end)},
    up_next:[]}}};
}
function upstream(id="wwf-90-00"){
 return {channel:{id,number:112,name:"WWF 1990-2000"},
         current:slot(-10000,3600000),up_next:[],server_time:stamp(0)};
}
async function trial(page, live, expectApi) {
 let pages=0, api=0;
 const fetch = async (url,options)=>{
   if(url.includes("ring-channel-tv")){api++; if(live instanceof Error)throw live;
     return {ok:true,status:200,json:async()=>live};}
   pages++; if(page instanceof Error)throw page;
   return {ok:true,status:200,json:async()=>page};
 };
 const ctx={window:{fetch},AbortController,Date,setTimeout,clearTimeout};
 vm.runInNewContext(js,ctx);
 const result = await ctx.window.SlamVisionDirect.resolve({
   cachedUrl:"./slamvision/wwf-live.json?t=123",channel:"52",sourceId:"wwf-90-00"});
 assert.equal(api,expectApi,"Unexpected API call count");
 return {result,api,pages};
}
(async()=>{
 let x=await trial(cached(12*3600000,-3600000,-120000),upstream(),1);
 assert.equal(x.result.channels["52"].id,"wwf-90-00");
 assert.equal(x.result.channels["52"].current.title,"WWF Raw Is War");
 assert.equal(x.result.channels["52"].current.stream_url,"https://archive.org/download/example/show.mp4");
 x=await trial(cached(60000),upstream(),0);
 assert.equal(x.result.channels["52"].current.id,"saved","Fresh Pages data should take priority");
 x=await trial(cached(12*3600000),upstream("wrong-feed"),1).then(()=>null,err=>err);
 assert.ok(x instanceof Error, "Wrong upstream identity must fail");
 x=await trial(cached(12*3600000,-60000,3600000),new Error("network offline"),1);
 assert.equal(x.result.channels["52"].current.id,"saved","Current saved broadcast should survive API outage");
 x=await trial(cached(12*3600000,-3600000,-120000),new Error("network offline"),1)
 .then(()=>null,err=>err);
 assert.ok(x instanceof Error,"Expired saved broadcast must not be represented as live");
 x=await trial(new Error("pages 404"),upstream(),1);
 assert.equal(x.result.channels["52"].current.id,"show-1","Pages outage should use direct API");
 console.log("PASS: 6 direct API fallback scenarios, including channel renumbering and outages");
})().catch(err=>{console.error(err);process.exit(1)});
