/**
 * Strictly read-only emote image URL health checker.
 * Treat only confirmed 404/410 or confirmed HTTP-200 non-image HTML as broken;
 * rate limits, 403, DNS failures and transient server errors are NOT deletable.
 */
import fs from 'node:fs/promises';
const FILE='baked-bridge/emote-url-audit.json';
const CONCURRENCY=14;
const TIMEOUT=7500;

function normalize(raw){
  if(typeof raw!=='string')return null;
  try{
    const u=new URL(raw.trim());
    if(!['http:','https:'].includes(u.protocol)||!u.hostname||u.username||u.password)return null;
    return u.href;
  }catch{return null;}
}
async function probe(req,url){
  const result={url,status:'unknown',first:null,verify:null,reason:''};
  async function check(method){
    const opts={timeout:TIMEOUT,maxRedirects:4,failOnStatusCode:false};
    if(method==='GET')opts.headers={Range:'bytes=0-0'};
    const response=method==='HEAD'?await req.head(url,opts):await req.get(url,opts);
    const status=response.status();
    const mime=String(response.headers()['content-type']||'').split(';')[0].toLowerCase();
    await response.dispose();
    return {status,mime};
  }
  try{
    const first=await check('HEAD');result.first=first;
    if(first.status>=200&&first.status<300&&first.mime.startsWith('image/')){
      result.status='working';return result;
    }
    if([403,429].includes(first.status)||first.status>=500){
      result.reason='access-restricted-or-transient';return result;
    }
    const second=await check('GET');result.verify=second;
    if(second.status>=200&&second.status<300&&second.mime.startsWith('image/')){
      result.status='working';return result;
    }
    if(([404,410].includes(first.status)&&[404,410].includes(second.status))){
      result.status='dead';result.reason='confirmed-http-404-or-410';return result;
    }
    if(first.status>=200&&first.status<300&&second.status>=200&&second.status<300&&
      /^(text\/html|application\/xhtml\+xml)$/.test(first.mime)&&
      /^(text\/html|application\/xhtml\+xml)$/.test(second.mime)){
      result.status='dead';result.reason='confirmed-html-instead-of-image';return result;
    }
    result.reason='ambiguous-response';return result;
  }catch(e){
    result.reason='request-failed-or-timed-out';return result;
  }
}
export async function auditEmoteUrls({page,request,initial}){
  if(initial.rank<3)throw Error('Need Admin to audit emotes');
  const emotes=await page.evaluate(()=>{
    const e=window.CHANNEL?.emotes||[];
    return e.map(x=>({name:String(x.name||''),image:String(x.image||'')}));
  });
  if(emotes.length<1000)throw Error('Emote list not loaded fully; refusing audit');
  const unique=new Map();
  for(const emote of emotes){
    const normalized=normalize(emote.image);
    const key=normalized??String(emote.image);
    if(!unique.has(key))unique.set(key,{url:normalized,raw:emote.image,names:[]});
    unique.get(key).names.push(emote.name);
  }
  const urls=[...unique.values()];
  const start=request.offset??0, end=Math.min(start+(request.limit??250),urls.length);
  const tasks=urls.slice(start,end);
  const tested=new Array(tasks.length);
  let next=0,done=0;
  const req=page.context().request;
  async function worker(){
    for(;;){
      const i=next++;if(i>=tasks.length)return;
      const item=tasks[i];
      tested[i]=item.url?await probe(req,item.url):
        {url:item.raw,status:'dead',reason:'invalid-image-url'};
      tested[i].names=item.names;
      tested[i].index=start+i;
      done++;
      if(done%100===0)console.log('Emote checks '+done+'/'+tasks.length+
        ' (no changes)');
    }
  }
  await Promise.all(Array.from({length:Math.min(CONCURRENCY,tasks.length)},()=>worker()));
  const count=status=>tested.filter(x=>x.status===status).length;
  const report={schema:1,action:'audit_emotes',channel:request.channel,
    username:initial.username,checkedAt:new Date().toISOString(),
    totalEmotes:emotes.length,totalUniqueUrls:urls.length,
    offset:start,limit:tasks.length,results:tested,
    statusCounts:{working:count('working'),dead:count('dead'),unknown:count('unknown')},
    noChangesMade:true};
  await fs.writeFile(FILE,JSON.stringify(report,null,2)+'\n');
  return {request_id:request.request_id,channel:request.channel,action:request.action,
    status:'emotes-audited',checked:report.limit,totalEmotes:emotes.length,
    uniqueUrls:urls.length,start,counts:report.statusCounts,
    confirmedDead:tested.filter(x=>x.status==='dead').map(x=>({names:x.names,url:x.url||x.raw,reason:x.reason})),
    noChangesMade:true};
}
