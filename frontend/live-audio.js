"use strict";
// Opt-in PCM monitoring. Browser lag never feeds back into capture or the archive.
(() => {
  const i18n=globalThis.radioI18n, t=i18n.t, setText=i18n.text;
  const toggle=document.getElementById("listen-live"), label=document.getElementById("live-audio-status");
  const player=document.getElementById("player");
  let enabled=false, context=null, socket=null, retry=null, generation=0, nextTime=0;
  const sources=new Set();
  function flush() {
    for(const source of sources) { try { source.stop(); } catch {} source.disconnect(); }
    sources.clear(); nextTime=0;
  }
  function stop() {
    enabled=false; generation++; toggle.checked=false; clearTimeout(retry); retry=null;
    const old=socket; socket=null; if(old) old.close();
    flush(); const oldContext=context; context=null;
    if(oldContext) oldContext.close().catch(()=>{});
    setText(label, ()=>(t("Звук выключен")));
  }
  function schedule(data) {
    if(!context || context.state!=="running" || !data.byteLength || data.byteLength%2) return;
    const input=new DataView(data), count=data.byteLength/2;
    if(count>64000) return; // Bounded 4 s server burst includes accepted pre-roll.
    // Initial pre-roll is legitimate queued audio, not a stalled browser. Check
    // projected duration to keep later overload bounded without trimming onset.
    if(Math.max(0,nextTime-context.currentTime)+count/16000>4.25) flush();
    const buffer=context.createBuffer(1,count,16000), output=buffer.getChannelData(0);
    for(let i=0;i<count;i++) output[i]=input.getInt16(i*2,true)/32768;
    const source=context.createBufferSource(); source.buffer=buffer; source.connect(context.destination);
    source.onended=()=>{sources.delete(source);source.disconnect();}; sources.add(source);
    const at=Math.max(context.currentTime+0.08,nextTime);
    source.start(at); nextTime=at+buffer.duration;
  }
  function connect(token) {
    if(!enabled || token!==generation) return;
    const ws=new WebSocket(`${location.protocol==="https:" ? "wss":"ws"}://${location.host}/ws/audio`);
    socket=ws; ws.binaryType="arraybuffer";
    ws.onopen=()=>{if(socket===ws) setText(label, ()=>(t("Ждём разговор")));};
    ws.onmessage=event=>{
      if(!enabled || socket!==ws || token!==generation) return;
      if(typeof event.data!=="string") { schedule(event.data); return; }
      const message=JSON.parse(event.data);
      if(message.type==="reset") flush();
      if(message.type==="state") setText(label, ()=>(message.state==="digital" ? t("Цифровая запись — после завершения"):message.state==="listening" ? t("Слушаем разговор"):t("Ждём разговор")));
    };
    ws.onerror=()=>ws.close();
    ws.onclose=()=>{
      if(socket!==ws || !enabled || token!==generation) return;
      socket=null; flush(); setText(label, ()=>(t("Восстанавливаем звук…")));
      retry=setTimeout(()=>connect(token),1000);
    };
  }
  async function start() {
    stop(); enabled=true; toggle.checked=true; const token=generation;
    try {
      const Audio=globalThis.AudioContext || globalThis.webkitAudioContext;
      if(!Audio) throw new Error("Web Audio unavailable");
      const audio=new Audio(); context=audio;
      globalThis.radioLive.onStart?.(); player.pause();
      setText(label, ()=>(t("Подключаем звук…")));
      await audio.resume();
      if(!enabled || generation!==token) return;
      connect(token);
    } catch {
      if(generation!==token) return;
      stop(); setText(label, ()=>(t("Не удалось включить звук. Попробуйте ещё раз.")));
    }
  }
  globalThis.radioLive={stop,start};
  toggle.onchange=()=>toggle.checked ? start():stop();
  player.addEventListener("play",stop);
  globalThis.addEventListener("pagehide",stop);
  stop();
})();
