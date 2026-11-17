// Test shared browser-only player routes and URL manifest without network.
"use strict";
const assert=require("node:assert/strict");
const fs=require("node:fs");
const vm=require("node:vm");
const records=JSON.parse(fs.readFileSync("research/slamvision-by-tube-2026-11-17.json","utf8")).channels;
const helper=fs.readFileSync("slamvision-direct-fallback.js","utf8");
const html=fs.readFileSync("slamvision-feed.html","utf8");
const newFeeds=records.filter(x=>x.player_type==="shared");
const legacy=records.filter(x=>x.player_type==="legacy");
assert.equal(records.length,116);
assert.equal(newFeeds.length,92);
assert.equal(legacy.length,24);
assert.equal(new Set(records.map(x=>x.id)).size,116);
assert.equal(new Set(records.map(x=>x.embed_url)).size,116);
assert.equal(new Set(records.map(x=>x.tube)).size,17);
for(const item of records) {
  assert(item.embed_html.includes('src="'+item.embed_url+'"'));
  assert(item.embed_html.startsWith("<iframe "));
  assert(item.embed_html.endsWith("</iframe>"));
  if(item.player_type==="shared") {
    const u=new URL(item.embed_url);
    assert.equal(u.hostname,"buttocks.github.io");
    assert.equal(u.pathname,"/suplex-baked-player/slamvision-feed.html");
    assert.equal(u.searchParams.get("id"),item.id);
    assert(item.id.match(/^[a-z0-9][a-z0-9-]{0,63}$/));
  } else {
    const u=new URL(item.embed_url);
    const path=u.pathname.replace("/suplex-baked-player/","");
    assert(fs.existsSync(path),"Missing legacy page: "+path);
  }
}
const oldPages=fs.readdirSync(".").filter(x=>x.endsWith("-slamvision.html"));
assert.equal(oldPages.length,34,"Legacy page count changed");
const tagged=html.match(/<script>([\s\S]*?)<\/script>/);
assert(tagged);
new vm.Script(tagged[1],{filename:"generic-inline.js"});
new vm.Script(helper,{filename:"direct-fallback.js"});
const now=Date.now();
const ts=n=>new Date(now+n).toISOString();
const upstream=id=>({
 channel:{id,number:Math.floor(Math.random()*1000)+1,name:"Test "+id},
 current:{start:ts(-40000),end:ts(3500000),program:{id:"p1",title:"Live wrestling test",stream_url:"https://archive.org/download/example/example.mp4"}},
 up_next:[]
});
async function check(id,body,shouldFail=false) {
 let reqs=[];
 const ctx={window:{fetch:async url=>{reqs.push(String(url));return {ok:true,status:200,json:async()=>body}}},AbortController,Date,setTimeout,clearTimeout,Map};
 vm.runInNewContext(helper,ctx);
 try {
   const result=await ctx.window.SlamVisionDirect.resolve({channel:id,sourceId:id,cachedUrl:null});
   assert.equal(shouldFail,false,"Unexpected success");
   assert.equal(result.channels[id].id,id);
   assert.equal(result.channels[id].current.title,"Live wrestling test");
 } catch(e) {assert(shouldFail, String(e))}
 assert.equal(reqs.length,1,"No cached Pages request should be attempted");
 assert(reqs[0].includes("/api/channels/"+encodeURIComponent(id)+"/now"));
}
(async()=>{
 for(const id of ["njpw-g1climax","year-1985","star","wcw-mn","tjpw-tv","619","aew-tv"]){
  await check(id,upstream(id));
 }
 await check("njpw-g1climax",upstream("wrong-feed"),true);
 console.log("PASS: 116 distinct embed URLs; 34 legacy pages untouched; 92 stable IDs; 8 live-only fallback routing scenarios");
})().catch(e=>{console.error(e);process.exit(1)});
