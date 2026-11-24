#!/usr/bin/env node
/**
 * Baked.live channel playlist bridge.
 * Runs only in a GitHub Actions runner with BAKED_LIVE_PASSWORD secret.
 * A commit to baked-bridge/request.json is the command transport.
 * Only authorized channels/players are allowed. Default operation: audit.
 */
import fs from 'node:fs/promises';
import assert from 'node:assert/strict';

const SITE='https://baked.live';
const USERNAME='buttman-gpt';
const CHANNELS=new Set(['luchatube']);
const PLAYER_ORIGIN='https://buttocks.github.io';
const PLAYER_ROOT='/suplex-baked-player/';
const REQUEST_PATH=process.env.BAKED_BRIDGE_REQUEST || 'baked-bridge/request.json';
const OUTPUT_PATH='baked-bridge/result.json';

function safeUrl(value){
  if(typeof value!=='string' || value.length>600)throw Error('Invalid player URL');
  let url;
  try{url=new URL(value);}catch{throw Error('Player URL must be absolute HTTPS');}
  if(url.origin!==PLAYER_ORIGIN||!url.pathname.startsWith(PLAYER_ROOT)||
     !/^[a-zA-Z0-9/_-]+\.html$/.test(url.pathname.slice(PLAYER_ROOT.length))||
     url.username||url.password||url.hash)throw Error('Player URL is not in the approved GitHub Pages directory');
  return url.href;
}
function validate(raw){
  if(!raw||typeof raw!=='object'||Array.isArray(raw))throw Error('Request must be an object');
  const allowed=['schema','request_id','channel','action','title','src','old_src'];
  for(const key of Object.keys(raw))if(!allowed.includes(key))throw Error('Unknown request key: '+key);
  if(raw.schema!==1||!CHANNELS.has(raw.channel))throw Error('Unsupported schema or unauthorized channel');
  if(!['audit','add_iframe','replace_iframe'].includes(raw.action))throw Error('Unsupported bridge action');
  if(typeof raw.request_id!=='string'||!/^[a-zA-Z0-9_-]{6,80}$/.test(raw.request_id))throw Error('Invalid request_id');
  if(raw.action==='audit'){
    if(raw.src||raw.old_src||raw.title)throw Error('Audit requests cannot contain mutations');
    return {schema:1,request_id:raw.request_id,channel:raw.channel,action:'audit'};
  }
  if(typeof raw.title!=='string'||raw.title.trim().length<4||raw.title.length>100)throw Error('Missing or invalid title');
  const request={schema:1,request_id:raw.request_id,channel:raw.channel,action:raw.action,title:raw.title.trim(),src:safeUrl(raw.src)};
  if(raw.action==='replace_iframe'){
    request.old_src=safeUrl(raw.old_src);
    if(request.old_src===request.src)throw Error('Old and new iframe URLs are identical');
  }else if(raw.old_src)throw Error('Old URL only allowed for replacement');
  return request;
}
function embedHtml(src){
  return '<iframe src="'+src+'" width="1280" height="720" frameborder="0" allow="autoplay; fullscreen; picture-in-picture" allowfullscreen></iframe>';
}
async function writeResult(result){
  await fs.writeFile(OUTPUT_PATH,JSON.stringify(result,null,2)+'\n','utf8');
  console.log('Bridge result: '+result.status+' / '+result.channel+' / '+result.action);
}
async function snapshot(page){
  return page.evaluate(()=>{
    function fromMedia(media){
      if(media?.type!=='cu'||typeof media.id!=='string')return null;
      const text=media.id;
      const match=text.match(/<iframe\b[^>]*\bsrc\s*=\s*["']([^"']+)["']/i);
      if(!match)return null;
      try{
        const element=document.createElement('textarea');
        element.innerHTML=match[1]; // decode HTML entities in src attribute
        return new URL(element.value,location.href).href;
      }catch{return null;}
    }
    const queue=[...document.querySelectorAll('#queue .queue_entry')].map((el,idx)=>{
      const media=window.jQuery?window.jQuery(el).data('media')||{}:{};
      const uid=window.jQuery?window.jQuery(el).data('uid'):null;
      const temp=window.jQuery?window.jQuery(el).data('temp'):null;
      return {index:idx,uid,src:fromMedia(media),type:media.type||null,title:media.title||el.querySelector('.qe_title')?.textContent||'',temp:!!temp};
    });
    const client=window.CLIENT||{};
    const permission=name=>typeof window.hasPermission==='function'&&!!window.hasPermission(name);
    return {connected:!!window.socket?.connected,channel:window.CHANNEL?.name,
      username:client.name,rank:client.rank,loggedIn:!!client.logged_in,playing:window.PL_CURRENT,
      permissions:{add:permission('playlistadd'),custom:permission('playlistaddcustom'),
        permanent:permission('playlistaddnontemp'),move:permission('playlistmove'),remove:permission('playlistdelete')},
      queue};
  });
}
async function waitFor(page,check,message,timeout=20000){
  const start=Date.now();
  while(Date.now()-start<timeout){
    const state=await snapshot(page);
    if(check(state))return state;
    await page.waitForTimeout(350);
  }
  throw Error(message);
}
function exactMatches(state,src){return state.queue.filter(entry=>entry.src===src);}
function mutationAllowed(state,action){
  if(!state.permissions.add||!state.permissions.custom)throw Error('Admin lacks permission to add custom iframes');
  if(action==='replace_iframe'&&(!state.permissions.move||!state.permissions.remove))
    throw Error('Admin lacks permission to move/delete existing entries');
}
async function login(page,password){
  await page.goto(SITE+'/login',{waitUntil:'domcontentloaded',timeout:45000});
  // Baked.live serves a header login form as well as the main login form.
  // Scope all fields and submit to one form to avoid strict-selector collisions.
  const form=page.locator('form[action="/login"]').last();
  const user=form.locator('input[name="name"]');
  const pass=form.locator('input[name="password"]');
  await user.waitFor({state:'visible',timeout:20000});
  await user.fill(USERNAME);
  await pass.fill(password);
  await form.locator('button[type="submit"]').click();
  await page.waitForLoadState('domcontentloaded');
  const body=await page.locator('body').innerText();
  if(/Login Failed|Invalid username\/password/i.test(body))throw Error('Baked.live login failed');
  // The channel's CLIENT state below provides the authoritative login/rank check.
}
async function run(request){
  const password=process.env.BAKED_LIVE_PASSWORD;
  if(!password)throw Error('Missing GitHub Actions secret BAKED_LIVE_PASSWORD; see baked-bridge/README.md');
  const {chromium}=await import('playwright');
  const browser=await chromium.launch({headless:true,args:['--no-sandbox']});
  let page;
  try{
    const context=await browser.newContext({viewport:{width:1380,height:880},acceptDownloads:false});
    page=await context.newPage();
    page.setDefaultTimeout(20000);
    await login(page,password);
    await page.goto(SITE+'/tv/'+request.channel,{waitUntil:'domcontentloaded',timeout:45000});
    const initial=await waitFor(page,state=>state.connected&&state.loggedIn&&
      String(state.username||'').toLowerCase()===USERNAME&&state.channel===request.channel,
      'Could not confirm authenticated account and channel connection',30000);
    if(!Number.isFinite(initial.rank)||initial.rank<3)
      throw Error('buttman-gpt is not an Admin on '+request.channel);
    const before=initial.queue.map(entry=>({index:entry.index,title:entry.title,src:entry.src,temp:entry.temp}));
    console.log('Authenticated '+USERNAME+' as channel Admin; playlist items: '+before.length);
    if(request.action==='audit'){
      return {request_id:request.request_id,channel:request.channel,action:request.action,status:'audited',
        items:before.length,iframes:before.filter(x=>x.src),canAddCustom:initial.permissions.custom,
        canMove:initial.permissions.move,canRemove:initial.permissions.remove};
    }
    mutationAllowed(initial,request.action);
    const already=exactMatches(initial,request.src);
    if(already.length>1)throw Error('Multiple existing copies of target iframe; refusing duplicate actions');
    if(request.action==='add_iframe'&&already.length===1){
      return {request_id:request.request_id,channel:request.channel,action:request.action,status:'already-present',src:request.src};
    }
    let old=null,predecessor=null;
    if(request.action==='replace_iframe'){
      const hits=exactMatches(initial,request.old_src);
      if(hits.length!==1)throw Error('Replacement requires exactly one matching old iframe in playlist');
      old=hits[0];
      if(old.uid===initial.playing)throw Error('Old iframe is currently playing; replacement cancelled');
      predecessor=old.index>0?initial.queue[old.index-1].uid:'prepend';
      if(already.length)throw Error('New iframe already exists elsewhere; refusing ambiguous replacement');
    }
    // Queue as permanent media; never advance live playback.
    await page.evaluate(({markup,title})=>{
      window.socket.emit('queue',{id:markup,title,type:'cu',pos:'end',temp:false});
    },{markup:embedHtml(request.src),title:request.title});
    let after=await waitFor(page,s=>exactMatches(s,request.src).length===1,
      'Baked.live did not confirm new iframe in playlist');
    const added=exactMatches(after,request.src)[0];
    if(added.temp)throw Error('New iframe was only added temporarily; review channel permissions');
    console.log('Verified permanent iframe added: '+request.src);
    if(request.action==='replace_iframe'){
      await page.evaluate(({uid,after})=>window.socket.emit('moveMedia',{from:uid,after}),
        {uid:added.uid,after:predecessor});
      after=await waitFor(page,s=>{
        const now=exactMatches(s,request.src)[0];
        if(!now)return false;
        const wanted=predecessor==='prepend'?0:s.queue.findIndex(x=>x.uid===predecessor)+1;
        return now.index===wanted;
      },'New iframe queued but position could not be verified; old entry left unchanged');
      await page.evaluate(uid=>window.socket.emit('delete',uid),old.uid);
      after=await waitFor(page,s=>!s.queue.some(x=>x.uid===old.uid),
        'Old iframe was not removed; review playlist manually');
      console.log('Old iframe replaced at original playlist position.');
    }
    return {request_id:request.request_id,channel:request.channel,action:request.action,
      status:request.action==='replace_iframe'?'replaced':'added',src:request.src,
      old_src:request.old_src||undefined,items_before:initial.queue.length,items_after:after.queue.length};
  }finally{await browser.close();}
}
function selfTest(){
  const audit=validate({schema:1,request_id:'test_audit_01',channel:'luchatube',action:'audit'});
  assert.equal(audit.action,'audit');
  const url='https://buttocks.github.io/suplex-baked-player/lucha-slamvision.html';
  assert.equal(validate({schema:1,request_id:'test_add_01',channel:'luchatube',
    action:'add_iframe',title:'Lucha',src:url}).src,url);
  for(const candidate of [
    {schema:1,request_id:'test_bad_01',channel:'other',action:'audit'},
    {schema:1,request_id:'test_bad_02',channel:'luchatube',action:'add_iframe',
      title:'Test',src:'https://example.com/attack.html'},
    {schema:1,request_id:'test_bad_03',channel:'luchatube',action:'add_iframe',
      title:'Test',src:'https://buttocks.github.io/suplex-baked-player/../attack.html'}
  ])assert.throws(()=>validate(candidate));
  assert.equal(embedHtml(url).includes('type="cu"'),false);
  console.log('PASS: request validation, channel allowlist, URL allowlist and embed format');
}
if(process.argv.includes('--self-test'))selfTest();
else{
  try{
    const request=validate(JSON.parse(await fs.readFile(REQUEST_PATH,'utf8')));
    const result=await run(request);
    await writeResult(result);
  }catch(error){
    // Never log environment variables, browser cookies, page HTML or login fields.
    console.error('Bridge failed: '+String(error.message||error).slice(0,400));
    process.exitCode=1;
  }
}
