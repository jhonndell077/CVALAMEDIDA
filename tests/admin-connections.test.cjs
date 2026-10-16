const {test}=require('node:test');
const assert=require('node:assert/strict');
const fs=require('node:fs');
const vm=require('node:vm');
const {parseHTML}=require('linkedom');
const source=fs.readFileSync('static/admin-connections.js','utf8');
function setup(fetcher){
 const {window}=parseHTML(fs.readFileSync('static/admin-connections.html','utf8'));
 let callback;const auth={currentUser:null,onAuthStateChanged(fn){callback=fn;},signOut(){return Promise.resolve();}};
 window.firebase={auth:()=>auth};
 const context={window,navigator:{},document:window.document,fetch:fetcher,setInterval(){},setTimeout,clearTimeout,AbortSignal,Date,Error,firebase:window.firebase};
 vm.runInNewContext(source,context);
 return {document:window.document,readyWorker:context.readyPushWorker,login(user){auth.currentUser=user;callback(user);}};
}
const settle=()=>new Promise(resolve=>setImmediate(resolve));
test('Push waits for the updated worker to activate before sending',async()=>{
 const ui=setup(async()=>{});let listener,removed=false,ready=false;
 const worker={state:'installing',addEventListener(event,fn){listener=fn;},removeEventListener(){removed=true;}};
 const pending=ui.readyWorker({installing:worker}).then(()=>{ready=true;});
 await settle();assert.equal(ready,false);worker.state='activated';listener();await pending;assert.equal(removed,true);
 await assert.rejects(ui.readyWorker({}));
});
test('non-admin denial never opens the diagnosis',async()=>{
 const ui=setup(async()=>new Response('',{status:403}));
 ui.login({getIdToken:async()=> 'fixture'});await settle();
 assert.equal(ui.document.querySelector('main').hidden,true);
 assert.match(ui.document.getElementById('access-message').textContent,/reservado/);
});
test('logout invalidates late token before any admin request',async()=>{
 let resolve,calls=0;const token=new Promise(r=>{resolve=r;});
 const ui=setup(async()=>{calls++;return new Response('');});
 ui.login({getIdToken:()=>token});ui.login(null);resolve('fixture');await settle();
 assert.equal(calls,0);assert.equal(ui.document.querySelector('main').hidden,true);
});
test('authorized response displays current state and logout clears it',async()=>{
 const at=new Date().toISOString();const ui=setup(async url=>url==='/'?new Response('',{headers:{'Content-Type':'text/html'}}):new Response(JSON.stringify({at,checks:[{id:'api',state:'ok',checkedAt:at,ms:0,detail:'Authenticated fixture'}]})));
 ui.login({getIdToken:async()=> 'fixture'});await settle();await settle();
 assert.equal(ui.document.querySelector('main').hidden,false);
 assert.equal(ui.document.getElementById('node-api').dataset.state,'ok');
 ui.login(null);assert.equal(ui.document.querySelector('main').hidden,true);
 assert.equal(ui.document.getElementById('checks').children.length,0);
 assert.equal(ui.document.getElementById('node-api').dataset.state,undefined);
});
test('a failed dependency remains visible and prevents the job group from turning green',async()=>{
 const at=new Date().toISOString();
 const checks=['api','storage','tasks','worker','vertex'].map(id=>({id,state:id==='tasks'?'error':'ok',checkedAt:at,ms:1,detail:'fixture'}));
 const ui=setup(async url=>url==='/'?new Response('',{headers:{'Content-Type':'text/html'}}):new Response(JSON.stringify({at,checks})));
 ui.login({getIdToken:async()=> 'fixture'});await settle();await settle();
 assert.equal(ui.document.getElementById('node-queue').dataset.state,'error');
 assert.equal(ui.document.getElementById('node-jobs').dataset.state,'error');
 assert.equal(ui.document.getElementById('node-channels').dataset.state,'unknown');
});
test('channels names the missing grant instead of suggesting a confirmed push failed',async()=>{
 const at=new Date().toISOString();
 const checks=['api','telegram','push','gmail'].map(id=>({id,state:id==='gmail'?'unknown':'ok',checkedAt:at,ms:0,detail:'fixture'}));
 const ui=setup(async url=>url==='/'?new Response('',{headers:{'Content-Type':'text/html'}}):new Response(JSON.stringify({at,checks})));
 ui.login({getIdToken:async()=> 'fixture'});await settle();await settle();
 assert.equal(ui.document.getElementById('node-channels').querySelector('.status').textContent,'? Falta: Gmail');
 assert.equal(ui.document.getElementById('node-channels').dataset.state,'unknown');
});
