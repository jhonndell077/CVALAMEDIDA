const {test}=require('node:test');
const assert=require('node:assert/strict');
const fs=require('node:fs');
const vm=require('node:vm');
const {parseHTML}=require('linkedom');
function setup(){
 const {window}=parseHTML(fs.readFileSync('static/index.html','utf8'));
 const {document}=window;
 const form=document.querySelector('#onboarding-form');
 form.elements={namedItem:name=>form.querySelector(`[name="${name}"]`)};
 form.reset=()=>form.querySelectorAll('input[name]').forEach(e=>e.value='');
 for(const dialog of document.querySelectorAll('dialog')){dialog.showModal=function(){this.open=true};dialog.close=function(){this.open=false};}
 const calls=[];
 const context=vm.createContext({window,document,URL,FormData,fetch:async(path)=>{calls.push(path);return {ok:true,json:async()=>({needed:true})}}});
 for(const file of ['repeaters','onboarding'])vm.runInContext(fs.readFileSync(`static/${file}.js`,'utf8'),context);
 return {window,document,form,calls,settings:{profile:()=>null,refreshToken:async()=>{},headers:()=>({})}};
}
test('preview uses unsaved fields, nested entries and safe text; closing preserves draft',async()=>{
 const {window,document,form,calls,settings}=setup();
 await window.cvOnboarding.initialize({uid:'a',displayName:'Alice'},settings);
 form.elements.namedItem('name').value='<img src=x onerror=alert(1)>';
 window.cvRepeaters.mount(form.querySelector('[data-repeater="experiences"]')).set([{title:'Chef',employer:'Restaurant',responsibilities:['Preparar platos']}]);
 window.cvRepeaters.mount(form.querySelector('[data-repeater="projects"]')).set([{title:'Proyecto',description:'Trabajo práctico',technologies:['Excel']}]);
 document.querySelector('#onboarding-preview-open').click();
 const preview=document.querySelector('#onboarding-cv-preview');
 assert.equal(document.querySelector('#onboarding-cv-dialog').open,true);
 assert.match(preview.textContent,/Chef/);assert.match(preview.textContent,/Preparar platos/);assert.match(preview.textContent,/Excel/);
 assert.equal(preview.querySelector('img'),null);
 document.querySelector('#onboarding-preview-back').click();
 assert.equal(document.querySelector('#onboarding-dialog').open,true);
 assert.match(form.elements.namedItem('name').value,/onerror/);
 form.elements.namedItem('name').value='Nuevo nombre';
 document.querySelector('#onboarding-preview-open').click();assert.match(preview.textContent,/Nuevo nombre/);
 window.cvOnboarding.reset();assert.equal(preview.textContent,'');assert.equal(document.querySelector('#onboarding-cv-dialog').open,false);
 assert.deepEqual(calls,['/api/account/onboarding']);
});
test('history is initially collapsed and contains existing history controls',()=>{
 const {document}=setup();const details=document.querySelector('#application-history-details');
 assert.ok(details);assert.equal(details.hasAttribute('open'),false);
 assert.ok(details.querySelector('summary'));assert.ok(details.querySelector('#refresh-application-history'));assert.ok(details.querySelector('#application-history'));
});

test('removing an unreadable optional reference preserves form and clears the blocking error',async()=>{
 const {window,document,form,settings}=setup();
 await window.cvOnboarding.initialize({uid:'a',displayName:'Alice'},settings);
 form.elements.namedItem('name').value='Nombre conservado';
 const file=document.querySelector('#onboarding-reference-cv');file.value='CV.pdf';
 const error=document.querySelector('#onboarding-error');error.hidden=false;error.textContent='No se pudo leer';
 document.querySelector('#onboarding-reference-remove').click();
 assert.equal(file.value,'');assert.equal(error.hidden,true);
 assert.equal(form.elements.namedItem('name').value,'Nombre conservado');
 assert.match(document.querySelector('#onboarding-status').textContent,/Guardar y consolidar/);
});
