// Catalog and state preservation checks; browser layout is verified separately.
const fs=require('node:fs'),vm=require('node:vm'),assert=require('node:assert/strict');
const elements=new Map(),storage=new Map();
class Element {
  constructor(tag='div'){this.tagName=tag;this.attrs={};this.children=[];this.value='';this.hidden=false;this.paused=true;this.disabled=false;this.checked=true;this.classList={toggle(){}};}
  set textContent(value){this.copy=String(value);this.children=[];}
  get textContent(){return (this.copy||'')+this.children.map(n=>n.textContent).join('');}
  setAttribute(k,v){this.attrs[k]=String(v);}
  getAttribute(k){return this.attrs[k]??null;}
  removeAttribute(k){delete this.attrs[k];}
  append(...nodes){this.children.push(...nodes);}
  replaceChildren(...nodes){this.copy='';this.children=nodes;}
  focus(){document.activeElement=this;}
  pause(){this.paused=true;}
  async play(){this.paused=false;}
  load(){}
  addEventListener(){}
}
function all(){const found=new Set();function visit(n){if(found.has(n))return;found.add(n);n.children.forEach(visit);}elements.forEach(visit);return [...found];}
const document={documentElement:{},getElementById(id){if(!elements.has(id))elements.set(id,new Element());return elements.get(id);},createElement:tag=>new Element(tag),addEventListener(){},
  querySelectorAll(selector){const attr=selector.match(/^\[([^\]]+)\]$/);if(attr)return all().filter(n=>Object.hasOwn(n.attrs,attr[1]));return all().filter(n=>n.open&&n.className?.includes('recording-actions'));},
  querySelector(selector){return this.querySelectorAll(selector)[0]||null;}};
const context=vm.createContext({document,Date,Intl,URL,URLSearchParams,Blob,AbortController,
  localStorage:{getItem:k=>storage.get(k),setItem:(k,v)=>storage.set(k,v)},fetch:()=>new Promise(()=>{}),
  setTimeout(){return 1;},clearTimeout(){},setInterval(){}});
require('./i18n_test_support.cjs')(context);
const run=s=>vm.runInContext(s,context),node=id=>document.getElementById(id);
const catalog=context.radioMessages;
const placeholders=s=>[...s.matchAll(/\{\d+\}/g)].map(m=>m[0]).sort();
for(const [key,entry] of Object.entries(catalog)){
  for(const lang of ['en','uk']){assert.ok(entry[lang]?.trim(),`${lang}: ${key}`);assert.deepEqual(placeholders(entry[lang]),placeholders(key),`${lang}: ${key}`);}
  assert.doesNotMatch(entry.en,/[А-Яа-яЁёІіЇїЄєҐґ]/,key);
}
const html=fs.readFileSync('frontend/index.html','utf8');
for(const match of html.matchAll(/data-i18n(?:-aria-label|-placeholder|-title)?="([^"]+)"/g))assert.ok(catalog[match[1].replaceAll('&amp;','&').replaceAll('&quot;','"')],match[1]);
for(const file of ['app','live-audio']) {
  const source=fs.readFileSync(`frontend/${file}.js`,'utf8');
  for(const match of source.matchAll(/\bt\("((?:[^"\\]|\\.)*)"/g))assert.ok(catalog[JSON.parse('"'+match[1]+'"')],match[1]);
  new vm.Script(source);
}
vm.runInContext(fs.readFileSync('frontend/app.js','utf8'),context);
assert.equal(document.documentElement.lang,'ru');
run(`rows=[{id:'sample',title:'Ищем разговоры',frequency_hz:154400000,start_utc:'2026-10-15T12:00:00Z',duration_seconds:12,playable:true,status:'ready'}];
  archivePreferences.open[154400000]=true; renderArchive();addScanRange({start_hz:140000000,end_hz:170000000});dirtySettings();
  selectedRow=rows[0]; currentId='sample'; playQueue=rows.slice();queueFrequency=154400000;
  $('player').src='blob:preserved';$('player').currentTime=4.5;$('player').paused=false;
  setText($('player-queue'),queueLabel);setText($('player-info'),()=>localDate(selectedRow.start_utc));
  const testMenu=frequencyMenu(154400000,{title:'Custom'});$('channels').append(testMenu);testMenu.open=true;
  editMenuTitle(testMenu,'Unsaved title','Название частоты',()=>{});`);
const range=node('scan-ranges').children[0],rangeInput=range.children[0].children[1];
const rangeSwitch=range.children[2].children[0];
assert.equal(rangeSwitch.checked,true);
rangeSwitch.checked=false;rangeSwitch.onchange();
rangeInput.value='141.125';
const menu=node('channels').children[0],form=menu.children[1].children[0],draft=form.children[0].children[1];
run('dismissActionMenus({closest:()=>true})');assert.equal(menu.open,true);
draft.value='Keep this draft';
for(const lang of ['en','uk','ru','en']){
  context.radioI18n.setLanguage(lang);
  assert.equal(document.documentElement.lang,lang);
  assert.equal(run('receptionLabel({snr_db:24})'),context.radioI18n.t('Приём при захвате: {0} дБ над шумом','+24'));
  assert.equal(rangeInput.value,'141.125');assert.equal(range.children[0].children[1],rangeInput);
  assert.equal(rangeSwitch.checked,false);
  assert.equal(range.children[2].children[1].textContent,context.radioI18n.t('Выключен'));
  assert.equal(rangeSwitch.getAttribute('aria-label'),context.radioI18n.t('Сканировать диапазон'));
  assert.equal(draft.value,'Keep this draft');assert.equal(form.children[0].children[1],draft);
  assert.equal(run('settingsDirty'),true);assert.equal(node('player').src,'blob:preserved');
  assert.equal(node('player').paused,false);assert.equal(node('player').currentTime,4.5);
  assert.equal(run('playQueue.length'),1);assert.equal(run('currentId'),'sample');
  assert.equal(run('rows[0].title'),'Ищем разговоры');
  assert.equal(form.children[0].children[0].textContent,context.radioI18n.t('Название частоты'));
}
assert.match(node('player-info').textContent,/October/);
assert.match(node('player-queue').textContent,/MHz.*oldest first/);
assert.equal(storage.get('radiomind.language.v1'),'en');
assert.equal(context.radioI18n.error('Диапазоны не должны пересекаться'),'Ranges must not overlap');
assert.equal(context.radioI18n.error('native unknown: -1000'),'native unknown: -1000');
assert.equal(context.radioI18n.t('missing key'),'missing key');
assert.equal(context.radioI18n.t('Найдено устройств: {0}',1234),'Devices found: 1,234');
context.radioI18n.setLanguage('invalid');assert.equal(document.documentElement.lang,'en');
// A new document restores the preference; denied storage falls back to Russian.
vm.runInContext(fs.readFileSync('frontend/i18n.js','utf8'),context);assert.equal(context.radioI18n.language,'en');
context.localStorage={getItem(){throw Error('denied');},setItem(){throw Error('denied');}};
vm.runInContext(fs.readFileSync('frontend/i18n.js','utf8'),context);assert.equal(context.radioI18n.language,'ru');
context.radioI18n.setLanguage('uk');assert.equal(context.radioI18n.language,'uk');
console.log(`Localization: ${Object.keys(catalog).length} complete catalogs, placeholders/static keys, three locales, dates/counts, persistence/fallback, unchanged drafts/player/queue and owner titles pass.`);

context.radioI18n.setLanguage('en');
assert.equal(run('attemptDiagnostic({diagnostic_reason:"frame_errors_observed",sync_candidates:["NXDN48"],invalid_counts:{dPMR:3}})'), '');
assert.match(run('attemptDiagnostic({diagnostic_reason:"frame_errors_observed",sync_candidates:["DMR"],invalid_counts:{DMR:2,dPMR:3}})'), /Frame errors: DMR/);
assert.match(run('attemptDiagnostic({frame_summary:{voice_burst:2,idle:3,pi_unresolved:1}})'), /DMR voice packets: 2.*DMR service packets: 3.*privacy header unresolved/);
console.log('Digital diagnostics: protocol-scoped errors and packet summaries pass.');
