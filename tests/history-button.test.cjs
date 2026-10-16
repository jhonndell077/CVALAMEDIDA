const {test}=require('node:test'),assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm');
const {parseHTML}=require('linkedom');
const source=fs.readFileSync('static/app.js','utf8');
function setup(connect=async()=>{}){
 const {document}=parseHTML(fs.readFileSync('static/index.html','utf8'));
 const calls=[],loads=[];let resolve;
 const state={user:{uid:'fixture',getIdToken:async()=> 'fixture'},authEpoch:1,applications:[]};
 const context=vm.createContext({document,state,$:selector=>document.querySelector(selector),URLSearchParams,WeakMap,
  window:{cvDrive:{connect,headers:()=>({})},cvLoading:{start:label=>{const operation={label,finished:false};loads.push(operation);return ()=>{operation.finished=true;};}}},
  authenticatedHeaders:h=>h,renderApplications(){},processFetch:(path,options)=>{calls.push({path,method:options.method});return new Promise(r=>{resolve=r;});}});
 vm.runInContext(source.slice(source.indexOf('const busyButtons ='),source.indexOf('function showError(')),context);
 vm.runInContext(source.slice(source.indexOf('async function applicationRequest('),source.indexOf('function renderApplications(')),context);
 vm.runInContext(source.slice(source.indexOf('async function refreshApplications('),source.indexOf('async function prepareApplication(')),context);
 return {document,state,calls,loads,context,respond:data=>resolve(data)};
}
const tick=()=>new Promise(setImmediate);
test('history click disables and labels button, reads GET, restores button and reports empty history',async()=>{
 const ui=setup(),button=ui.document.querySelector('#refresh-application-history');
 const pending=ui.context.refreshApplications({type:'click'});await tick();
 assert.equal(button.disabled,true);assert.equal(button.textContent,'Cargando historial de envío');
 assert.equal(ui.loads[0].label,'Cargando historial de envío');assert.deepEqual(ui.calls,[{path:'/api/applications',method:'GET'}]);
 ui.respond({ok:true,json:async()=>({entries:[],has_more:false})});await pending;
 assert.equal(button.disabled,false);assert.equal(button.textContent,'Consultar historial en Drive');assert.equal(ui.loads[0].finished,true);
 assert.equal(ui.document.querySelector('#application-history-status').textContent,'Todavía no has preparado postulaciones.');
});
test('Drive authorization failure stops history read and restores loading state',async()=>{
 const ui=setup(async()=>{throw Error('Autorización Drive requerida');});await ui.context.refreshApplications();
 assert.equal(ui.calls.length,0);assert.equal(ui.loads[0].finished,true);
 assert.equal(ui.document.querySelector('#refresh-application-history').disabled,false);
 assert.match(ui.document.querySelector('#application-history-status').textContent,/Autorización Drive/);
});
test('HTTP failure remains an error message, does not replace existing records, and ends loading',async()=>{
 const ui=setup();ui.state.applications=[{application_id:'previous'}];
 const pending=ui.context.refreshApplications();await tick();ui.respond({ok:false,json:async()=>({error:'Permiso insuficiente'})});await pending;
 assert.equal(ui.state.applications[0].application_id,'previous');assert.equal(ui.loads[0].finished,true);
 assert.match(ui.document.querySelector('#application-history-status').textContent,/Permiso insuficiente/);
});
