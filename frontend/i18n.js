"use strict";
// Local-only localization. Bind text/attributes, never replace controls or HTML.
(() => {
  const messages=globalThis.radioMessages;
  const locales={ru:"ru-RU",uk:"uk-UA",en:"en-GB"};
  const bindings=new WeakMap(), listeners=new Set();
  let language="ru";
  try { const saved=localStorage.getItem("radiomind.language.v1"); if(Object.hasOwn(locales,saved)) language=saved; } catch {}
  function t(key,...args) {
    const message=messages[key]?.[language] ?? key;
    return message.replace(/\{(\d+)\}/g,(_,index)=>{
      const value=args[Number(index)];return typeof value==="number" ? number(value) : String(value ?? `{${index}}`);
    });
  }
  function number(value,options={}) { return new Intl.NumberFormat(locales[language],options).format(value); }
  function error(value) {
    if(value?.translationKey)return t(value.translationKey);
    if(Array.isArray(value?.detail))return validation(value.detail);
    if(value?.httpStatus && typeof value.detail!=="string")return t("Не удалось выполнить действие ({0})",value.httpStatus);
    const message=(value?.message ?? String(value ?? "")).replace(/^Value error, /,"");
    return t(message);
  }
  function validation(details) {
    return details.map(detail=>{
      if(detail.loc?.some(part=>part==="start_hz" || part==="end_hz") &&
         ["greater_than_equal","less_than_equal"].includes(detail.type)) return t("Частоты должны быть в пределах 1–6000 МГц");
      return error(detail.msg);
    }).join("; ");
  }
  function deviceLabel(device) {
    const label=`HackRF USB · ${device.serial || t("Серийный номер недоступен")}`;
    return device.label?.endsWith("сейчас используется") ? label+" · "+t("Сейчас используется") : label;
  }
  function bind(node,name,value) {
    if(name==="text") node.removeAttribute("data-i18n");
    let fields=bindings.get(node);
    if(!fields) { fields=new Map(); bindings.set(node,fields); }
    if(typeof value==="function") { fields.set(name,value); node.setAttribute("data-localized",""); }
    else fields.delete(name);
    const rendered=String(typeof value==="function" ? value() : value);
    if(name==="text") node.textContent=rendered; else node.setAttribute(name,rendered);
    return node;
  }
  function apply() {
    document.documentElement.lang=language;
    document.querySelectorAll("[data-i18n]").forEach(node=>{node.textContent=t(node.getAttribute("data-i18n"));});
    for(const name of ["aria-label","placeholder","title"]) {
      document.querySelectorAll(`[data-i18n-${name}]`).forEach(node=>node.setAttribute(name,t(node.getAttribute(`data-i18n-${name}`))));
    }
    document.querySelectorAll("[data-localized]").forEach(node=>{
      for(const [name,render] of bindings.get(node) || []) bind(node,name,render);
    });
    const picker=document.getElementById("language");if(picker)picker.value=language;
  }
  function setLanguage(value) {
    if(!Object.hasOwn(locales,value) || value===language)return;
    language=value;
    try { localStorage.setItem("radiomind.language.v1",value); } catch {}
    apply();for(const listener of listeners)listener();
  }
  globalThis.radioI18n={t,number,error,validation,deviceLabel,text:(node,value)=>bind(node,"text",value),attribute:bind,
    get language(){return language;},get locale(){return locales[language];},
    setLanguage,apply,onChange(listener){listeners.add(listener);return ()=>listeners.delete(listener);}};
  apply();
  const picker=document.getElementById("language");if(picker)picker.onchange=()=>setLanguage(picker.value);
})();
