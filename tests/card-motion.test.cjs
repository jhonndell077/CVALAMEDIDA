const {test}=require('node:test');
const assert=require('node:assert/strict');
const fs=require('node:fs'),vm=require('node:vm');
const {parseHTML}=require('linkedom');
function setup(reduced=false){
 const {window,document}=parseHTML('<html><body><div id="profile-tree"><details class="profile-node"><summary><span class="profile-card-icon">◇</span>Proyecto</summary><div class="profile-node-body"><input value="Conservar borrador"></div></details></div><button id="open">Abrir</button><dialog><input value="Contacto sin guardar"></dialog></body></html>');
 const animations=[],listeners={};let observe;
 window.HTMLElement.prototype.getBoundingClientRect=()=>({left:30,top:50,width:300,height:90});
 window.HTMLElement.prototype.animate=function(frames,options){const animation={finished:Promise.resolve(),cancel(){animation.cancelled=true;}};animations.push({element:this,frames,options,animation});return animation;};
 const dialog=document.querySelector('dialog');Object.defineProperty(dialog,'open',{get:()=>dialog.hasAttribute('open')});
 const root={document,MutationObserver:class {constructor(callback){observe=callback;}observe(){}},matchMedia:()=>({matches:reduced,addEventListener(){}}),addEventListener:(type,fn)=>listeners[type]=fn};
 let clock=1000;
 class Clock extends Date {static now(){return clock;}}
 vm.runInNewContext(fs.readFileSync('static/card-motion.js','utf8'),{window:root,Date:Clock});
 return {document,window,root,animations,listeners,tick:()=>clock+=250,mutate:()=>observe([{type:'attributes',target:dialog}]),dialog};
}
test('motion respects reduced preference and leaves form drafts intact',()=>{
 const qa=setup(true);qa.dialog.setAttribute('open','');qa.mutate();
 assert.equal(qa.animations.length,0);
 assert.equal(qa.document.querySelector('.profile-node input').value,'Conservar borrador');
 assert.equal(qa.dialog.querySelector('input').value,'Contacto sin guardar');
});
test('native modal expands from trigger and closing creates only an inert color cover',async()=>{
 const qa=setup();qa.document.querySelector('#open').dispatchEvent(new qa.window.Event('click',{bubbles:true}));
 qa.dialog.setAttribute('open','');qa.mutate();
 const opening=qa.animations.find(item=>item.element===qa.dialog);
 assert.match(opening.frames[0].transform,/translate\(/);
 qa.dialog.removeAttribute('open');qa.mutate();
 const cover=qa.document.querySelector('.cv-motion-cover');
 assert.equal(cover.getAttribute('aria-hidden'),'true');assert.equal(cover.children.length,0);
 assert.equal(qa.dialog.querySelector('input').value,'Contacto sin guardar');
 await new Promise(setImmediate);assert.equal(qa.document.querySelector('.cv-motion-cover'),null);
});
test('card toggles animate their existing body and resize cancels motion',()=>{
 const qa=setup(),card=qa.document.querySelector('.profile-node');card.open=true;
 card.dispatchEvent(new qa.window.Event('toggle'));
 assert.ok(qa.animations.some(item=>item.element.classList.contains('profile-node-body')));
 qa.listeners.resize();assert.ok(qa.animations.some(item=>item.animation.cancelled));
 assert.equal(card.querySelector('input').value,'Conservar borrador');
});

test('button feedback is visible without blocking its action and clears the wave',async()=>{
 const qa=setup();const button=qa.document.querySelector('#open');let actions=0;
 button.addEventListener('click',()=>actions++);
 const click=new qa.window.Event('click',{bubbles:true,cancelable:true});button.dispatchEvent(click);
 assert.equal(actions,1);assert.equal(click.defaultPrevented,false);
 const feedback=qa.animations.find(item=>item.element===button);
 assert.equal(feedback.frames[0].transform,'scale(.98)');
 assert.equal(feedback.frames[1].transform,'scale(1)');
 assert.equal(button.querySelector('.cv-button-wave').getAttribute('aria-hidden'),'true');
 await new Promise(setImmediate);assert.equal(button.querySelector('.cv-button-wave'),null);
});

test('scroll no longer starts a continuous bounce loop',()=>{
 const qa=setup();assert.equal(qa.listeners.scroll,undefined);
});

test('busy buttons restore original label and decorations after success or failure',()=>{
 const source=fs.readFileSync('static/app.js','utf8');
 const qa=setup(),button=qa.document.querySelector('#open');
 const original=[...button.childNodes];let finished=0;
 const context=vm.createContext({busyButtons:new WeakMap(),window:{cvLoading:{start:()=>()=>finished++}}});
 vm.runInContext(source.slice(source.indexOf('function setBusy('),source.indexOf('function showError(')),context);
 for(const label of ['Guardando','Sincronizando']) {
   context.setBusy(button,true,label);qa.mutate();
   assert.equal(button.textContent,label);assert.equal(button.disabled,true);
   context.setBusy(button,false);qa.mutate();
   assert.equal(button.textContent,'Abrir');assert.equal(button.disabled,false);
   assert.deepEqual([...button.childNodes],original);
   assert.equal(button.querySelectorAll('.cv-galaxy-decoration').length,1);
   assert.equal(button.querySelectorAll('.cv-button-label').length,1);
 }
 assert.equal(finished,2);
});

test('galaxy decorates dynamic buttons and restores decoration after label updates without duplicates',()=>{
 const qa=setup(),button=qa.document.querySelector('#open');
 assert.equal(button.textContent,'Abrir');
 assert.equal(button.querySelector('.cv-galaxy-decoration').getAttribute('aria-hidden'),'true');
 qa.mutate();assert.equal(button.querySelectorAll('.cv-galaxy-decoration').length,1);
 button.textContent='Guardando';qa.mutate();
 assert.equal(button.textContent,'Guardando');assert.equal(button.querySelectorAll('.cv-galaxy-decoration').length,1);
 const added=qa.document.createElement('button');added.textContent='Adaptar mi CV';qa.dialog.append(added);qa.mutate();
 assert.ok(added.classList.contains('cv-galaxy-button'));assert.equal(added.textContent,'Adaptar mi CV');
});

test('history action survives repeated async label replacements and clicks on its label',()=>{
 const qa=setup(),button=qa.document.querySelector('#open');let actions=0;
 button.id='refresh-application-history';button.classList.add('button','button-secondary');
 button.addEventListener('click',()=>actions++);
 for(const text of ['Cargando historial de envío','Consultar historial en Drive']) {
   button.textContent=text;
   // A label change can render before the decoration observer runs.
   assert.equal(button.textContent,text);
   qa.mutate();
   const label=button.querySelector('.cv-button-label');
   assert.equal(label.textContent,text);
   label.dispatchEvent(new qa.window.Event('click',{bubbles:true}));
   assert.equal(button.querySelectorAll('.cv-galaxy-decoration').length,1);
 }
 assert.equal(actions,2);
 const css=fs.readFileSync('static/card-motion.css','utf8');
 assert.match(css,/\.cv-galaxy-decoration\s*\{[^}]*z-index:-2/);
 assert.match(css,/\.cv-button-wave\s*\{[^}]*z-index:-1/);
 assert.doesNotMatch(css,/mix-blend-mode:screen/);
});
