const {test}=require('node:test');
const assert=require('node:assert/strict');
const fs=require('node:fs'),vm=require('node:vm');
const source=fs.readFileSync('static/app.js','utf8');
test('failed save reuses its ID until the user changes the information',async()=>{
 const elements=new Map(),requests=[];let handler,nextId=0,title='Curso de prueba';
 const $=id=>{if(!elements.has(id))elements.set(id,{hidden:false,textContent:''});return elements.get(id)};
 const form={hidden:false,addEventListener:(name,fn)=>handler=fn};
 const context=vm.createContext({state:{},$,informationForm:form,informationSaving:false,informationRequestId:null,informationRequestSignature:null,
   crypto:{randomUUID:()=>String(++nextId).padStart(32,'0')},FormData:class{*[Symbol.iterator](){yield ['type','courses'];yield ['title',title];}},
   window:{cvRepeaters:{collect:()=>({})}},setBusy(){},requestJson:async(path,payload)=>{requests.push(payload);throw Error('Conexión interrumpida');}});
 vm.runInContext(source.slice(source.indexOf('informationForm.addEventListener("submit"'),source.indexOf('const templateDetails')),context);
 for(let i=0;i<2;i++)await handler({preventDefault(){}});
 assert.equal(requests[0].request_id,requests[1].request_id);
 title='Curso corregido';await handler({preventDefault(){}});
 assert.notEqual(requests[1].request_id,requests[2].request_id);
 assert.equal(context.informationSaving,false);
 assert.equal(form.hidden,false);
});
for(const recovered of [false,true]) test(`saved information refreshes cards and invalidates previous CV (${recovered?'recovered':'direct'})`,async()=>{
 const elements=new Map(),state={analysis:{old:true},draft:{old:true},pdf:{old:true},vacancyRevision:4};
 const $=id=>{if(!elements.has(id))elements.set(id,{hidden:false,textContent:''});return elements.get(id)};
 let handler,renders=0;
 const profile={courses:[{id:'new-record',title:'Fixture'}]};
 const form={hidden:false,elements:{type:{dispatchEvent(){}}},reset(){},addEventListener:(name,fn)=>handler=fn};
 const context=vm.createContext({state,$,structuredClone,Event,crypto:{randomUUID:()=> 'request-id'},FormData:class{*[Symbol.iterator](){yield ['type','courses'];yield ['title','Fixture'];}},informationForm:form,informationSaving:false,informationRequestId:null,
 informationRequestSignature:null,window:{cvRepeaters:{collect:()=>({}),reset(){}},addEventListener:(name,fn)=>handler=fn},requestJson:async()=>({profile,message:'Guardado'}),setBusy(){},closeInformationForm(){form.hidden=true},renderProfileTree(){renders++},loadProfileSummary(){throw Error('Do not reload stale profile after confirmed save')},analysisPanel:$('analysis'),cvPanel:$('cv'),jobPanel:$('job')});
 vm.runInContext(source.slice(source.indexOf('function applySavedProfile('),source.indexOf('function renderKnowledgeMap(')),context);
 if(recovered){vm.runInContext(source.slice(source.indexOf("window.addEventListener('cv-background-result'"),source.indexOf('function setActiveStep(')),context);await handler({detail:{path:'/api/profile/information',result:{profile,message:'Guardado'}}});}
 else {vm.runInContext(source.slice(source.indexOf('informationForm.addEventListener("submit"'),source.indexOf('const templateDetails')),context);await handler({preventDefault(){}});}
 assert.equal(state.profile.courses[0].id,'new-record');assert.equal(renders,1);assert.equal(state.draft,null);assert.equal(state.analysis,null);assert.equal(state.pdf,null);assert.equal(state.vacancyRevision,5);
 assert.equal($('cv').hidden,true);assert.equal($('job').hidden,false);
});

test('profile refresh begun before an edit cannot overwrite the saved result',async()=>{
 const state={user:{uid:'fixture'},vacancyRevision:1};let release,applied=false;
 const response=new Promise(resolve=>release=resolve);
 const context=vm.createContext({state,fetch:()=>response,authenticatedHeaders:()=>({}),applySavedProfile(){applied=true}});
 vm.runInContext(source.slice(source.indexOf('async function loadProfileSummaryWork('),source.indexOf('function applySavedProfile(')),context);
 const pending=context.loadProfileSummaryWork();state.vacancyRevision=2;
 release({ok:true,json:async()=>({courses:[]})});await pending;assert.equal(applied,false);
});
