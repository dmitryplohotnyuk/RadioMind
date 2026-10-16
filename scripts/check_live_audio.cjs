const fs=require('node:fs'),vm=require('node:vm'),assert=require('node:assert/strict');
const nodes=new Map(),events={},timers=new Map(),sockets=[],contexts=[];
let nextTimer=0,starts=0;
function node(id){if(!nodes.has(id))nodes.set(id,{checked:false,textContent:'',pause(){this.paused=true;},addEventListener(name,fn){this[name]=fn;}});return nodes.get(id);}
class Audio {
  constructor(){this.currentTime=1;this.state='running';this.sources=[];contexts.push(this);}
  async resume(){} async close(){this.state='closed';}
  createBuffer(ch,n,rate){assert.equal(ch,1);assert.equal(rate,16000);const data=new Float32Array(n);return {duration:n/rate,getChannelData:()=>data,data};}
  createBufferSource(){const source={connect(){},disconnect(){},stop(){this.stopped=true;},start(at){this.at=at;}};this.sources.push(source);return source;}
}
class Socket {
  constructor(url){assert.equal(url,'ws://localhost:8765/ws/audio');sockets.push(this);}
  close(){this.closed=true;this.onclose?.();}
}
const context=vm.createContext({document:{getElementById:node},location:{host:'localhost:8765',protocol:'http:'},AudioContext:Audio,WebSocket:Socket,DataView,Math,JSON,Set,Error,
  setTimeout(fn){const id=++nextTimer;timers.set(id,fn);return id;},clearTimeout(id){timers.delete(id);},addEventListener(name,fn){events[name]=fn;}});
require('./i18n_test_support.cjs')(context);
vm.runInContext(fs.readFileSync('frontend/live-audio.js','utf8'),context);
const run=code=>vm.runInContext(code,context);
function audio(ws,n=640){const bytes=new ArrayBuffer(n),view=new DataView(bytes);for(let i=0;i<n;i+=2)view.setInt16(i,16384,true);ws.onmessage({data:bytes});}
(async()=>{
  assert.equal(node('listen-live').checked,false);assert.equal(contexts.length,0);
  context.radioLive.onStart=()=>starts++;
  await run('radioLive.start()');assert.equal(starts,1);assert.equal(node('player').paused,true);
  const first=sockets.at(-1),ctx=contexts.at(-1);first.onopen();
  audio(first);assert.equal(ctx.sources[0].buffer.data[0],.5);assert.equal(ctx.sources[0].at,1.08);
  audio(first);assert.ok(Math.abs(ctx.sources[1].at-1.10)<1e-9);
  first.onmessage({data:JSON.stringify({type:'reset'})});
  audio(first,96000); // Entire 3-second onset, not only its last 500 ms.
  const onset=ctx.sources.at(-1);
  assert.equal(onset.buffer.data.length,48000);assert.equal(onset.buffer.data[0],.5);
  audio(first,3200); // 100 ms continuation follows the onset without flushing it.
  assert.equal(onset.stopped,undefined);
  assert.ok(Math.abs(ctx.sources.at(-1).at-(onset.at+3))<1e-9);
  for(let i=0;i<300;i++)audio(first);
  assert.ok(ctx.sources.at(-1).at+ctx.sources.at(-1).buffer.duration-ctx.currentTime<=4.25);
  assert.ok(ctx.sources.some(s=>s.stopped));
  first.onmessage({data:JSON.stringify({type:'reset'})});assert.equal(ctx.sources.at(-1).stopped,true);
  first.onmessage({data:JSON.stringify({type:'state',state:'digital'})});assert.match(node('live-audio-status').textContent,/после завершения/);
  const beforeSwitch=contexts.length;
  run('radioI18n.setLanguage("en")');
  assert.equal(contexts.length,beforeSwitch);assert.equal(first.closed,undefined);
  assert.equal(node('listen-live').checked,true);assert.equal(ctx.state,'running');
  run('radioI18n.setLanguage("ru")');
  first.close();assert.equal(timers.size,1);assert.match(node('live-audio-status').textContent,/Восстанавливаем/);
  const retry=[...timers.values()][0];timers.clear();retry();assert.equal(sockets.length,2);
  run('radioLive.stop()');assert.equal(timers.size,0);assert.equal(node('listen-live').checked,false);assert.equal(ctx.state,'closed');
  const count=ctx.sources.length;audio(first);assert.equal(ctx.sources.length,count);
  await run('radioLive.start()');node('player').play();assert.equal(node('listen-live').checked,false);
  await run('radioLive.start()');events.pagehide();assert.equal(sockets.at(-1).closed,true);
  // Stop while AudioContext permission/resume is still pending.
  let resume;Audio.prototype.resume=()=>new Promise(resolve=>resume=resolve);
  const pending=run('radioLive.start()'),before=sockets.length;run('radioLive.stop()');resume();await pending;
  assert.equal(sockets.length,before);assert.equal(node('listen-live').checked,false);
  console.log('Live audio: full 3-second pre-roll and continuation, opt-in, PCM rate/level, bounded scheduling, reset, reconnect, archive exclusion and pending-start cancellation pass.');
})().catch(error=>{console.error(error);process.exitCode=1;});
