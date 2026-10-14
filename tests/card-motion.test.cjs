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
