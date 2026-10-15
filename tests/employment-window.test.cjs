const {test}=require('node:test');
const assert=require('node:assert/strict');
const fs=require('node:fs'),vm=require('node:vm');
const {parseHTML}=require('linkedom');
test('employment link opens a modal with original controls and closing preserves the search',()=>{
 const {window,document}=parseHTML(fs.readFileSync('static/index.html','utf8'));
 const dialog=document.querySelector('#employment-window'),link=document.querySelector('.employment-nav');
 dialog.showModal=()=>dialog.open=true;
 dialog.close=()=>{dialog.open=false;dialog.dispatchEvent(new window.Event('close'));};
 vm.runInNewContext(fs.readFileSync('static/employment-window.js','utf8'),{window,document,Event:window.Event});
 link.hidden=false;link.click();assert.equal(dialog.open,true);
 assert.equal(document.querySelector('#employment-panel').parentElement.className,'employment-window-content');
 const query=document.querySelector('#employment-query');query.value='Chef';
 document.querySelector('#employment-window-close').click();assert.equal(dialog.open,false);
 link.click();assert.equal(query.value,'Chef');assert.equal(dialog.open,true);
 document.querySelector('.employment-login-link').click();assert.equal(dialog.open,false);
 assert.equal(document.querySelector('#sync-panel'),null);
 assert.equal(document.querySelector('#sync-bank').hidden,true);
 assert.ok(document.querySelector('#bank-panel #bank-status'));
});
test('model selector is hidden only when a single working model is available',async()=>{
 const source=fs.readFileSync('static/app.js','utf8');
 for(const [models,available,hidden] of [[[{name:'one'}],true,true],[[{name:'one'},{name:'two'}],true,false],[[],false,false]]){
  const row={},elements=new Map();
  const modelSelect={closest:()=>row,replaceChildren(){},add(){}};
  const context=vm.createContext({state:{},modelSelect,$:id=>{if(!elements.has(id))elements.set(id,{});return elements.get(id);},Option:function(){},updateAnalyzeButton(){}});
  vm.runInContext(source.slice(source.indexOf('async function loadModels('),source.indexOf('function loadScript(')),context);
  await context.loadModels({provider:'vertex-ai',model_available:available,models});assert.equal(row.hidden,hidden);
 }
});
