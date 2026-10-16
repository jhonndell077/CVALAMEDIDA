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
 vm.runInNewContext(source,{window,navigator:{},document:window.document,fetch:fetcher,setInterval(){},AbortSignal,Date,Error,firebase:window.firebase});
 return {document:window.document,login(user){auth.currentUser=user;callback(user);}};
}
const settle=()=>new Promise(resolve=>setImmediate(resolve));
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
