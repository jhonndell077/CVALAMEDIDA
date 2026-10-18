const {test}=require('node:test');
const assert=require('node:assert/strict');
const fs=require('node:fs'),vm=require('node:vm');
const {parseHTML}=require('linkedom');

function setup(){
 const {window,document}=parseHTML(fs.readFileSync('static/index.html','utf8'));
 const observers=[];
 class Observer{constructor(callback){this.callback=callback;observers.push(this)}observe(target){this.target=target}}
 const dialog=document.querySelector('#data-dialog');
 Object.defineProperty(dialog,'open',{get:()=>dialog.hasAttribute('open')});
 dialog.showModal=()=>dialog.setAttribute('open','');
 dialog.close=()=>{dialog.removeAttribute('open');dialog.dispatchEvent(new window.Event('close'))};
 const listeners={};
 const root={scrollY:0,innerWidth:1000,scrollTo(){},addEventListener(type,handler){listeners[type]=handler}};
 vm.runInNewContext(fs.readFileSync('static/data-panel.js','utf8'),{document,window:root,MutationObserver:Observer,matchMedia:()=>({matches:true})});
 return {document,dialog,emit:(type,detail)=>listeners[type]?.({detail}),notify:target=>observers.filter(o=>o.target===target).forEach(o=>o.callback())};
}

test('Datos opens before synchronization and remains visible across account state changes',async()=>{
 const {document,dialog,notify}=setup();
 const button=document.querySelector('#data-toggle'),panel=document.querySelector('#profile-panel');
 const unavailable=document.querySelector('#data-unavailable'),actions=document.querySelector('#data-actions');
 assert.equal(panel.hidden,true);assert.equal(button.hidden,false);
 button.click();assert.equal(dialog.open,true);assert.equal(unavailable.hidden,false);
 assert.equal(actions.parentNode,dialog);
 panel.hidden=false;notify(panel);assert.equal(unavailable.hidden,true);
 panel.hidden=true;notify(panel);assert.equal(dialog.open,true);assert.equal(button.hidden,false);
 button.click();await Promise.resolve();assert.equal(dialog.open,false);
 assert.equal(actions.parentNode,document.body);assert.equal(button.getAttribute('aria-expanded'),'false');
});

test('floating sync delegates to the original action and follows its busy state',()=>{
 const {document,notify}=setup();
 const original=document.querySelector('#sync-bank'),floating=document.querySelector('#data-sync');let clicks=0;
 original.addEventListener('click',()=>clicks++);
 assert.equal(floating.hidden,false);assert.equal(floating.disabled,true);
 original.disabled=false;notify(original);assert.equal(floating.disabled,false);
 floating.click();assert.equal(clicks,1);
 original.disabled=true;notify(original);assert.equal(floating.disabled,true);
 original.disabled=false;notify(original);assert.equal(floating.disabled,false);
});

test('cloud arrows rotate independently of the cloud and respect reduced motion',()=>{
 const {document}=setup();const css=fs.readFileSync('static/styles.css','utf8');
 assert.ok(document.querySelector('#data-sync .cloud-sync-arrows'));
 assert.equal(document.querySelector('#data-sync .cloud-sync-arrows').contains(document.querySelector('#data-sync svg > path')),false);
 assert.match(css,/\.cloud-sync-arrows\s*\{[^}]*animation: cloud-sync-spin 3s linear infinite/);
 assert.match(css,/@media \(prefers-reduced-motion: reduce\).*\.cloud-sync-arrows.*animation: none/);
});


test('signed-in disconnected user sees Drive instructions and sync errors inside Datos',()=>{
 const {document,emit}=setup();
 emit('cv-session-state',{signedIn:true});
 assert.match(document.querySelector('#data-unavailable').textContent,/Tu sesión está iniciada/);
 emit('cv-app-error',{message:'Google bloqueó la ventana de autorización.'});
 const error=document.querySelector('#data-connection-error');
 assert.equal(error.hidden,false);assert.match(error.textContent,/Google bloqueó/);
 emit('cv-app-error',{message:''});assert.equal(error.hidden,true);
 emit('cv-app-error',{message:'Cuenta anterior'});
 emit('cv-session-state',{signedIn:false});assert.equal(error.hidden,true);
 assert.doesNotMatch(document.querySelector('#data-unavailable').textContent,/Tu sesión está iniciada/);
});
