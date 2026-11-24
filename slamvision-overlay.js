/* Shared fade-on-idle behavior for existing SlamVision / Baked TV embeds.
   Visual-only: never touches playback, schedules, stream sources or volume. */
(()=>{
'use strict';
const video=document.getElementById('video');
const controls=document.getElementById('controls');
const guide=document.getElementById('guide');
const status=document.getElementById('status');
if(!video||!controls||!guide||!status)return;

const FIRST_FADE=5500,REVEAL_FADE=3200;
let timer=null,usingKeyboard=false,hoveringControls=false;
const active=()=>!video.paused&&!video.ended&&status.hidden&&guide.hidden;
function hideLater(ms=REVEAL_FADE){
  clearTimeout(timer);
  if(!active())return;
  timer=setTimeout(()=>{
    if(!active()||hoveringControls)return;
    if(usingKeyboard&&controls.contains(document.activeElement))return;
    document.body.classList.add('sv-overlay-idle');
  },ms);
}
function reveal(ms=REVEAL_FADE){
  document.body.classList.remove('sv-overlay-idle');
  hideLater(ms);
}
const top=document.getElementById('sv-hover-top');
if(top){
  top.addEventListener('pointerenter',()=>{usingKeyboard=false;reveal()});
  top.addEventListener('pointerleave',()=>hideLater(1200));
}
controls.addEventListener('pointerenter',()=>{hoveringControls=true;usingKeyboard=false;reveal()});
controls.addEventListener('pointerleave',()=>{hoveringControls=false;hideLater(1200)});
document.addEventListener('pointermove',()=>{usingKeyboard=false;reveal()},{passive:true});
document.addEventListener('pointerdown',()=>{usingKeyboard=false;reveal()},{passive:true});
document.addEventListener('touchstart',()=>{usingKeyboard=false;reveal()},{passive:true});
document.addEventListener('keydown',()=>{usingKeyboard=true;reveal()});
document.addEventListener('focusin',()=>reveal());

video.addEventListener('playing',()=>{setTimeout(()=>reveal(FIRST_FADE),50)});
video.addEventListener('pause',()=>reveal());
video.addEventListener('error',()=>reveal());
new MutationObserver(()=>reveal(status.hidden?FIRST_FADE:REVEAL_FADE))
  .observe(status,{attributes:true,attributeFilter:['hidden']});
new MutationObserver(()=>reveal())
  .observe(guide,{attributes:true,attributeFilter:['hidden']});

reveal();
})();