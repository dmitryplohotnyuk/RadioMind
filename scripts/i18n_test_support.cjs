const fs=require('node:fs'),vm=require('node:vm');
module.exports=function loadI18n(context) {
  const doc=context.document;
  doc.documentElement ||= {};
  doc.querySelectorAll ||= ()=>[];
  const enhance=node=>{node.removeAttribute ||= ()=>{};node.setAttribute ||= ()=>{};return node;};
  const get=doc.getElementById.bind(doc);doc.getElementById=id=>enhance(get(id));
  if(doc.createElement){const create=doc.createElement.bind(doc);doc.createElement=(...args)=>enhance(create(...args));}
  for(const file of ['messages','i18n'])vm.runInContext(fs.readFileSync(`frontend/${file}.js`,'utf8'),context);
};
