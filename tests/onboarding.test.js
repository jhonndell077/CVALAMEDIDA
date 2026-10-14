const {test}=require('node:test');
const assert=require('node:assert/strict');
const fs=require('node:fs');
const vm=require('node:vm');
const {parseHTML}=require('linkedom');
function environment(){
 const {window}=parseHTML(fs.readFileSync('static/index.html','utf8'));
 const {document}=window;
 const form=document.querySelector('#onboarding-form');
 form.elements={namedItem:name=>form.querySelector(`[name="${name}"]`)};
 form.reset=()=>form.querySelectorAll('input[name]').forEach(e=>e.value='');
 for(const dialog of document.querySelectorAll('dialog')){
  dialog.open=false;dialog.showModal=function(){this.open=true};dialog.close=function(){this.open=false};
 }
 const calls=[];
 const context=vm.createContext({window,document,URL,FormData,
  fetch:async path=>{calls.push(path);return {ok:true,json:async()=>({needed:true})}}});
 window.cvDrive={connect:async()=>{}};
 for(const file of ['repeaters','onboarding'])vm.runInContext(fs.readFileSync(`static/${file}.js`,'utf8'),context);
 return {context,window,form,calls,get:selector=>selector.startsWith('[name=')?form.querySelector(selector):document.querySelector(selector),controller:window.cvOnboarding,
  settings:{headers:()=>({}),refreshToken:async()=>{},profile:()=>null,consolidate:async()=>{},completed(){}}};
}
test('initial popup clears personal fields and repeaters on account switch',async()=>{
 const {controller,get,settings,window,form}=environment();
 await controller.initialize({uid:'alice',displayName:'Alice',email:'alice@example.com'},settings);
 assert.equal(get('#onboarding-dialog').open,true);assert.equal(get('[name="name"]').value,'Alice');
 window.cvRepeaters.mount(form.querySelector('[data-repeater="experiences"]')).set([{title:'Private Alice job'}]);
 controller.reset();assert.equal(get('#onboarding-dialog').open,false);
 await controller.initialize({uid:'bob',displayName:'Bob',email:'bob@example.com'},settings);
 assert.equal(get('[name="name"]').value,'Bob');assert.equal(get('[name="email"]').value,'bob@example.com');
 assert.equal(window.cvRepeaters.collect(form).experiences.length,0);
});
test('late onboarding response cannot show a popup for the previous account',async()=>{
 const {controller,context,get,settings}=environment();let resolve;
 context.fetch=()=>new Promise(r=>resolve=r);
 const pending=controller.initialize({uid:'alice'},settings);await new Promise(r=>setImmediate(r));
 controller.reset();resolve({ok:true,json:async()=>({needed:true})});
 await assert.rejects(pending,/cuenta cambi/);assert.equal(get('#onboarding-dialog').open,false);
});
test('view my CV previews unsaved fields without uploading or dismissing onboarding',async()=>{
 const {controller,get,settings,calls}=environment();
 await controller.initialize({uid:'alice',displayName:'Alice'},settings);
 get('#onboarding-preview-open').click();
 assert.equal(get('#onboarding-cv-dialog').open,true);assert.equal(get('#onboarding-dialog').open,true);
 assert.match(get('#onboarding-cv-preview').textContent,/Alice/);
 assert.deepEqual(calls,['/api/account/onboarding']);
});
test('closing and reopening preserves edits and does not automatically reopen on sync',async()=>{
 const {controller,get,settings}=environment();
 await controller.initialize({uid:'alice',displayName:'Alice'},settings);
 get('[name="name"]').value='Edited name';get('[name="address"]').value='Edited address';
 get('#onboarding-close').click();assert.equal(get('#onboarding-dialog').open,false);
 await controller.check();assert.equal(get('#onboarding-dialog').open,false);
 get('#open-onboarding').click();
 assert.equal(get('[name="name"]').value,'Edited name');assert.equal(get('[name="address"]').value,'Edited address');
});
test('routine token renewal preserves an open draft for the same account',async()=>{
 const {controller,get,settings,window,form}=environment();
 await controller.initialize({uid:'alice',displayName:'Alice'},settings);
 window.cvRepeaters.mount(form.querySelector('[data-repeater="experiences"]')).set([{title:'Unsaved experience'}]);
 get('[name="name"]').value='Edited name';
 await controller.initialize({uid:'alice',displayName:'Alice'},settings);
 assert.equal(get('#onboarding-dialog').open,true);
 assert.equal(window.cvRepeaters.collect(form).experiences[0].title,'Unsaved experience');
 assert.equal(get('[name="name"]').value,'Edited name');
});


test('reference import fills editable fields and preserves fields on read failure',async()=>{
 const {controller,context,get,settings,window,form}=environment();
 await controller.initialize({uid:'alice',displayName:'Alias'},settings);
 const input=get('#onboarding-reference-cv'); input.files=[new Blob(['cv'],{type:'application/pdf'})];
 input.files[0].name='cv.pdf';
 context.fetch=async path=>({ok:true,json:async()=>({fields:{name:'Ana',phones:['123'],education:[{title:'Bachiller'}],experiences:[{title:'Auxiliar',responsibilities:['Atender']}],skills:['Comunicación']},notes:[]})});
 input.dispatchEvent(new window.Event('change')); await new Promise(r=>setImmediate(r));
 assert.equal(get('[name="name"]').value,'Ana');
 assert.equal(window.cvRepeaters.collect(form).experiences[0].title,'Auxiliar');
 get('[name="name"]').value='Ana editada';
 context.fetch=async()=>({ok:false,json:async()=>({error:'Ilegible'})});
 input.dispatchEvent(new window.Event('change')); await new Promise(r=>setImmediate(r));
 assert.equal(get('[name="name"]').value,'Ana editada');
 assert.equal(get('#onboarding-error').textContent,'Ilegible');
});
