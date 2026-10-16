const {test}=require('node:test'),assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm');
const {parseHTML}=require('linkedom');
const settle=()=>new Promise(resolve=>setImmediate(resolve));
function setup(fetcher){
 const {window}=parseHTML(fs.readFileSync('static/admin-functionality.html','utf8'));const document=window.document;
 for(const select of document.querySelectorAll('select')){Object.defineProperty(select,'value',{get(){return this._value||this.firstElementChild?.getAttribute('value')||'';},set(v){this._value=v;}});Object.defineProperty(select,'options',{get(){return [...this.children];}});select.add=function(element){this.append(element);};}
 let callback;const auth={currentUser:null,onAuthStateChanged(fn){callback=fn;},signOut:async()=>{}};
 const popup={closed:false,postMessage(){}};const listeners={};
 const browser={addEventListener:(event,fn)=>{listeners[event]=fn;},open:()=>popup};
 vm.runInNewContext(fs.readFileSync('static/admin-functionality.js','utf8'),{window:browser,document,firebase:{auth:()=>auth},location:{origin:'https://app.test'},fetch:fetcher,AbortSignal,setInterval(){},Date,Map,Set,Error});
 return {document,popup,listeners,login(user){auth.currentUser=user;callback(user);}};
}
const manifest={schema:1,generatedAt:new Date().toISOString(),current:{sourceHash:'fixture',buildId:'v1',pages:[{path:'/',label:'Inicio',controls:1}],controls:[{key:'/::#generate',page:'/',selector:'#generate',id:'generate',label:'Generar',group:'main',handlers:[],guards:[],relatedTestCount:0}],dynamicHandlers:[],warnings:[]},tests:{passed:null},previous:{buildId:'v0'},baseline:{buildId:'v1'},changesSincePrevious:{added:[],removed:[],changed:[]},changesSinceBaseline:{added:[],removed:[],changed:[]}};
test('owner gate denies map on failed authorization even if public artifact is available',async()=>{
 const ui=setup(async path=>new Response(JSON.stringify(manifest),{status:path.includes('/api/')?403:200}));ui.login({getIdToken:async()=> 'fixture'});await settle();await settle();assert.equal(ui.document.querySelector('main').hidden,true);
});
test('late sign-in result after logout never sends authenticated diagnostic requests',async()=>{
 let finish,calls=0;const token=new Promise(resolve=>{finish=resolve;});const ui=setup(async()=>{calls++;});ui.login({getIdToken:()=>token});ui.login(null);finish('fixture');await settle();assert.equal(calls,0);assert.equal(ui.document.querySelector('main').hidden,true);
});
test('renders inventory and ignores observation from unrelated windows; signout clears it',async()=>{
 const ui=setup(async path=>new Response(JSON.stringify(path.includes('/api/')?{sourceHash:'fixture',routes:[],flags:{}}:manifest)));ui.login({getIdToken:async()=> 'fixture'});await settle();await settle();assert.equal(ui.document.querySelector('main').hidden,false);assert.match(ui.document.getElementById('counts').textContent,/1 visibles/);
 ui.document.getElementById('observe').click();const message={origin:'https://app.test',source:{},data:{channel:'cv-functional-v1',type:'snapshot',path:'/',controls:[{selector:'#generate',disabled:true,hidden:false,busy:false}]}};
 ui.listeners.message(message);assert.doesNotMatch(ui.document.getElementById('controls').textContent,/Deshabilitado ·/);
 message.source=ui.popup;ui.listeners.message(message);assert.match(ui.document.getElementById('controls').textContent,/Deshabilitado ·/);
 ui.login(null);assert.equal(ui.document.querySelector('main').hidden,true);assert.equal(ui.document.getElementById('events').children.length,0);
});
