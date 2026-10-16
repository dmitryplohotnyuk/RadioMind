// Network-state regression tests with a DOM stub; no hardware or browser required.
const fs=require('node:fs'), vm=require('node:vm'), assert=require('node:assert/strict');
const elements=new Map(), timers=new Map();
let timerId=0, mode='ok', calls=[];
const status={running:true,record_audio:true,source:'hackrf',error:null,conversation:{state:'SCAN'},resources:{process_cpu_percent:1,rss_bytes:1024,disk_free_bytes:1024},capture:{application_dropped_samples:0}};
function element(){return {value:'',textContent:'',hidden:true,disabled:false,children:[],classList:{toggle(){}},setAttribute(){},replaceChildren(...nodes){this.children=nodes}};}
const document={getElementById(id){if(!elements.has(id))elements.set(id,element());return elements.get(id)},addEventListener(){},querySelector(){return null},querySelectorAll(){return []}};
function untilAbort(signal){return new Promise((resolve,reject)=>{signal.addEventListener('abort',()=>{const error=new Error('Aborted');error.name='AbortError';reject(error)},{once:true})});}
const context=vm.createContext({document,URLSearchParams,AbortController,TypeError,Error,
  setTimeout(fn,ms){const id=++timerId;timers.set(id,{fn,ms});return id},clearTimeout(id){timers.delete(id)},
  fetch:async(path,options)=>{
    calls.push({path,method:options.method});
    if(mode==='offline')throw new TypeError('Failed to fetch');
    if(mode==='hang')return untilAbort(options.signal);
    if(mode==='http')return {ok:false,status:409,json:async()=>({detail:'Сначала остановите приём'})};
    const read=async()=>mode==='body' ? untilAbort(options.signal) : path==='/api/status' ? status : [];
    return {ok:true,json:read,blob:read};
  }});
const source=fs.readFileSync('frontend/app.js','utf8').replace(/refresh\(\);\s*setInterval\(refresh,1000\);\s*$/,'');
require('./i18n_test_support.cjs')(context);
vm.runInContext(source,context);
const run=code=>vm.runInContext(code,context), node=id=>document.getElementById(id);
run('renderArchive=()=>{};renderChannels=()=>{};');
async function deadline(ms){
  // Let response headers resolve before aborting a pending response body.
  for(let i=0;i<8;i++)await Promise.resolve();
  assert.ok(timers.size>0);
  for(const timer of [...timers.values()]){assert.equal(timer.ms,ms);timer.fn();}
}
(async()=>{
  run('rows=[{id:"preserved"}];');node('player').src='blob:playing';node('message').textContent='Важное сообщение';
  mode='offline';await run('refresh()');
  assert.equal(run('busy'),false);assert.equal(run('rows[0].id'),'preserved');
  assert.equal(node('player').src,'blob:playing');assert.equal(node('message').textContent,'Важное сообщение');
  assert.equal(node('connection-message').hidden,false);assert.match(node('connection-message').textContent,/Нет связи/);
  assert.doesNotMatch(node('connection-message').textContent,/Failed to fetch/);assert.equal(node('toggle').disabled,true);
  mode='ok';await run('refresh()');
  assert.equal(node('connection-message').hidden,true);assert.equal(node('toggle').disabled,false);
  assert.equal(node('receiver-title').textContent,'Ищем разговоры');assert.equal(node('message').textContent,'Важное сообщение');
  for(const failure of ['hang','body']){
    mode=failure;const pending=run('refresh()');await deadline(8000);await pending;
    assert.equal(run('busy'),false);assert.equal(node('connection-message').hidden,false);
    assert.equal(timers.size,0);mode='ok';await run('refresh()');assert.equal(node('connection-message').hidden,true);
  }
  mode='body';const audio=run('request("/api/conversations/a/audio?variant=original",undefined,r=>r.blob()).catch(notice)');
  await deadline(30000);await audio;assert.equal(timers.size,0);
  mode='offline';calls=[];await run('command("start")');
  assert.equal(calls.filter(c=>c.method==='POST').length,1);assert.match(node('message').textContent,/Результат действия неизвестен/);
  mode='ok';await run('refresh()');
  assert.equal(calls.filter(c=>c.method==='POST').length,1);assert.match(node('message').textContent,/Результат действия неизвестен/);
  mode='http';await run('api("/api/control",{action:"start"}).catch(notice)');
  assert.equal(node('message').textContent,'Сначала остановите приём');assert.equal(node('connection-message').hidden,true);
  mode='ok';status.running=false;status.error='Hardware failure';await run('refresh()');
  assert.equal(node('message').textContent,'Приём остановлен: Hardware failure');
  mode='offline';await run('refresh()');assert.equal(node('message').textContent,'Приём остановлен: Hardware failure');
  mode='ok';await run('refresh()');assert.equal(node('connection-message').hidden,true);
  assert.equal(node('message').textContent,'Приём остановлен: Hardware failure');assert.equal(timers.size,0);
  status.error=null;status.scan_enabled=false;await run('refresh()');
  assert.equal(node('receiver-title').textContent,'Диапазоны выключены');
  assert.equal(node('toggle').disabled,true);
  await run('command("start")');assert.equal(node('toggle').disabled,true);
  status.scan_enabled=true;await run('refresh()');assert.equal(node('toggle').disabled,false);
  console.log('Connection: poll recovery, fetch/body/audio deadlines, preserved player/archive/errors, HTTP details and no write replay pass.');
})().catch(error=>{console.error(error);process.exitCode=1;});
