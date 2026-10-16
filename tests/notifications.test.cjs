const {test}=require('node:test');
const assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm');
const id='web-12345678-1234-1234-1234-123456789abc';
function setup(){
 const handlers={},shown=[],messages=[];
 const state={ready:false,visible:true,closed:false,waiting:null};
 const client={get url(){return state.admin?'https://example.com/admin/conexiones':'https://example.com/';},get visibilityState(){return state.visible?'visible':'hidden'},postMessage(data,ports){messages.push(data);if(ports)ports[0].reply({ready:state.ready})}};
 class Channel {constructor(){const port1={close(){},onmessage:null};this.port1=port1;this.port2={reply:data=>queueMicrotask(()=>port1.onmessage?.({data}))}}}
 const self={location:{origin:'https://example.com'},addEventListener:(type,fn)=>handlers[type]=fn,
  clients:{matchAll:async()=>state.closed?[]:[client]},registration:{showNotification:async(title,options)=>shown.push({title,...options})}};
 const context={self,URL,MessageChannel:Channel,setTimeout:(fn,delay)=>delay===250?setImmediate(()=>{state.waiting?.();fn()}):setTimeout(fn,delay),clearTimeout};
 vm.runInNewContext(fs.readFileSync('static/sw.js','utf8'),context);
 const push=data=>{let promise=Promise.resolve();handlers.push({data:{json:()=>data},waitUntil:p=>promise=p});return promise};
 return {state,shown,messages,push};
}
test('push waits for visible loading to reach 100 before notification', {timeout:3000},async()=>{
 const q=setup();let waits=0;
 q.state.waiting=()=>{waits++;assert.equal(q.shown.length,0);q.state.ready=true};
 await q.push({job_id:id,state:'done',progress:100});
 assert.equal(waits,1);assert.equal(q.shown.length,1);assert.equal(q.shown[0].data.progress,100);
 assert.equal(q.messages[0].type,'cv-process-finished');
});
test('admin probe displays a distinct notification and acknowledges only its nonce',async()=>{
 const q=setup();q.state.admin=true;
 const nonce='12345678-1234-1234-1234-123456789abc';
 await q.push({type:'cv-admin-probe',nonce});
 assert.equal(q.shown.length,1);assert.equal(q.shown[0].data.admin_probe,true);
 assert.equal(q.messages[0].type,'cv-admin-probe-received');assert.equal(q.messages[0].nonce,nonce);
 assert.ok(!q.messages.some(item=>item.type==='cv-process-finished'));
});
test('admin probe does not send its acknowledgement to the ordinary app',async()=>{
 const q=setup();await q.push({type:'cv-admin-probe',nonce:'12345678-1234-1234-1234-123456789abc'});
 assert.equal(q.messages.length,0);
});
for(const change of ['hidden','closed'])test(`confirmed completion notifies if the app becomes ${change}`,{timeout:3000},async()=>{
 const q=setup();q.state.waiting=()=>{assert.equal(q.shown.length,0);if(change==='closed')q.state.closed=true;else q.state.visible=false};
 await q.push({job_id:id,state:'done',progress:100});assert.equal(q.shown.length,1);
});
test('no open app still receives confirmed completion immediately',async()=>{
 const q=setup();q.state.closed=true;await q.push({job_id:id,state:'done',progress:100});assert.equal(q.shown.length,1);
});
test('partial, failed, malformed and legacy push payloads cannot show notifications',async()=>{
 const q=setup();q.state.ready=true;
 for(const payload of [{job_id:id,state:'done',progress:60},{job_id:id,state:'failed',progress:100},{job_id:id,state:'processing',progress:100},{job_id:id},{state:'done',progress:100}])await q.push(payload);
 assert.equal(q.shown.length,0);
});
