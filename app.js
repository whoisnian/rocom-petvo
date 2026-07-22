const grid=document.getElementById('grid'),q=document.getElementById('q'),
      sub=document.getElementById('sub'),empty=document.getElementById('empty');
const small=matchMedia('(max-width:480px)');
// 只用 m4a/AAC:Chrome、Firefox、Safari/iOS、Android WebView 全部原生支持,免去格式分支
const a=new Audio();
a.preload='none';                        // 每只一个小文件,点了才拉
let cur=null,curMode=0,curRate=1,timer=0;
// 游戏内 -100~100 的 voice 值经 Wwise RTPC "Pet_Vo_Pitch" 实时变调,曲线逐宠手调、
// 三点线性(x=-100/0/100),两端音分即 manifest 的 l/h。Wwise 的 pitch 本身就是重采样
// (变调同时变速),所以关掉浏览器默认的保音调时间伸缩后,playbackRate 即等价实现。
const rateOf=(p,m)=>Math.pow(2,(m<0?p.l:m>0?p.h:0)/1200);
function stop(){clearTimeout(timer);a.pause();
  if(cur){cur.classList.remove('playing','loading');
    cur.querySelectorAll('.pb.on').forEach(b=>b.classList.remove('on'));cur=null}}
function play(p,el,mode){
  mode=mode||0;
  const wasEl=cur,wasMode=curMode;stop();
  document.querySelectorAll('.pet.target').forEach(e=>{if(e!==el)e.classList.remove('target')});
  if(wasEl===el&&wasMode===mode)return;   // 同一只同一档再次点击=停止
  cur=el;curMode=mode;curRate=rateOf(p,mode);
  el.classList.add('playing','loading');
  const b=mode&&el.querySelector('.pb[data-m="'+mode+'"]');if(b)b.classList.add('on');
  // 换 src 后同步 play():整个过程都在 click 的手势栈内,iOS/WebView 均放行。
  // 不再依赖 seek —— QQ 等内置浏览器不转发 Range 时,整轨方案会退回 0 秒。
  a.src='audio/'+p.py+'.m4a';
  // preservesPitch 默认 true(保音调伸缩),必须置 false 才是重采样变调;
  // 前缀写法覆盖 Chrome<109 / 老 Safari。playbackRate 会被 load() 重置为
  // defaultPlaybackRate,故两者都要在换 src 之后设。
  a.preservesPitch=a.mozPreservesPitch=a.webkitPreservesPitch=false;
  a.defaultPlaybackRate=a.playbackRate=curRate;
  const pr=a.play();if(pr&&pr.catch)pr.catch(()=>{});
  timer=setTimeout(stop,((p.d||3)/curRate+1)*1000);   // ended 不触发时的兜底
}
a.addEventListener('playing',()=>{if(!cur)return;cur.classList.remove('loading');
  // 移动端曾出现「play promise 落定前的赋值被丢弃」,这里补一次兜底
  if(Math.abs(a.playbackRate-curRate)>1e-3)a.playbackRate=curRate});
a.addEventListener('ended',stop);
const seen={},vi={};
for(const p of PETS)seen[p.book]=(seen[p.book]||0)+1;
for(const p of PETS)if(seen[p.book]>1)vi[p.py]=(vi[p.book]=(vi[p.book]||0)+1);
function render(list){
  grid.replaceChildren();elMap.clear();empty.hidden=list.length>0;
  const d=small.matches?DS:D,f=document.createDocumentFragment();
  for(const p of list){
    const el=document.createElement('div');el.className='pet';
    el.title=p.name+' · 图鉴 '+p.book+' · '+p.py;
    const x=-(p.i%COLS)*d,y=-Math.floor(p.i/COLS)*d;
    el.innerHTML='<div class="ico" style="background-position:'+x+'px '+y+'px"></div>'+
      '<div class="nm">'+p.name+'</div><div class="id">#'+String(p.book).padStart(3,'0')+
      (vi[p.py]?' <span style="opacity:.7">形态'+vi[p.py]+'</span>':'')+'</div>'+
      '<div class="pbs"><button class="pb" type="button" data-m="-1">粗嗓门</button>'+
      '<button class="pb" type="button" data-m="1">婉转声</button></div>';
    el.onclick=()=>{setHash(p);play(p,el,0)};
    for(const b of el.querySelectorAll('.pb'))
      b.onclick=e=>{e.stopPropagation();setHash(p);play(p,el,+b.dataset.m)};
    elMap.set(p.py,el);f.appendChild(el);
  }
  grid.appendChild(f);
  sub.textContent='点击头像或下方按钮播放 · '+(list.length===PETS.length?'共 '+PETS.length+' 只'
                                     :list.length+' / '+PETS.length);
}
// ---- hash 路由 ----
const elMap=new Map();
const byHash=h=>{h=decodeURIComponent((h||'').replace(/^#/,'')).trim();if(!h)return null;
  const lo=h.toLowerCase();
  return PETS.find(p=>p.py.toLowerCase()===lo)||
         (/^\d+$/.test(h)?PETS.find(p=>p.book===+h):null)||null};
function setHash(p){history.replaceState(null,'','#'+p.py)}
function focusPet(p,doPlay){
  if(q.value){q.value='';filter()}          // 目标可能被搜索过滤掉
  const el=elMap.get(p.py);if(!el)return;
  el.scrollIntoView({block:'center',behavior:'smooth'});
  document.querySelectorAll('.pet.target').forEach(e=>e.classList.remove('target'));
  el.classList.add('target');
  if(doPlay)play(p,el);
}
const gate=document.getElementById('gate');
let pending=null;
function openGate(p){pending=p;gate.hidden=false;gate.classList.remove('out')}
gate.addEventListener('click',()=>{
  const p=pending;pending=null;
  gate.classList.add('out');
  setTimeout(()=>{gate.hidden=true;gate.classList.remove('out')},180);
  if(p)focusPet(p,true);                     // 仍在用户手势栈内,iOS 可正常起播
});
addEventListener('hashchange',()=>{const p=byHash(location.hash);if(p)focusPet(p,true)});

function filter(){
  const s=q.value.trim().toLowerCase();
  render(!s?PETS:PETS.filter(p=>p.name.toLowerCase().includes(s)||p.py.toLowerCase().includes(s)||
    String(p.book)===s||String(p.book).padStart(3,'0')===s||String(p.book).startsWith(s)));
}
q.addEventListener('input',filter);
q.addEventListener('keydown',e=>{if(e.key==='Escape'){q.value='';filter()}});
small.addEventListener('change',filter);   // 断点切换需重算精灵偏移
render(PETS);
const start=byHash(location.hash);
if(start)openGate(start);
