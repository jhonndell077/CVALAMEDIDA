const {test}=require('node:test');
const assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm');
const {parseHTML}=require('linkedom');
const jobId='web-12345678-1234-1234-1234-123456789abc';
function setup(records=[], job={state:'done',progress:100,path:'/api/draft',result:{draft:{position:'Test'}}}){
 const {window,document}=parseHTML('<section id="background-panel"><div id="background-processes"></div></section><button id="enable-notifications"></button><p id="notifications-status"></p><div id="process-completed-toast" hidden></div>');
 const timers=new Map(),storage=new Map();let timerId=0;
 const localStorage={getItem:key=>storage.get(key)||JSON.stringify(records),setItem:(key,value)=>storage.set(key,value),removeItem:key=>storage.delete(key)};
 const context={window,document,navigator:{},location:{href:'https://example.com'},URL,CustomEvent:window.CustomEvent,localStorage,
  setTimeout:(fn,delay)=>{timers.set(++timerId,{fn,delay});return timerId},clearTimeout:id=>timers.delete(id)};
 window.cvLoading={backgroundSession:()=>null,start:()=>Object.assign(()=>{},{update(){}})};
 vm.runInNewContext(fs.readFileSync('static/background.js','utf8'),context);
 context.crypto={randomUUID:()=>jobId.slice(4)};
 const settings={enabled:true,user:()=>({uid:'alice'}),request:async path=>path==='/api/background/jobs'?{job_id:jobId}:job};
 const start=()=>window.cvBackground.run('/api/draft',{});
 const emit=(type,detail)=>window.dispatchEvent(new window.CustomEvent(type,{detail}));
 return {window,document,timers,storage,settings,emit,context,start,toast:document.querySelector('#process-completed-toast')};
}
const settle=()=>new Promise(setImmediate);

test('failed task exposes its recovery code and correlation to the interface',async()=>{
 const q=setup([],{state:'failed',progress:3,error:'Revisa el banco',errorCode:'bank_review_required',
  stage:'bank-sync',correlationId:'b'.repeat(32),retryable:false,safeNextAction:'review_bank'});
 await q.window.cvBackground.initialize(q.settings);
 await assert.rejects(q.start(),error=>error.code==='bank_review_required'&&error.correlationId==='b'.repeat(32)&&error.retryable===false);
 assert.match(q.document.querySelector('#background-processes').textContent,/bank_review_required/);
});

test('failed bank process preserves document review details for the owner',async()=>{
 const bank={pending:0,warnings:[{file_id:'fixture-file',name:'Documento de prueba',message:'No se pudo leer',severity:'blocking'}]};
 const q=setup([],{state:'failed',progress:92,path:'/api/bank/sync',error:'Revisa el documento',result:bank});
 await q.window.cvBackground.initialize(q.settings);
 await assert.rejects(q.window.cvBackground.run('/api/bank/sync',{}),error=>error.bankStatus===bank);
 const details=q.document.querySelector('#background-processes details');
 assert.ok(details.open);assert.match(details.textContent,/Documento de prueba/);assert.match(details.textContent,/No se pudo leer/);
 assert.equal(details.querySelector('a').getAttribute('href'),'https://drive.google.com/file/d/fixture-file/view');
 assert.equal(q.toast.hidden,true);
});
test('a local background load marks its row and shows a temporary completion toast',async()=>{
 const q=setup();await q.window.cvBackground.initialize(q.settings);
 q.emit('cv-loading-background',{id:1,message:'Cargando perfil'});
 assert.match(q.document.querySelector('#background-processes').textContent,/Cargando perfil/);
 assert.equal(q.toast.hidden,true);
 q.emit('cv-loading-finished',{id:1,success:true});
 assert.equal(q.toast.hidden,false);assert.equal(q.toast.textContent,'Estado Completado');
 assert.match(q.document.querySelector('.process-done').textContent,/100% · Estado Completado/);
 const timer=[...q.timers.values()].find(timer=>timer.delay===5000);assert.ok(timer);timer.fn();assert.equal(q.toast.hidden,true);
});
test('failed background load cannot show the green completion state',async()=>{
 const q=setup();await q.window.cvBackground.initialize(q.settings);
 q.emit('cv-loading-background',{id:2,message:'Guardando'});q.emit('cv-loading-finished',{id:2,success:false});
 assert.equal(q.toast.hidden,true);assert.equal(q.document.querySelector('.process-done'),null);assert.ok(q.document.querySelector('.process-failed'));
});

test('historical completed jobs are marked without repeating the toast',async()=>{
 const q=setup([{id:jobId,path:'/api/draft',state:'done',announced:true}]);
 await q.window.cvBackground.initialize(q.settings);await settle();assert.equal(q.document.querySelector('.process-done'),null);assert.equal(q.toast.hidden,true);
});
test('completion while hidden queues the in-app toast until the page is visible',async()=>{
 const q=setup();await q.window.cvBackground.initialize(q.settings);q.document.hidden=true;
 q.emit('cv-loading-background',{id:3,message:'Sincronizando'});q.emit('cv-loading-finished',{id:3,success:true});assert.equal(q.toast.hidden,true);
 q.document.hidden=false;q.document.dispatchEvent(new q.window.Event('visibilitychange'));assert.equal(q.toast.hidden,false);
});
test('changing accounts clears a queued toast and ignores the old loading session',async()=>{
 const q=setup();await q.window.cvBackground.initialize(q.settings);
 q.emit('cv-loading-background',{id:4,message:'Guardando'});
 await q.window.cvBackground.initialize({...q.settings,user:()=>({uid:'bob'})});
 q.emit('cv-loading-finished',{id:4,success:true});assert.equal(q.toast.hidden,true);assert.equal(q.document.querySelector('#background-processes').children.length,0);
});

test('a local background placeholder is replaced by its server job and announces once',async()=>{
 const q=setup();await q.window.cvBackground.initialize(q.settings);
 q.window.cvLoading.backgroundSession=()=>5;
 q.window.cvLoading.currentSession=()=>5;
 q.emit('cv-loading-background',{id:5,message:'Generando CV'});
 q.settings.request=async path=>path==='/api/background/jobs'?{job_id:jobId}:{state:'done',progress:100,path:'/api/draft',result:{draft:{position:'Test'}}};
 // The browser chooses the durable request id before sending it to the server.
 q.context.crypto={randomUUID:()=>jobId.slice(4)};
 await q.window.cvBackground.run('/api/draft',{});
 assert.equal(q.document.querySelector('#background-processes').children.length,1);
 assert.equal(q.toast.hidden,true);
 q.window.cvLoading.currentSession=()=>null;
 q.emit('cv-loading-finished',{id:5,success:true});assert.equal(q.toast.hidden,false);
 assert.equal(q.storage.has('cv-processes-alice'),false,'current result is not persisted as login history');
});
test('the real loading button and successful completion drive the toast and process row',async()=>{
 const q=setup();await q.window.cvBackground.initialize(q.settings);
 const container=q.document.createElement('div');
 container.innerHTML='<dialog id="loading-overlay" hidden></dialog><p id="loading-label"></p><progress id="loading-progress"></progress><span id="loading-percent"></span><p id="loading-detail"></p><button id="loading-background"></button>';
 q.document.documentElement.append(container);q.document.querySelector('#loading-overlay').focus=()=>{};
 q.context.performance={now:()=>0};let sequence=0;const frames=new Map();
 q.context.requestAnimationFrame=fn=>{frames.set(++sequence,fn);return sequence};q.context.cancelAnimationFrame=id=>frames.delete(id);
 vm.runInNewContext(fs.readFileSync('static/loading.js','utf8'),q.context);
 const finish=q.window.cvLoading.start('Actualizando perfil');
 q.document.querySelector('#loading-background').click();assert.equal(q.toast.hidden,true);
 await finish();assert.equal(q.toast.hidden,false);assert.match(q.document.querySelector('.process-done').textContent,/100% · Estado Completado/);
});
test('startup moved to background is preserved during the first account initialization',async()=>{
 const q=setup();q.emit('cv-loading-background',{id:6,message:'Cargando'});
 await q.window.cvBackground.initialize(q.settings);
 q.emit('cv-loading-finished',{id:6,success:true});assert.equal(q.toast.hidden,false);assert.ok(q.document.querySelector('.process-done'));
});
test('one user action groups multiple jobs and keeps each result accessible',async()=>{
 const q=setup();await q.window.cvBackground.initialize(q.settings);let session=8,serial=0;
 q.window.cvLoading.currentSession=()=>session;q.window.cvLoading.backgroundSession=()=>session;
 q.context.crypto={randomUUID:()=>`12345678-1234-1234-1234-${String(++serial).padStart(12,'0')}`};
 let path='';q.settings.request=async(url,data)=>{
  if(url==='/api/background/jobs'){path=data.path;return {job_id:`web-${data.request_id}`}}
  return {state:'done',progress:100,path,result:path==='/api/draft'?{draft:{position:'Test'}}:{analysis:{vacancy:{position:'Test'}}}};
 };
 q.emit('cv-loading-background',{id:8,message:'Preparando mi CV'});
 await q.window.cvBackground.run('/api/analyze',{});await q.window.cvBackground.run('/api/draft',{});
 assert.equal(q.document.querySelector('#background-processes').children.length,1);
 assert.equal(q.toast.hidden,true);assert.equal(q.document.querySelector('.process-done'),null);
 session=null;q.emit('cv-loading-finished',{id:8,success:true});
 assert.ok(q.document.querySelector('.process-done'));assert.equal(q.toast.hidden,false);
 assert.equal(q.document.querySelectorAll('#background-processes button').length,2);
});
test('backgrounding during the final counter associates an already finished job',async()=>{
 const q=setup();await q.window.cvBackground.initialize(q.settings);let session=9;
 q.window.cvLoading.currentSession=()=>session;q.context.crypto={randomUUID:()=>jobId.slice(4)};
 q.settings.request=async(url,data)=>url==='/api/background/jobs'?{job_id:jobId}:{state:'done',progress:100,path:'/api/draft',result:{draft:{}}};
 await q.window.cvBackground.run('/api/draft',{});
 q.emit('cv-loading-background',{id:9,message:'Generando CV'});
 assert.equal(q.document.querySelector('#background-processes').children.length,1);
 session=null;q.emit('cv-loading-finished',{id:9,success:true});assert.equal(q.toast.hidden,false);
});
test('toast uses the top layer above dialogs and closes after five seconds',async()=>{
 const q=setup();await q.window.cvBackground.initialize(q.settings);let shown=0,hidden=0;
 q.toast.showPopover=()=>shown++;q.toast.hidePopover=()=>hidden++;
 q.emit('cv-loading-background',{id:10,message:'Sincronizando'});q.emit('cv-loading-finished',{id:10,success:true});assert.equal(shown,1);
 [...q.timers.values()].find(timer=>timer.delay===5000).fn();assert.equal(hidden,1);assert.equal(q.toast.hidden,true);
});





for(const state of ['queued','done','failed'])test(`login discards saved ${state} jobs including unannounced background results`,async()=>{
 const q=setup([{id:jobId,path:'/api/draft',state,backgrounded:true,pendingNotice:true,actionId:'old:1'}]);let calls=0;
 q.settings.request=async()=>{calls++;throw new Error('History must not be fetched')};
 await q.window.cvBackground.initialize(q.settings);await settle();
 assert.equal(calls,0);assert.equal(q.document.querySelector('#background-processes').children.length,0);assert.equal(q.toast.hidden,true);
 assert.equal(q.storage.has('cv-processes-alice'),false);
});

test('current result survives token refresh, opens explicitly, and disappears at next login',async()=>{
 const q=setup();const events=[];q.window.addEventListener('cv-background-result',event=>events.push(event.detail));
 await q.window.cvBackground.initialize(q.settings);await q.start();
 await q.window.cvBackground.initialize(q.settings);await settle();
 assert.equal(events.length,0);assert.equal(q.document.querySelector('#background-processes').children.length,1);
 q.document.querySelector('#background-processes button').click();assert.equal(events.length,1);
 await q.window.cvBackground.initialize({enabled:false,user:()=>null});
 await q.window.cvBackground.initialize(q.settings);await settle();
 assert.equal(q.document.querySelector('#background-processes').children.length,0);
});

test('old push and job link cannot import a previous generation',async()=>{
 const q=setup();let callback,calls=0;
 q.context.navigator.serviceWorker={register:async()=>({}),addEventListener:(name,fn)=>callback=fn};
 // Build a new runtime with the service worker available from initialization.
 vm.runInNewContext(fs.readFileSync('static/background.js','utf8'),q.context);
 q.settings.request=async()=>{calls++;throw new Error('Old job requested')};
 q.context.location.href=`https://example.com/?job=${jobId}`;
 await q.window.cvBackground.initialize(q.settings);
 callback({data:{type:'cv-process-finished',job_id:jobId}});await settle();
 assert.equal(calls,0);assert.equal(q.document.querySelector('#background-processes').children.length,0);
});

test('pageshow reconnects a stalled job explicitly started in this session',async()=>{
 const q=setup();let calls=0;
 q.settings.request=async path=>{if(path==='/api/background/jobs')return {job_id:jobId};if(++calls===1)return new Promise(()=>{});return {state:'done',progress:100,path:'/api/draft',result:{draft:{}}}};
 await q.window.cvBackground.initialize(q.settings);const pending=q.start();await settle();assert.equal(calls,1);
 q.window.dispatchEvent(new q.window.Event('pageshow'));await pending;
 assert.equal(calls,2);assert.ok(q.document.querySelector('.process-done'));
});

test('a delayed submission cannot repopulate the panel after logout and same-account login',async()=>{
 const q=setup();let release,calls=0;
 q.settings.request=async path=>{calls++;return new Promise(resolve=>release=resolve)};
 await q.window.cvBackground.initialize(q.settings);const pending=q.start();
 await q.window.cvBackground.initialize({enabled:false,user:()=>null});await q.window.cvBackground.initialize(q.settings);
 release({job_id:jobId});await assert.rejects(pending,/La sesi/);
 assert.equal(calls,1);assert.equal(q.document.querySelector('#background-processes').children.length,0);
});

for(const failure of [
 {status:503,code:'job_dispatch_unavailable',job_id:jobId},
 {status:503,code:'queue_unavailable'},
 {}
]) test(`uncertain submission retains its cause and explicit retry identity (${failure.code||'network'})`,async()=>{
 const q=setup();let serial=0;const submissions=[];let polls=0;
 q.context.crypto={randomUUID:()=>`12345678-1234-1234-1234-${String(++serial).padStart(12,'0')}`};
 const original=Object.assign(new Error('Error original de despacho'),failure);
 q.settings.request=async(path,data)=>{
  if(path==='/api/background/jobs'){
   submissions.push(data);if(submissions.length===1)throw original;
   return {job_id:`web-${data.request_id}`};
  }
  polls++;return {state:'done',progress:100,path:'/api/draft',result:{draft:{}}};
 };
 await q.window.cvBackground.initialize(q.settings);
 await assert.rejects(q.window.cvBackground.run('/api/draft',{position:'A'}),error=>error===original);
 assert.equal(polls,0,'a rejected or unconfirmed submit must not become a fictional queued job');
 assert.match(q.document.querySelector('.process-failed').textContent,/Error original de despacho/);
 q.window.dispatchEvent(new q.window.Event('online'));await settle();
 assert.equal(submissions.length,1,'reconnect must not repeat external work');
 await q.window.cvBackground.run('/api/draft',{position:'A'});
 assert.equal(submissions[0].request_id,submissions[1].request_id);
 assert.equal(polls,1);assert.equal(q.document.querySelector('#background-processes').children.length,1);
});

test('uncertain retry identity is isolated by payload and account',async()=>{
 const q=setup();let serial=0;const ids=[];
 q.context.crypto={randomUUID:()=>`12345678-1234-1234-1234-${String(++serial).padStart(12,'0')}`};
 q.settings.request=async(path,data)=>{ids.push(data.request_id);throw Object.assign(new Error('Temporal'),{status:503})};
 await q.window.cvBackground.initialize(q.settings);
 await assert.rejects(q.window.cvBackground.run('/api/gmail/send',{to:'first@example.test'}));
 await assert.rejects(q.window.cvBackground.run('/api/gmail/send',{to:'second@example.test'}));
 await q.window.cvBackground.initialize({...q.settings,user:()=>({uid:'bob'})});
 await assert.rejects(q.window.cvBackground.run('/api/gmail/send',{to:'first@example.test'}));
 assert.equal(new Set(ids).size,3);
});

test('a known admission rejection preserves its status without polling a missing job',async()=>{
 const q=setup();let polls=0;
 const rejection=Object.assign(new Error('La cuenta necesita autorización'),{status:403,code:'authorization_required'});
 q.settings.request=async(path)=>{if(path==='/api/background/jobs')throw rejection;polls++;throw new Error('Unexpected poll')};
 await q.window.cvBackground.initialize(q.settings);
 await assert.rejects(q.window.cvBackground.run('/api/bank/sync',{}),error=>error===rejection);
 assert.equal(polls,0);assert.equal(q.window.cvBackground.hasActive(),false);
 assert.match(q.document.querySelector('.process-failed').textContent,/necesita autorización/);
});
