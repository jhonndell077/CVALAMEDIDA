const {test}=require('node:test');
const assert=require('node:assert/strict');
const fs=require('node:fs'),vm=require('node:vm');
const {parseHTML}=require('linkedom');
for(const state of ['done','queued']) test(`restored ${state} CV opens only on request`,async()=>{
 const {window,document}=parseHTML('<div id="background-panel"><div id="background-processes"></div></div><button id="enable-notifications"></button><p id="notifications-status"></p>');
 const id='web-12345678-1234-1234-1234-123456789abc';const events=[];
 window.addEventListener('cv-background-result',event=>events.push(event.detail));
 window.cvLoading={start:()=>Object.assign(()=>{},{update(){}})};
 const context=vm.createContext({window,document,navigator:{},location:{href:'https://example.com'},URL,CustomEvent:window.CustomEvent,localStorage:{getItem:()=>JSON.stringify([{id,path:'/api/draft',state}]),setItem(){}},setTimeout,clearTimeout});
 vm.runInContext(fs.readFileSync('static/background.js','utf8'),context);
 const settings={enabled:true,user:()=>({uid:'alice'}),request:async()=>({path:'/api/draft',state:'done',result:{draft:{position:'Example'}}})};
 await window.cvBackground.initialize(settings);await new Promise(resolve=>setImmediate(resolve));
 assert.equal(events.length,0,'restoring must not navigate');
 await window.cvBackground.initialize(settings);assert.equal(events.length,0,'token renewal must not navigate');
 if(state==='done') { assert.equal(document.querySelector('#background-processes').children.length,0,'old history is not replayed as new actions');return; }
 assert.equal(document.querySelector('#background-processes').children.length,1,'newly recovered completion remains visible');
 assert.match(document.querySelector('#background-processes').textContent,/100% · Estado Completado/);
 assert.ok(document.querySelector('.process-done'));
 document.querySelector('#background-processes button').click();assert.equal(events.length,1,'the result opens only on request');
});


test('an old watcher cannot commit after logout and login with the same UID',async()=>{
 const source=fs.readFileSync('static/background.js','utf8');
 let release;const rendered=[];
 const context=vm.createContext({owner:'alice',generation:0,watchers:new Map(),progressListeners:new Map(),jobs:new Map(),
 enabled:()=>true,titles:{},status:()=>new Promise(r=>{release=r}),render:(record,job)=>rendered.push(job),
 persist(){},delivered:new Set(),completedToast(){},notice:{},
 window:{cvLoading:{}},document:{hidden:false}});
 vm.runInContext(source.slice(source.indexOf('  async function watch('),source.indexOf('  async function run(')),context);
 const pending=vm.runInContext("watch({id:'job',path:'/api/draft',state:'queued'},true)",context).catch(()=>null);
 context.owner='';context.generation++;context.owner='alice';context.generation++;
 release({path:'/api/draft',state:'done',progress:100,result:{private:'old-session'}});
 await pending;
 assert.equal(rendered.length,1,'old generation must not commit even when the UID matches again');
});
