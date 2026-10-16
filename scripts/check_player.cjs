// State/playlist regression test with a tiny DOM stub, not browser visual validation.
const fs=require('node:fs'), vm=require('node:vm'), assert=require('node:assert/strict');
const elements=new Map();
function element(){return {value:'',textContent:'',hidden:false,disabled:false,paused:true,checked:true,currentTime:0,duration:3,children:[],classList:{toggle(){}},setAttribute(){},removeAttribute(){},load(){},append(...nodes){this.children.push(...nodes)},replaceChildren(...nodes){this.children=nodes},scrollIntoView(){},pause(){this.paused=true},async play(){this.paused=false},focus(){}};}
const document={getElementById(id){if(!elements.has(id))elements.set(id,element());return elements.get(id)},createElement:element,addEventListener(){},querySelector(){return null},querySelectorAll(){return []}};
const context=vm.createContext({document,URL,URLSearchParams,Blob,Date,Map,Math,JSON,String,Number,Promise,AbortController,setTimeout(fn,ms){const timer=setTimeout(fn,ms);timer.unref();return timer},clearTimeout,setInterval(){},fetch:()=>new Promise(()=>{})});
require('./i18n_test_support.cjs')(context);
vm.runInContext(fs.readFileSync(process.argv[2] || 'frontend/app.js','utf8'),context);
(async()=>{
  assert.equal(vm.runInContext('receptionLabel({snr_db:24.4})',context),'Приём при захвате: +24 дБ над шумом');
  for(const value of ['0','-0.1','-3']) assert.match(vm.runInContext(`receptionLabel({snr_db:${value}})`,context),value==='-3' ? /-3 дБ/ : /: 0 дБ/);
  for(const value of ['undefined','null','NaN','Infinity','"24"']) assert.equal(vm.runInContext(`receptionLabel({snr_db:${value}})`,context),'Приём при захвате: нет данных');
  for(const grouped of [true,false]) assert.match(vm.runInContext(`JSON.stringify(recordingCard({id:'level',snr_db:24.4,start_utc:'2026-10-15T12:00:00Z',frequency_hz:154400000},${grouped}))`,context),/Приём при захвате: \+24 дБ над шумом/);
  assert.match(vm.runInContext('attemptDiagnostic({diagnostic_reason:"rf_disappeared"})',context),/исчез/);
  assert.match(vm.runInContext('attemptDiagnostic({signal_evidence:{observed_ms:1000,rf_present_fraction:0},acquisition:{correction_hz:-6250}})',context),/-6,25 кГц.*0%/);
  assert.equal(vm.runInContext('attemptDiagnostic({})',context),'');
  // Mixed channels, days, active capture and prior listening: summary and navigation
  // must reflect conversations, not accidentally combine nearby frequencies.
  vm.runInContext(`
    rows=[
      {id:'a',frequency_hz:154400000,start_utc:'2026-10-14T12:00:00Z',duration_seconds:10,playable:true,status:'ready',listened:false},
      {id:'b',frequency_hz:154400000,start_utc:'2026-10-15T12:00:00Z',duration_seconds:20,playable:true,status:'ready',listened:true},
      {id:'c',frequency_hz:421325000,start_utc:'2026-10-15T13:00:00Z',duration_seconds:30,playable:true,status:'ready',listened:false},
      {id:'d',frequency_hz:421325000,start_utc:'2026-10-15T14:00:00Z',duration_seconds:4,playable:false,status:'recording'},
      {id:'e',frequency_hz:154406250,start_utc:'2026-10-13T12:00:00Z',duration_seconds:5,playable:true,status:'ready',listened:false}
    ];
    renderArchive();
  `,context);
  assert.equal(document.getElementById('group').value,'frequency');
  assert.equal(vm.runInContext('frequencyGroups().length',context),3);
  assert.equal(vm.runInContext('frequencyGroups()[0].frequency',context),421325000);
  assert.equal(vm.runInContext('frequencyGroups()[0].unlistened',context),1);
  assert.equal(vm.runInContext('frequencyGroups()[0].seconds',context),30);
  assert.equal(document.getElementById('recordings').children.length,3);
  assert.equal(document.getElementById('recordings').children[0].children[2].hidden,true);
  vm.runInContext(`archivePreferences.sort='frequency'; archiveSignature=''; renderArchive();`,context);
  assert.equal(vm.runInContext('frequencyGroups()[0].frequency',context),154400000);
  const group=document.getElementById('recordings').children[0];
  group.children[0].children[0].children[0].onclick();
  assert.equal(group.children[2].hidden,false);
  vm.runInContext(`rows[0].duration_seconds=11; renderArchive();`,context);
  assert.equal(document.getElementById('recordings').children[0].children[2].hidden,false);
  assert.equal(vm.runInContext('frequencyPlaylist(154400000).map(r=>r.id).join(",")',context),'a,b');
  assert.equal(vm.runInContext('frequencyPlaylist(421325000).map(r=>r.id).join(",")',context),'c');
  vm.runInContext(`hasMore=true; renderArchive();`,context);
  assert.equal(document.getElementById('load-more').hidden,false);
  assert.match(document.getElementById('archive-scope').textContent,/загруженные/);
  vm.runInContext(`$('group').value='day'; renderArchive();`,context);
  assert.equal(document.getElementById('frequency-tools').hidden,true);
  assert.equal(vm.runInContext('typeof recordingLabel',context),'undefined');
  const cardText=vm.runInContext(`JSON.stringify(recordingCard(rows[0],true))`,context);
  assert.doesNotMatch(cardText,/Есть речь|Нет речи|Неразборчиво|recording-marker|status-chip/);
  assert.match(vm.runInContext('JSON.stringify(frequencyMenu(145000000,{manual:0}))',context),/Добавить в чёрный список/);
  assert.match(vm.runInContext('JSON.stringify(frequencyMenu(145000000,{manual:1}))',context),/Убрать из чёрного списка/);
  assert.equal(vm.runInContext('isBlacklisted({manual:"0"})',context),false);
  await vm.runInContext(`(async()=>{
    busy=false; renderArchive=()=>{};
    request=async(path,body,read)=>read({blob:async()=>new Blob(['test'])});
    api=async(path,flags)=>{const row=rows.find(r=>path.includes(r.id));if(row)Object.assign(row,flags);return flags;};
    refresh=async()=>{rows=rows.filter(r=>!r.listened);};
    rows=['a','b','c'].map(id=>({id,playable:true,status:'ready',duration_seconds:3,frequency_hz:154400000,start_utc:'2026-10-14T12:00:00Z'}));
    await playRecording(rows[0]);
    await $('player').onended();
    await Promise.resolve();await Promise.resolve();await Promise.resolve();
  })()`,context);
  assert.equal(vm.runInContext('currentId',context),'b');
  assert.equal(vm.runInContext('rows.length',context),2);
  await vm.runInContext(`(async()=>{ await playRecording(selectedRow,true,'cleaned',1.25); $('player').onloadedmetadata(); })()`,context);
  assert.equal(vm.runInContext('currentVariant',context),'cleaned');
  assert.equal(document.getElementById('player').currentTime,1.25);
  assert.equal(vm.runInContext('playQueue.length',context),3);
  assert.equal(vm.runInContext('typeof openTranscript',context),'undefined');
  await vm.runInContext(`(async()=>{ await playRecording(selectedRow,true,'original',0); $('player').onloadedmetadata(); })()`,context);
  assert.equal(document.getElementById('player').currentTime,0);
  await vm.runInContext(`(async()=>{
    rows=[
      {id:'channel-old',playable:true,status:'ready',duration_seconds:3,frequency_hz:154400000,start_utc:'2026-10-14T12:00:00Z'},
      {id:'other',playable:true,status:'ready',duration_seconds:3,frequency_hz:421325000,start_utc:'2026-10-14T12:01:00Z'},
      {id:'channel-new',playable:true,status:'ready',duration_seconds:3,frequency_hz:154400000,start_utc:'2026-10-14T12:02:00Z'}
    ];
    $('group').value='frequency';
    await playRecording(rows[0]);
    await $('player').onended();
    await Promise.resolve();await Promise.resolve();await Promise.resolve();
  })()`,context);
  assert.equal(vm.runInContext('currentId',context),'channel-new');
  assert.equal(vm.runInContext('playQueue.length',context),2);
  assert.match(document.getElementById('player-queue').textContent,/154.400/);
  await vm.runInContext(`$('play-all').onclick();`,context);
  assert.equal(vm.runInContext('playQueue.length',context),2);
  assert.equal(vm.runInContext('playQueue.some(r=>r.id==="other")',context),true);
  vm.runInContext(`forgetDeleted([currentId]);`,context);
  assert.equal(vm.runInContext('currentId',context),null);
  assert.equal(document.getElementById('player-bar').hidden,true);
  assert.equal(vm.runInContext('selectedRow',context),null);
  console.log('Archive: frequency summaries, exact Hz grouping, sorting, expansion persistence, pagination scope and isolated channel queue pass.');
  console.log('Player: stable filtered queue, version position, no transcription UI and seek-to-zero pass.');
})().catch(error=>{console.error(error);process.exitCode=1;});
