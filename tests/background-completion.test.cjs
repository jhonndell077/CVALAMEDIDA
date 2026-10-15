const {test}=require('node:test');
const assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm');
const {parseHTML}=require('linkedom');
const jobId='web-12345678-1234-1234-1234-123456789abc';
function setup(records=[], job={state:'done',progress:100,path:'/api/draft',result:{draft:{position:'Test'}}}){
 const {window,document}=parseHTML('<section id="background-panel"><div id="background-processes"></div></section><button id="enable-notifications"></button><p id="notifications-status"></p><div id="process-completed-toast" hidden></div>');
 const timers=new Map(),storage=new Map();let timerId=0;
 const localStorage={getItem:key=>storage.get(key)||JSON.stringify(records),setItem:(key,value)=>storage.set(key,value)};
 const context={window,document,navigator:{},location:{href:'https://example.com'},URL,CustomEvent:window.CustomEvent,localStorage,
  setTimeout:(fn,delay)=>{timers.set(++timerId,{fn,delay});return timerId},clearTimeout:id=>timers.delete(id)};
 window.cvLoading={backgroundSession:()=>null,start:()=>Object.assign(()=>{},{update(){}})};
 vm.runInNewContext(fs.readFileSync('static/background.js','utf8'),context);
 const settings={enabled:true,user:()=>({uid:'alice'}),request:async()=>job};
 const emit=(type,detail)=>window.dispatchEvent(new window.CustomEvent(type,{detail}));
 return {window,document,timers,storage,settings,emit,context,toast:document.querySelector('#process-completed-toast')};
}
const settle=()=>new Promise(setImmediate);
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
test('a completed pending server job is marked and announced once on recovery',async()=>{
 const q=setup([{id:jobId,path:'/api/draft',state:'queued',backgrounded:true}]);
 await q.window.cvBackground.initialize(q.settings);await settle();
 assert.equal(q.toast.hidden,false);assert.ok(q.document.querySelector('.process-done'));
 const saved=JSON.parse(q.storage.get('cv-processes-alice'));assert.equal(saved[0].announced,true);
 const count=q.timers.size;await q.window.cvBackground.initialize(q.settings);await settle();assert.equal(q.timers.size,count);
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
test('a recovered completion waits until visible loading reaches 100',async()=>{
 const q=setup([{id:jobId,path:'/api/draft',state:'queued'}]);let ready=false;
 q.window.cvLoading.notificationReady=()=>ready;
 await q.window.cvBackground.initialize(q.settings);await settle();
 assert.equal(q.toast.hidden,true);assert.ok(q.document.querySelector('.process-done'));
 ready=true;[...q.timers.values()].find(timer=>timer.delay===250).fn();assert.equal(q.toast.hidden,false);
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
 assert.equal(JSON.parse(q.storage.get('cv-processes-alice'))[0].announced,true);
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
