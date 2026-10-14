const {test}=require('node:test');
const assert=require('node:assert/strict');
const fs=require('node:fs'),vm=require('node:vm');
const {parseHTML}=require('linkedom');
for(const state of ['done','queued']) test(`restored ${state} CV opens only on request`,async()=>{
 const {window,document}=parseHTML('<div id="background-panel"><div id="background-processes"></div></div><button id="enable-notifications"></button><p id="notifications-status"></p>');
 const id='web-12345678-1234-1234-1234-123456789abc';const events=[];
 window.addEventListener('cv-background-result',event=>events.push(event.detail));
 window.cvLoading={start:()=>Object.assign(()=>{},{update(){}})};
 const context=vm.createContext({window,document,navigator:{},location:{href:'https://example.com'},URL,CustomEvent:window.CustomEvent,localStorage:{getItem:()=>JSON.stringify([{id,path:'/api/draft',state}]),setItem(){}},setTimeout});
 vm.runInContext(fs.readFileSync('static/background.js','utf8'),context);
 const settings={enabled:true,user:()=>({uid:'alice'}),request:async()=>({path:'/api/draft',state:'done',result:{draft:{position:'Example'}}})};
 await window.cvBackground.initialize(settings);await new Promise(resolve=>setImmediate(resolve));
 assert.equal(events.length,0,'restoring must not navigate');
 await window.cvBackground.initialize(settings);assert.equal(events.length,0,'token renewal must not navigate');
 assert.equal(document.querySelector('#background-processes').children.length,0,'old completed tasks stay hidden, even when locally queued');
});
