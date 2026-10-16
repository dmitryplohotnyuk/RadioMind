"use strict";
const i18n=globalThis.radioI18n, t=i18n.t, setText=i18n.text;
const $ = id => document.getElementById(id);
let busy = false, running = false, scanEnabled = true, tabName = "archive";
let rows = [], channels = [], pageCount = 1, currentId = null, audioUrl = null, playRequest = 0;
let currentRevision = null, currentVariant = "original", selectedRow = null, playQueue = [];
let lastSequence = -1, lastWindow = "", archiveSignature = "", channelSignature = "";
let hasMore = false, queueFrequency = null;
const queueLabel = () => queueFrequency===null ? t("Все записи · от новых к старым") : mhz(queueFrequency)+t(" МГц · от старых к новым");
let deletePlan = null, deleteRequest = 0;
if(globalThis.radioLive) globalThis.radioLive.onStart=()=>{playRequest++; $("player").pause();};
let settingsLoaded=false, settingsDirty=false, settingsLoading=false, settingsRevision=0;
let archivePreferences = {group:"frequency", sort:"recent", open:{}};
try {
  const saved = JSON.parse(localStorage.getItem("radiomind.archive.v1"));
  if (saved && ["frequency","day"].includes(saved.group)) archivePreferences.group = saved.group;
  if (saved && ["recent","frequency","unlistened"].includes(saved.sort)) archivePreferences.sort = saved.sort;
  if (saved?.open && typeof saved.open === "object") {
    for (const [key,value] of Object.entries(saved.open)) if (/^\d+$/.test(key) && typeof value === "boolean") archivePreferences.open[key] = value;
  }
} catch { /* Storage may be disabled; the archive still works. */ }
function saveArchivePreferences() {
  try { localStorage.setItem("radiomind.archive.v1",JSON.stringify(archivePreferences)); } catch { /* Optional local preference. */ }
}
const mhz = value => (value / 1e6).toFixed(4).replace(/0$/, "");
const decimal = (value,digits=0) => i18n.number(value,{minimumFractionDigits:digits,maximumFractionDigits:digits});
const duration = value => `${Math.floor((value || 0) / 60)}:${String(Math.floor((value || 0) % 60)).padStart(2,"0")}`;
const localDate = value => new Date(value).toLocaleDateString(i18n.locale, {day:"numeric",month:"long",year:"numeric"});
const localTime = value => new Date(value).toLocaleTimeString(i18n.locale, {hour:"2-digit",minute:"2-digit",second:"2-digit"});
function el(tag, text, className) {
  const node=document.createElement(tag);
  if(text!==undefined) {
    // Labels may later receive inputs: translate a separate span, preserving drafts.
    if(tag==="label") { const copy=document.createElement("span");setText(copy,text);node.append(copy); }
    else setText(node,text);
  }
  if(className)node.className=className;return node;
}
const actionMenus = new WeakMap();
function closeActionMenu(menu, restoreFocus=false) {
  menu.open=false;
  const state=actionMenus.get(menu);
  if(state) { state.actions.replaceChildren(...state.buttons); if(restoreFocus) state.summary.focus(); i18n.apply(); }
}
function dismissActionMenus(target=null) {
  if(target?.closest?.(".language-picker")) return;
  for(const menu of document.querySelectorAll(".recording-actions[open]")) {
    if(!target || !menu.contains(target)) closeActionMenu(menu);
  }
}
document.addEventListener("pointerdown",event=>dismissActionMenus(event.target));
document.addEventListener("focusin",event=>dismissActionMenus(event.target));
document.addEventListener("keydown",event=>{
  if(event.key!=="Escape") return;
  const menu=document.querySelector(".recording-actions[open]");
  if(menu) { event.preventDefault(); closeActionMenu(menu,true); }
});
function setupActionMenu(menu,summary,actions,buttons) {
  actionMenus.set(menu,{summary,actions,buttons});
  summary.onclick=event=>{
    event.preventDefault();
    if(menu.open) closeActionMenu(menu);
    else { dismissActionMenus(menu); menu.open=true; }
  };
  actions.replaceChildren(...buttons); menu.append(summary,actions);
}
function editMenuTitle(menu,value,label,saveTitle) {
  const {actions}=actionMenus.get(menu);
  const form=el("form",undefined,"rename-form"), field=el("label",()=>t(label)), input=el("input"), controls=el("div",undefined,"rename-controls");
  const save=el("button",()=>(t("Сохранить")),"primary"), cancel=el("button",()=>(t("Отмена")));
  input.value=value || ""; input.maxLength=100;
  i18n.attribute(input,"placeholder",()=>t(label));i18n.attribute(input,"aria-label",()=>t(label));
  save.type="submit"; cancel.type="button";
  cancel.onclick=()=>closeActionMenu(menu,true);
  field.append(input); controls.append(cancel,save); form.append(field,controls);
  form.onsubmit=async event=>{
    event.preventDefault(); if(save.disabled) return;
    save.disabled=true;
    try { await saveTitle(input.value); closeActionMenu(menu,true); archiveSignature=channelSignature=""; await refresh(); }
    catch(error) { notice(error); save.disabled=false; }
  };
  actions.replaceChildren(form); input.focus();
}
class ConnectionError extends Error {
  constructor(write) {
    super(write ? t("Связь прервалась. Результат действия неизвестен — после восстановления проверьте, применилось ли оно.") : t("Нет связи с сервером. Повторяем подключение…"));
    this.write=write;
    this.translationKey=write ? "Связь прервалась. Результат действия неизвестен — после восстановления проверьте, применилось ли оно." : "Нет связи с сервером. Повторяем подключение…";
  }
}
function connectionLost() {
  $("connection-message").hidden=false;
  setText($("connection-message"), ()=>(t("Нет связи с сервером. Повторяем подключение…")));
  setText($("receiver-title"), ()=>(t("Состояние приёмника неизвестно")));
  setText($("receiver-subtitle"), ()=>(t("Ждём ответ сервера. На экране последние полученные данные.")));
  for(const id of ["toggle","watch","sweep"]) $(id).disabled=true;
}
function notice(error) {
  if(error instanceof ConnectionError) { connectionLost(); if(!error.write) return; }
  setText($("message"), ()=>i18n.error(error));
}
async function request(path, body, read=response=>response) {
  const controller=new AbortController();
  const timeout=setTimeout(()=>controller.abort(),body || path.includes("/audio?") ? 30000:8000);
  try {
    const response = await fetch(path, {method: body ? "POST" : "GET", signal:controller.signal, cache:"no-store", headers:body ? {"Content-Type":"application/json"} : {}, ...(body ? {body:JSON.stringify(body)} : {})});
    if (!response.ok) {
      const payload=await response.json().catch(()=>({}));
      const error=new Error(typeof payload.detail==="string" ? payload.detail : t("Не удалось выполнить действие ({0})",response.status));
      error.detail=payload.detail; error.httpStatus=response.status;throw error;
    }
    // Keep the deadline through JSON/audio body consumption, not only headers.
    return await read(response);
  } catch(error) {
    if(error instanceof TypeError || error.name==="AbortError" || controller.signal.aborted) {
      connectionLost(); throw new ConnectionError(Boolean(body));
    }
    throw error;
  } finally { clearTimeout(timeout); }
}
async function api(path, body) { return request(path,body,response=>response.json()); }
for (const name of ["archive","channels","settings","diagnostics"]) $("tab-"+name).onclick=() => { tabName=name; for (const other of ["archive","channels","settings","diagnostics"]) { $(other+"-view").hidden=other!==name; $("tab-"+other).classList.toggle("active",other===name); $("tab-"+other).setAttribute("aria-current",other===name ? "page":"false"); } if(name==="settings" && !settingsLoaded) loadReceiverSettings(); refresh(); };
for (const action of ["watch","sweep"]) $(action).onclick=() => command(action);
$("toggle").onclick=() => command(running ? "stop":"start");
async function command(action) { $("toggle").disabled=true; try { await api("/api/control",{action}); await refresh(); } catch(error) { notice(error); } finally { $("toggle").disabled=!$("connection-message").hidden || (!running && !scanEnabled); } }
function query() {
  const params=new URLSearchParams({limit:"200",q:$("search").value.trim(),view:$("view").value});
  if ($("date").value) { const begin=new Date($("date").value+"T00:00:00"), end=new Date(begin); end.setDate(end.getDate()+1); params.set("since",begin.toISOString()); params.set("until",end.toISOString()); }
  return params;
}
let searchTimer;
for (const id of ["search","date","view"]) $(id).oninput=() => { clearTimeout(searchTimer); pageCount=1; searchTimer=setTimeout(refresh,200); };
$("group").value=archivePreferences.group;
$("frequency-sort").value=archivePreferences.sort;
$("group").onchange=() => { archivePreferences.group=$("group").value; saveArchivePreferences(); archiveSignature=""; renderArchive(); };
$("frequency-sort").onchange=() => { archivePreferences.sort=$("frequency-sort").value; saveArchivePreferences(); archiveSignature=""; renderArchive(); };
for (const [id,open] of [["expand-groups",true],["collapse-groups",false]]) $(id).onclick=()=>{
  for (const row of rows) archivePreferences.open[row.frequency_hz]=open;
  saveArchivePreferences(); archiveSignature=""; renderArchive();
};
$("load-more").onclick=() => { pageCount++; refresh(); };
function playlist() { return rows.filter(row=>row.playable); }
async function askDeletion(selection) {
  const requestId=++deleteRequest;
  try {
    const plan=await api("/api/archive/delete-preview",selection);
    if(requestId!==deleteRequest) return;
    deletePlan=plan;
    setText($("delete-title"), ()=>(selection.frequency_hz ? t("Удалить группу {0} МГц?", mhz(selection.frequency_hz)) : t("Удалить запись?")));
    setText($("delete-description"), ()=>(t("Будет удалено разговоров: {0}, включая все их части, оригиналы и очищенные копии. ", plan.conversations)+(selection.frequency_hz ? t("Это все записи частоты за все даты, включая скрытые фильтрами. ") : "")+t("Восстановить их нельзя. Настройки приёма частоты сохранятся.")));
    setText($("delete-error"), ""); $("delete-confirm").disabled=false;
    $("delete-dialog").showModal();
  } catch(error) { notice(error); }
}
function forgetDeleted(ids) {
  ++playRequest; // In-flight audio responses may belong to a now-deleted file.
  rows=rows.filter(row=>!ids.includes(row.id));
  playQueue=playQueue.filter(row=>!ids.includes(row.id));
  if(ids.includes(currentId)) {
    $("player").pause(); $("player").removeAttribute("src"); $("player").load();
    if(audioUrl) URL.revokeObjectURL(audioUrl);
    audioUrl=null; currentId=null; currentRevision=null; selectedRow=null;
    $("player-bar").hidden=true;
  }
  archiveSignature=""; renderArchive();
}
$("delete-cancel").onclick=()=>$("delete-dialog").close();
$("delete-dialog").onclose=()=>{ deletePlan=null; ++deleteRequest; };
$("delete-form").onsubmit=async event=>{
  event.preventDefault(); if(!deletePlan) return;
  $("delete-confirm").disabled=true;
  try {
    const result=await api("/api/archive/delete",{token:deletePlan.token});
    forgetDeleted(result.deleted_sessions);
    $("delete-dialog").close();
    setText($("message"), ()=>(result.pending_file_cleanup ? t("Записи убраны из архива. Некоторые файлы заняты; очистка диска повторится при следующем запуске.") : t("Записи удалены. Настройки приёма сохранены.")));
    await refresh();
  } catch(error) { setText($("delete-error"), ()=>(i18n.error(error)+t(" Закройте окно и повторите удаление."))); }
};
function frequencyGroups(source=rows) {
  const groups=new Map();
  for (const row of source) {
    if (!groups.has(row.frequency_hz)) groups.set(row.frequency_hz,{frequency:row.frequency_hz,items:[],unlistened:0,seconds:0,latest:row.start_utc});
    const group=groups.get(row.frequency_hz);
    group.items.push(row);
    if (row.playable) group.seconds+=row.duration_seconds || 0;
    if (!row.listened && row.status!=="recording") group.unlistened++;
    if (new Date(row.start_utc)>new Date(group.latest)) group.latest=row.start_utc;
  }
  for (const group of groups.values()) group.items.sort((a,b)=>new Date(b.start_utc)-new Date(a.start_utc) || a.id.localeCompare(b.id));
  return [...groups.values()].sort((a,b)=>{
    if (archivePreferences.sort==="frequency") return a.frequency-b.frequency;
    if (archivePreferences.sort==="unlistened" && a.unlistened!==b.unlistened) return b.unlistened-a.unlistened;
    return new Date(b.latest)-new Date(a.latest) || a.frequency-b.frequency;
  });
}
function frequencyPlaylist(frequency) {
  return playlist().filter(row=>row.frequency_hz===frequency).sort((a,b)=>new Date(a.start_utc)-new Date(b.start_utc) || a.id.localeCompare(b.id));
}
function startFrequency(frequency) {
  const list=frequencyPlaylist(frequency);
  if (!list.length) return;
  playQueue=list; queueFrequency=frequency;
  playRecording(list[0],true).catch(notice);
}
function receptionLabel(row) {
  if(typeof row.snr_db!=="number" || !Number.isFinite(row.snr_db)) return t("Приём при захвате: нет данных");
  const value=Math.round(row.snr_db) || 0;
  return t("Приём при захвате: {0} дБ над шумом", (value>0 ? "+":"")+decimal(value,0));
}
function renderArchive() {
  // Do not replace a rename form while its owner is typing during live polling.
  if (document.querySelector("#recordings .recording-actions[open]")) return;
  const signature=JSON.stringify([rows,channels.filter(c=>c.title || c.favorite || c.manual),currentId,$("player").paused,$("group").value,archivePreferences,hasMore]);
  if (signature===archiveSignature) return; archiveSignature=signature;
  const total=rows.filter(r=>r.playable).reduce((sum,r)=>sum+r.duration_seconds,0);
  setText($("count"), rows.length);
  const frequencyView=$("group").value==="frequency", groups=frequencyGroups();
  setText($("archive-summary"), ()=>(rows.length ? t("Частот: {0} · записей: {1} · {2} для прослушивания", groups.length, rows.length, duration(total)) : t("Готовые записи появятся здесь")));
  $("frequency-tools").hidden=!frequencyView || !rows.length;
  setText($("archive-scope"), ()=>(hasMore ? t("Показаны загруженные записи с учётом фильтров. Загрузите ещё, чтобы увидеть более ранние записи и частоты.") : t("С учётом выбранных фильтров · новые записи появляются автоматически")));
  $("play-all").disabled=!playlist().length;
  $("load-more").hidden=!hasMore;
  if (!rows.length) { const empty=el("div",undefined,"empty card"); empty.append(el("div","▥","empty-icon"),el("h2",()=>($("search").value || $("date").value || $("view").value!=="all" ? t("Записей не найдено"):t("Архив пока пуст"))),el("p",()=>($("search").value || $("date").value || $("view").value!=="all" ? t("Попробуйте другую дату, фильтр или очистите поиск."):t("Когда приёмник найдёт речь, здесь появится запись. Её можно будет прослушать и перейти к следующей.")))); $("recordings").replaceChildren(empty); return; }
  const nodes=[];
  if (frequencyView) {
    for (const group of groups) {
      const section=el("section",undefined,"frequency-group card"), heading=el("div",undefined,"frequency-heading");
      const title=el("h2"), toggle=el("button",undefined,"frequency-toggle"), copy=el("span",undefined,"frequency-copy"), chevron=el("span","›","frequency-chevron");
      chevron.setAttribute("aria-hidden","true");
      const profile=channels.find(c=>c.frequency_hz===group.frequency) || {title:group.items[0].frequency_title,favorite:group.items[0].frequency_favorite,manual:group.items[0].frequency_excluded};
      copy.append(el("strong",()=>(profile.title || mhz(group.frequency)+t(" МГц"))));
      if(profile.title) copy.append(el("span",()=>(mhz(group.frequency)+t(" МГц")),"frequency-number"));
      copy.append(el("span",()=>(t("Записей: {0} · {1} для прослушивания", group.items.length, duration(group.seconds))),"frequency-stats"));
      toggle.append(chevron,copy);
      const content=el("div",undefined,"frequency-content"); content.id="frequency-"+group.frequency;
      toggle.setAttribute("aria-controls",content.id);
      toggle.id="toggle-frequency-"+group.frequency;
      i18n.attribute(toggle, "aria-label", ()=>(t("Записи частоты {0} МГц", mhz(group.frequency))));
      const setOpen=open=>{ content.hidden=!open; toggle.setAttribute("aria-expanded",String(open)); section.classList.toggle("expanded",open); };
      setOpen(archivePreferences.open[group.frequency]===true);
      toggle.onclick=()=>{ const open=content.hidden; archivePreferences.open[group.frequency]=open; saveArchivePreferences(); setOpen(open); };
      title.append(toggle);
      const badges=el("div",undefined,"frequency-badges");
      if(isBlacklisted(profile)) badges.append(el("span",()=>(t("В чёрном списке")),"blacklist-badge"));
      badges.append(el("span",()=>(group.unlistened ? t("Не прослушано: {0}", group.unlistened) : t("Всё прослушано")),group.unlistened ? "unheard-badge":"heard-badge"));
      if (group.items.some(row=>row.status==="recording")) badges.append(el("span",()=>(t("● Записывается")),"capture-badge"));
      if (group.items.some(row=>row.id===currentId)) badges.append(el("span",()=>($("player").paused ? t("В плеере"):t("Сейчас слушаете")),"playing-badge"));
      const play=el("button",()=>(t("▶ Слушать частоту")),"frequency-play"); play.disabled=!group.items.some(row=>row.playable);
      i18n.attribute(play, "aria-label", ()=>(t("Слушать частоту {0} МГц", mhz(group.frequency))));
      i18n.attribute(play,"title",()=>t("Загруженные записи этой частоты от старых к новым, с учётом фильтров"));
      play.onclick=()=>startFrequency(group.frequency);
      heading.append(title,badges,frequencyFavorite(group.frequency,profile),play,frequencyMenu(group.frequency,profile));
      const last=el("p",()=>(t("Последняя запись: {0} · {1}", localDate(group.latest), localTime(group.latest))),"frequency-last");
      appendDays(content,group.items,true);
      section.append(heading,last,content); nodes.push(section);
    }
  } else {
    const list=el("div"); appendDays(list,rows,false); nodes.push(list);
  }
  const focusedGroup=document.activeElement?.id;
  $("recordings").replaceChildren(...nodes);
  if (focusedGroup?.startsWith("toggle-frequency-")) $(focusedGroup)?.focus({preventScroll:true});
}
function appendDays(container,items,frequencyView) {
  const days=new Map();
  for (const row of items) { const day=localDate(row.start_utc); if(!days.has(day)) days.set(day,[]); days.get(day).push(row); }
  for (const [day,records] of days) {
    container.append(el("h3",`${day} · ${records.length}`,"group-title"));
    for (const row of records) container.append(recordingCard(row,frequencyView));
  }
}
function recordingCard(row,frequencyView) {
      const card=el("article",undefined,"recording card"+(row.id===currentId ? " playing":""));
      const play=el("button",row.id===currentId && !$("player").paused ? "❚❚":"▶","play-button"); play.disabled=!row.playable; i18n.attribute(play, "aria-label", ()=>(t("Слушать {0} МГц, {1}", mhz(row.frequency_hz), localTime(row.start_utc)))); play.onclick=() => { if (row.id===currentId && !$("player").paused) $("player").pause(); else playRecording(row).catch(notice); };
      const copy=el("div",undefined,"recording-copy"); copy.append(el("strong",()=>(row.title || (frequencyView ? localTime(row.start_utc) : mhz(row.frequency_hz)+t(" МГц"))),"recording-title"),el("span",()=>(`${frequencyView ? (row.title ? localTime(row.start_utc)+" · " : "")+t("Запись эфира") : localTime(row.start_utc)+" · "+mhz(row.frequency_hz)+t(" МГц")}${row.source==="mock" ? t(" · Тестовая запись"):""}`),"recording-meta"));
      const reception=el("span",()=>receptionLabel(row),"recording-reception");
      i18n.attribute(reception,"title",()=>t("Превышение спектрального пика над оценкой фонового шума в момент захвата частоты. Больше — сигнал заметнее на фоне шума. Это не среднее за разговор и не оценка разборчивости речи."));
      copy.append(reception);
      if (!row.listened && row.status!=="recording") copy.append(el("span",()=>(t("Не прослушано")),"listening-note"));
      const favorite=el("button",row.favorite ? "★":"☆","favorite quiet"); i18n.attribute(favorite, "aria-label", ()=>(row.favorite ? t("Убрать из избранного"):t("В избранное"))); favorite.setAttribute("aria-pressed",String(Boolean(row.favorite))); favorite.onclick=()=>reviewFlags(row,{favorite:!row.favorite});
      if(row.discontinuity) copy.append(el("span",()=>(t("Запись с разрывом")),"recording-meta"));
      const menu=el("details",undefined,"recording-actions"), summary=el("summary","•••"); i18n.attribute(summary, "aria-label", ()=>(t("Действия с записью"))); const actions=el("div",undefined,"action-menu");
      const rename=el("button",()=>(t("Назвать запись"))); rename.onclick=()=>editMenuTitle(menu,row.title,"Название записи",title=>api(`/api/recordings/${row.id}/review`,{title}));
      const heard=el("button",()=>(row.listened ? t("Отметить непрослушанным"):t("Отметить прослушанным"))); heard.disabled=row.status==="recording"; heard.onclick=()=>{closeActionMenu(menu);reviewFlags(row,{listened:!row.listened});};
      const remove=el("button",()=>(t("Удалить запись")),"danger-text"); remove.disabled=row.status==="recording";
      remove.onclick=()=>{closeActionMenu(menu); askDeletion({session_id:row.id});};
      setupActionMenu(menu,summary,actions,[rename,heard,remove]);
      card.append(play,copy,favorite,el("span",()=>(row.status==="recording" ? t("Идёт запись"):duration(row.duration_seconds)),"recording-time"),menu); return card;
}
async function playRecording(row, keepQueue=false, variant="original", position=null) {
  if (!row.playable) return;
  globalThis.radioLive?.stop();
  if (!keepQueue) {
    const grouped=$("group").value==="frequency";
    playQueue=grouped ? frequencyPlaylist(row.frequency_hz) : playlist().slice();
    queueFrequency=grouped ? row.frequency_hz:null;
  }
  setText($("player-queue"), queueLabel);
  const revision = `${row.duration_seconds}:${row.part_count || 1}:${row.status}`;
  if (currentId===row.id && audioUrl && currentRevision===revision && currentVariant===variant) { if(position!==null) $("player").currentTime=position; await $("player").play(); return; }
  const requestId=++playRequest;
  const blob=await request(`/api/conversations/${row.id}/audio?variant=${variant}`,undefined,response=>response.blob());
  if (requestId!==playRequest) return;
  $("player").pause(); if (audioUrl) URL.revokeObjectURL(audioUrl);
  audioUrl=URL.createObjectURL(blob); currentId=row.id; currentRevision=revision; currentVariant=variant; selectedRow=row; $("player").src=audioUrl;
  setText($("player-title"), ()=>(row.title || mhz(row.frequency_hz)+t(" МГц")));
  setText($("player-info"), ()=>(`${localDate(row.start_utc)} · ${localTime(row.start_utc)}`));
  $("player-bar").hidden=false; updateAudioControls(); renderArchive();
  if(position!==null) $("player").onloadedmetadata=()=>{ $("player").currentTime=Math.min(position,$("player").duration); $("player").onloadedmetadata=null; };
  else $("player").onloadedmetadata=null;
  await $("player").play();
}
function step(direction) { const list=playQueue,index=list.findIndex(r=>r.id===currentId),row=list[index+direction]; if (row) playRecording(row,true).catch(notice); }
$("play-all").onclick=()=>{ playQueue=playlist().slice(); queueFrequency=null; const first=playQueue[0]; if (first) playRecording(first,true).catch(notice); };
$("previous").onclick=()=>step(-1); $("next").onclick=()=>step(1);
$("player").onplay=renderArchive; $("player").onpause=renderArchive;
$("player").onended=async()=>{
  const finished=selectedRow, revision=currentRevision;
  if(finished && finished.status!=="recording") await reviewFlags(finished,{listened:true});
  if(currentId===finished?.id && currentRevision===revision && $("autoplay").checked) step(1);
};
async function reviewFlags(row,flags) { try { await api(`/api/recordings/${row.id}/review`,flags); Object.assign(row,flags); await refresh(); } catch(error) { notice(error); } }
function updateAudioControls() {
  if(!selectedRow) return;
  const state=selectedRow.clean_status;
  $("clean-audio").hidden=state==="ready";
  $("clean-audio").disabled=state==="processing" || selectedRow.status==="recording";
  setText($("clean-audio"), ()=>(state==="processing" ? t("Очищается…"):state==="failed" ? t("Повторить очистку"):state==="outdated" ? t("Улучшить очистку"):t("Очистить звук")));
  $("audio-variant").disabled=state!=="ready" && state!=="outdated";
  $("audio-variant").value=currentVariant;
}
$("clean-audio").onclick=async()=>{if(!selectedRow)return; const row=selectedRow; try { const result=await api(`/api/conversations/${row.id}/clean`,{}); row.clean_status=result.status; updateAudioControls(); } catch(error) { notice(error); }};
$("audio-variant").onchange=()=>{if(selectedRow) playRecording(selectedRow,true,$("audio-variant").value,$("player").currentTime).catch(notice);};
async function changeChannel(frequency_hz,action) { try { const changed=await api("/api/channels",{frequency_hz,action}); frequency_hz=changed.frequency_hz; setText($("message"), ()=>(action==="exclude" ? t("{0} МГц исключена из записи", mhz(frequency_hz)):t("Настройка частоты сохранена"))); await refresh(); } catch(error) { notice(error); } }
async function saveFrequency(frequency_hz,change) {
  const result=await api("/api/frequency-profile",{frequency_hz,...change});
  const old=channels.find(c=>c.frequency_hz===frequency_hz);
  if(old) Object.assign(old,result); else channels.push(result);
  archiveSignature=channelSignature="";
  await refresh();
}
function frequencyFavorite(frequency,profile) {
  const button=el("button",profile.favorite ? "★":"☆","favorite quiet frequency-favorite");
  i18n.attribute(button, "aria-label", ()=>(t("{0} {1} МГц", profile.favorite ? t("Убрать частоту из избранного"):t("В избранные частоты"), mhz(frequency))));
  button.setAttribute("aria-pressed",String(Boolean(profile.favorite)));
  button.onclick=()=>saveFrequency(frequency,{favorite:!profile.favorite}).catch(notice);
  return button;
}
function frequencyMenu(frequency,profile) {
  const menu=el("details",undefined,"recording-actions frequency-actions"), summary=el("summary","•••"), actions=el("div",undefined,"action-menu");
  i18n.attribute(summary, "aria-label", ()=>(t("Действия с частотой {0} МГц", mhz(frequency))));
  const rename=el("button",()=>(t("Назвать частоту")));
  rename.onclick=()=>editMenuTitle(menu,profile.title,"Название частоты",title=>saveFrequency(frequency,{title}));
  const blacklist=el("button",()=>(isBlacklisted(profile) ? t("Убрать из чёрного списка"):t("Добавить в чёрный список")));
  blacklist.onclick=()=>{closeActionMenu(menu); changeChannel(frequency,isBlacklisted(profile) ? "restore":"exclude");};
  const priority=el("button",()=>(profile.priority ? t("Убрать приоритет сканирования"):t("Чаще проверять эту частоту")));
  priority.onclick=()=>{closeActionMenu(menu);changeChannel(frequency,profile.priority ? "normal":"priority");};
  const remove=el("button",()=>(t("Удалить записи частоты")),"danger-text");
  remove.onclick=()=>{closeActionMenu(menu);askDeletion({frequency_hz:frequency});};
  setupActionMenu(menu,summary,actions,[rename,blacklist,priority,remove]); return menu;
}
function isBlacklisted(profile) { return profile.manual===true || profile.manual===1 || profile.manual==="1"; }
$("channel-form").onsubmit=event=>{event.preventDefault(); changeChannel(Math.round(Number($("channel-frequency").value)*1e6),$("channel-action").value);};
function renderChannels() {
  if(document.querySelector("#channels .recording-actions[open]")) return;
  const now=Date.now()/1000, visible=channels.filter(c=>c.title || c.favorite || c.manual || c.priority || c.expires>now).sort((a,b)=>Number(b.favorite)-Number(a.favorite) || a.frequency_hz-b.frequency_hz);
  const signature=JSON.stringify(visible.map(c=>[c.frequency_hz,c.title,c.favorite,c.manual,c.priority,Math.ceil((c.expires-now)/60)]));
  if (signature===channelSignature) return; channelSignature=signature;
  if (!visible.length) { $("channels").replaceChildren(el("div",()=>(t("Здесь появятся важные частоты и исключения.")),"empty card")); return; }
  $("channels").replaceChildren(...visible.map(c=>{const row=el("div",undefined,"channel card"),copy=el("div",undefined,"channel-copy"); copy.append(el("strong",()=>(c.title || mhz(c.frequency_hz)+t(" МГц"))),el("p",()=>((c.title ? mhz(c.frequency_hz)+t(" МГц · "):"")+(c.manual ? t("В чёрном списке"):c.priority ? t("Приоритет сканирования"):c.expires>now ? t("Повторная проверка через {0} мин", Math.max(1,Math.ceil((c.expires-now)/60))):t("Участвует в поиске в выбранных диапазонах"))))); row.append(copy,frequencyFavorite(c.frequency_hz,c),frequencyMenu(c.frequency_hz,c)); return row;}));
}
function dirtySettings() { settingsRevision++;settingsDirty=true; $("save-settings").disabled=false; setText($("settings-message"), ()=>(t("Есть несохранённые изменения"))); }
function addScanRange(range={}) {
  if($("scan-ranges").children.length>=16) return;
  const row=el("div",undefined,"scan-range"), startLabel=el("label",()=>(t("От, МГц"))),endLabel=el("label",()=>(t("До, МГц"))),start=el("input"),end=el("input"),remove=el("button",()=>(t("Убрать")),"quiet");
  for(const [input,label,value] of [[start,startLabel,range.start_hz],[end,endLabel,range.end_hz]]) {
    input.type="number"; input.step="0.000001"; input.min="1"; input.max="6000"; input.required=true;
    input.value=value ? String(value/1e6):""; input.oninput=dirtySettings; label.append(input);
  }
  start.className="range-start"; end.className="range-end";
  const switchLabel=el("label",undefined,"range-switch"), enabled=el("input",undefined,"range-enabled"), state=el("span");
  enabled.type="checkbox"; enabled.setAttribute("role","switch"); enabled.checked=range.enabled!==false;
  i18n.attribute(enabled,"aria-label",()=>t("Сканировать диапазон"));
  const updateState=()=>{row.classList.toggle("range-off",!enabled.checked);setText(state,()=>enabled.checked ? t("Включён"):t("Выключен"));};
  enabled.onchange=()=>{updateState();dirtySettings();}; updateState(); switchLabel.append(enabled,state);
  remove.type="button"; i18n.attribute(remove, "aria-label", ()=>(t("Убрать диапазон"))); remove.onclick=()=>{row.remove();dirtySettings();};
  row.append(startLabel,endLabel,switchLabel,remove); $("scan-ranges").append(row);
}
async function refreshDevices() {
  const selected=$("device-choice").value, wasDisabled=$("device-choice").disabled; $("refresh-devices").disabled=true;$("device-choice").disabled=true;
  try {
    const result=await api("/api/devices"), automatic=el("option",()=>(t("Найти автоматически"))); automatic.value="";
    const options=[automatic];
    for(const device of result.devices) {
      if(!device.serial) continue;
      const option=el("option",()=>i18n.deviceLabel(device)); option.value=device.serial; options.push(option);
    }
    if(selected && !result.devices.some(d=>d.serial===selected)) { const missing=el("option",()=>(t("HackRF {0} · сейчас не найден", selected)));missing.value=selected;options.push(missing); }
    $("device-choice").replaceChildren(...options); $("device-choice").value=selected;
    setText($("device-message"), ()=>(i18n.error(result.message) || t("Найдено устройств: {0}", result.devices.length)));
  } catch(error) { setText($("device-message"), ()=>i18n.error(error)); }
  finally { $("refresh-devices").disabled=false;$("device-choice").disabled=wasDisabled; }
}
async function loadReceiverSettings() {
  if(settingsLoading) return; settingsLoading=true;
  try {
    const result=await api("/api/settings");
    const selected=el("option",()=>(result.desired.device_serial ? `HackRF ${result.desired.device_serial}`:t("Найти автоматически"))); selected.value=result.desired.device_serial || "";
    $("device-choice").replaceChildren(selected); $("device-choice").value=selected.value;
    $("receive-gain").value=result.desired.receive_gain || "normal";
    $("scan-ranges").replaceChildren(); result.desired.ranges.forEach(addScanRange);
    $("device-choice").disabled=result.source!=="hackrf";
    settingsLoaded=true;settingsDirty=false;$("save-settings").disabled=true;
    setText($("settings-message"), ()=>(result.pending ? t("Сохранено. Применим после текущего разговора."):t("Настройки применены")));
    await refreshDevices();
  }catch(error){setText($("settings-message"), ()=>i18n.error(error));}
  finally{settingsLoading=false;}
}
$("add-range").onclick=()=>{addScanRange();dirtySettings();};
$("device-choice").onchange=dirtySettings;
$("receive-gain").onchange=dirtySettings;
$("refresh-devices").onclick=refreshDevices;
$("reload-settings").onclick=loadReceiverSettings;
$("receiver-settings-form").onsubmit=async event=>{
  event.preventDefault(); $("save-settings").disabled=true;const revision=settingsRevision;
  try {
    const ranges=Array.from($("scan-ranges").children,row=>({start_hz:Math.round(Number(row.querySelector(".range-start").value)*1e6),end_hz:Math.round(Number(row.querySelector(".range-end").value)*1e6),enabled:row.querySelector(".range-enabled").checked}));
    if(!ranges.length) throw new Error(t("Добавьте хотя бы один диапазон"));
    const result=await api("/api/settings",{device_serial:$("device-choice").value || null,receive_gain:$("receive-gain").value,ranges});
    if(revision!==settingsRevision) { setText($("settings-message"), ()=>(t("Предыдущие изменения сохранены. Новые изменения ещё не сохранены."))); return; }
    settingsDirty=false;
    setText($("settings-message"), ()=>(result.pending ? t("Сохранено. Применим после текущего разговора."):t("Настройки применены")));
  }catch(error){setText($("settings-message"), ()=>i18n.error(error));$("save-settings").disabled=false;}
};
function draw(frame) {
  if (frame.sequence===lastSequence) return; lastSequence=frame.sequence;
  const c=$("psd"),ctx=c.getContext("2d"), w=c.width,h=c.height,low=frame.noise_floor_dbfs_hz-10,high=low+65, values=frame.psd_dbfs_hz;
  ctx.clearRect(0,0,w,h); ctx.strokeStyle="#263b40";
  for (let i=0;i<5;i++) { ctx.beginPath();ctx.moveTo(0,i*h/4);ctx.lineTo(w,i*h/4);ctx.stroke(); }
  ctx.strokeStyle="#7bdfbb";ctx.beginPath(); values.forEach((value,i)=>{const x=i*w/(values.length-1),y=Math.max(0,Math.min(h,(high-value)/(high-low)*h)); if(i)ctx.lineTo(x,y);else ctx.moveTo(x,y);});ctx.stroke();
  const wf=$("waterfall"),wc=wf.getContext("2d");if(frame.window!==lastWindow){wc.clearRect(0,0,wf.width,wf.height);lastWindow=frame.window;}
  wc.drawImage(wf,0,0,wf.width,wf.height-3,0,3,wf.width,wf.height-3);
  for(let x=0;x<wf.width;x++){const level=Math.max(0,Math.min(1,(values[Math.min(values.length-1,Math.floor(x/wf.width*values.length))]-low)/55));wc.fillStyle=`hsl(${235-level*190} 80% ${8+level*57}%)`;wc.fillRect(x,0,1,3);}
  setText($("frequency"), ()=>(mhz(frame.center_hz)+t(" МГц")));setText($("frame-time"), ()=>(localTime(frame.timestamp)));setText($("start-hz"), mhz(frame.start_hz));setText($("end-hz"), mhz(frame.end_hz));setText($("band-label"), frame.window);
}
async function refresh() {
  if (busy) return; busy=true; const params=query(), key=params.toString();
  try {
    const [status,pages,channelRows]=await Promise.all([api("/api/status"),Promise.all(Array.from({length:pageCount},(_,i)=>api(`/api/conversations?${key}&offset=${i*200}`))),api("/api/channels")]);
    $("connection-message").hidden=true; setText($("connection-message"), "");
    for(const id of ["toggle","watch","sweep"]) $(id).disabled=false;
    running=status.running;
    scanEnabled=status.scan_enabled!==false;
    $("toggle").disabled=!running && !scanEnabled;
    if(settingsLoaded && !settingsDirty && !settingsLoading) setText($("settings-message"), ()=>(status.settings_pending ? t("Сохранено. Применим после текущего разговора."):t("Настройки применены")));
    const state=status.conversation?.state || "SCAN", frequency=status.conversation?.frequency_hz;
    setText($("receiver-title"), ()=>(!running ? (!scanEnabled ? t("Диапазоны выключены"):t("Приём остановлен")):!status.record_audio ? t("Обзор эфира · запись выключена"):({SCAN:t("Ищем разговоры"),VERIFY:t("Проверяем сигнал"),RECORD:t("Записываем разговор"),HANG:t("Ждём ответ")})[state]));
    setText($("receiver-subtitle"), ()=>(!scanEnabled && !running ? t("Включите диапазон в настройках, чтобы начать приём."):frequency ? t("{0} МГц{1}", mhz(frequency), state==="RECORD" || state==="HANG" ? " · "+duration(status.conversation.recorded_seconds):""):t("Сканируем выбранные диапазоны · записи сохраняются на этом ПК")));
    $("live-symbol").classList.toggle("is-recording",state==="RECORD" || state==="HANG");
    setText($("toggle"), ()=>(running ? t("Остановить приём"):t("Начать приём")));
    if(status.reconnecting) setText($("message"), ()=>(t("Восстанавливаем связь с приёмником…")));
    else if(status.error) setText($("message"), ()=>(t("Приём остановлен: ")+i18n.error(status.error)));
    else if(status.metadata?.full && status.metadata.full_policy==="drop_new") setText($("message"), ()=>(t("Журнал диагностики заполнен. Запись разговоров продолжается; старые данные сохранены.")));
    else if(status.source==="mock") setText($("message"), ()=>(t("Тестовый источник: это не эфир с HackRF.")));
    else if ($("message").textContent.startsWith(t("Восстанавливаем связь")) || $("message").textContent.startsWith(t("Приём остановлен:"))) setText($("message"), "");
    setText($("source"), ()=>(status.source==="mock" ? t("Синтетический IQ"):"HackRF · RX"));
    setText($("resources"), ()=>(t("CPU {0}% · {1} МБ", decimal(status.resources.process_cpu_percent), decimal(status.resources.rss_bytes/2**20))));
    setText($("capture"), ()=>(t("Потери приложения: {0} отсчётов · USB: неизвестно", status.capture.application_dropped_samples || 0)));
    const adc=status.capture.adc;
    setText($("reception-quality"), ()=>(adc?.sampled_components ? t("Пик АЦП {0} дБFS · крайние значения {1}% выборки", decimal(adc.peak_dbfs,1), decimal(100*adc.sampled_rail_fraction,3)) : t("Уровень приёмника: ждём измерение")));
    setText($("disk"), ()=>(t("Архив: {0} / {1} МБ · свободно {2} ГиБ", decimal((status.archive_bytes || 0)/2**20,1), decimal((status.archive_limit_bytes || 0)/2**20), decimal(status.resources.disk_free_bytes/2**30,1))));
    channels=channelRows;
    if(query().toString()===key) { hasMore=pages[pages.length-1].length===200; rows=[...new Map(pages.flat().map(row=>[row.id,row])).values()]; const playing=rows.find(r=>r.id===currentId); if(playing) { setText($("player-title"), ()=>(playing.title || mhz(playing.frequency_hz)+t(" МГц"))); if(selectedRow) selectedRow.clean_status=playing.clean_status; updateAudioControls(); } renderArchive(); }
    renderChannels();
    if(tabName==="diagnostics") {
      const attempts=await api("/api/digital-attempts?limit=30");
      const labels={encryption_indicated:"Есть признак шифрования",analog_selected:"Выбрана аналоговая речь",audio_candidate:"Получен звук · речь не подтверждена",sync_without_audio:"Есть синхронизация · звука нет",not_decoded:"Речь и цифровой формат не подтверждены"};
      $("digital-attempts").replaceChildren(...(attempts.length ? attempts.map(item=>el("p",()=>(t("{0} · {1} МГц · {2} · {3}{4}", localTime(item.timestamp), mhz(item.frequency_hz), item.outcome==="analog_selected" ? t("Аналоговая FM") : item.protocol || (item.sync_candidates?.length ? t("Возможный формат: ")+item.sync_candidates.join(", ") : t("Неизвестный сигнал")), t(labels[item.outcome] || item.outcome), attemptDiagnostic(item))))) : [el("p",()=>(t("Проверок сигналов пока нет.")))]));
      $("coverage").replaceChildren(...status.coverage.map(win=>el("div",()=>(t("{0}: {1}–{2} МГц · {3}", win.name, mhz(win.start_hz), mhz(win.end_hz), win.observing ? t("приём"):win.seconds_since_last_frame===null ? t("ожидание"):Math.round(win.seconds_since_last_frame)+t(" с назад"))),win.observing ? "observing":"")));
      if(running) { try { const frame=await api("/api/spectrum"); draw(frame); } catch(error) { setText($("frame-time"), ()=>i18n.error(error)); } }
    }
  } catch(error) { notice(error); }
  finally { busy=false; }
}
function attemptDiagnostic(item) {
  const reasons={decoder_error:t("Ошибка декодера"),rf_disappeared:t("Сигнал исчез к концу проверки"),rf_not_confirmed:t("Сигнал отсутствует или ниже порога приёма"),frame_errors_observed:t("Декодер сообщил ошибки кадров"),no_digital_sync:t("Цифровая синхронизация не найдена"),insufficient_sync:t("Недостаточно совпадений синхронизации"),service_frames_observed:t("Наблюдались служебные пакеты DMR")};
  const parts=[];
  let reason=reasons[item.diagnostic_reason] || (item.decoder_error ? reasons.decoder_error:"");
  const relevant=item.protocol ? [item.protocol] : (item.sync_candidates || []);
  const errors=item.diagnostic_error_protocols || Object.keys(item.invalid_counts || {}).filter(p=>item.invalid_counts[p]>0 && (!relevant.length || relevant.includes(p)));
  if(item.diagnostic_reason==="frame_errors_observed") reason=errors.length ? t("Ошибки кадров: {0}", errors.join(", ")) : "";
  if(reason) parts.push(reason);
  const frames=item.frame_summary;
  if(frames) {
    if(frames.voice_burst || frames.voice_header) parts.push(t("Голосовые пакеты DMR: {0}", (frames.voice_burst || 0)+(frames.voice_header || 0)));
    if(frames.idle || frames.control || frames.data) parts.push(t("Служебные пакеты DMR: {0}", (frames.idle || 0)+(frames.control || 0)+(frames.data || 0)));
    if(frames.pi_unresolved) parts.push(t("Заголовок защиты DMR не разобран"));
  }
  if(item.acquisition?.correction_hz) parts.push(t("Настройка уточнена на {0} кГц", decimal(item.acquisition.correction_hz/1000,2)));
  if(item.signal_evidence?.observed_ms>0) parts.push(t("Сигнал выше порога {0}% времени", Math.round(item.signal_evidence.rf_present_fraction*100)));
  return parts.length ? " · "+parts.join(" · "):"";
}
i18n.onChange(()=>{archiveSignature=channelSignature="";renderArchive();renderChannels();});
refresh();
setInterval(refresh,1000);
