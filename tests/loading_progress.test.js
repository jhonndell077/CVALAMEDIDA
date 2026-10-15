const {test}=require('node:test');
const assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm');
function setup(){
 const nodes=new Map(),frames=new Map(),painted=[];let clock=0,id=0;
 const element=s=>{if(!nodes.has(s))nodes.set(s,{hidden:true,handlers:{},focus(){},addEventListener(type,fn){this.handlers[type]=fn}});return nodes.get(s)};
 const document={hidden:false,activeElement:null,querySelector:element,querySelectorAll:()=>[],body:{classList:{add(){},remove(){}}}};
 const context={window:{},document,performance:{now:()=>clock},requestAnimationFrame:fn=>{frames.set(++id,fn);return id},cancelAnimationFrame:id=>frames.delete(id)};
 vm.runInNewContext(fs.readFileSync('static/loading.js','utf8'),context);
 const frame=(delta=16)=>{clock+=delta;const callbacks=[...frames.values()];frames.clear();callbacks.forEach(fn=>fn(clock));painted.push(Number(element('#loading-percent').textContent.replace('%','')))};
 async function settle(promise){let done=false;promise.then(()=>done=true);for(let i=0;i<250&&!done;i++){frame();await Promise.resolve()}assert.equal(done,true);await promise}
 return {loader:context.window.cvLoading,document,element,frame,settle,painted,frames};
}
test('fast completion paints every integer on its own frame',async()=>{
 const q=setup(),finish=q.loader.start('Rapido');q.painted.push(1);await q.settle(finish());
 assert.deepEqual([...new Set(q.painted)],Array.from({length:100},(_,i)=>i+1));
 assert.equal(q.element('#loading-overlay').hidden,true);assert.equal(q.frames.size,0);
});
test('sparse progress keeps moving without jumps, regressions or premature completion',async()=>{
 const q=setup(),finish=q.loader.start('Sincronizando');
 for(let i=0;i<120;i++)q.frame(100);
 const before=Number(q.element('#loading-percent').textContent.replace('%',''));assert.ok(before>1&&before<99);
 finish.update(85,'Guardando',true);q.frame(10000);assert.equal(Number(q.element('#loading-percent').textContent.replace('%','')),before+1);
 finish.update(3,'Esperando');for(let i=0;i<120;i++)q.frame(1000);
 assert.ok(q.painted.every(v=>v<100));for(let i=1;i<q.painted.length;i++)assert.ok(q.painted[i]-q.painted[i-1]>=0&&q.painted[i]-q.painted[i-1]<=1);
 assert.match(q.element('#loading-detail').textContent,/estimado/);await q.settle(finish());
});
test('nested actions preserve parent progress and errors close without 100',async()=>{
 const q=setup(),finish=q.loader.start('Principal');q.frame(500);const before=q.element('#loading-percent').textContent;
 await q.loader.start('Interna')();assert.equal(q.element('#loading-percent').textContent,before);assert.equal(q.element('#loading-overlay').hidden,false);finish.cancel();
 await assert.rejects(q.loader.run('Error',async update=>{update(60,'Procesando');throw Error('fallo')}),/fallo/);
 assert.equal(q.painted.includes(100),false);assert.equal(q.frames.size,0);assert.equal(q.element('#loading-overlay').hidden,true);
});
test('hidden tabs finish without waiting for animation frames',async()=>{
 const q=setup(),finish=q.loader.start('Oculta');q.document.hidden=true;await finish();assert.equal(q.frames.size,0);assert.equal(q.element('#loading-overlay').hidden,true);
});
test('background is available at 1 percent and dismisses without cancelling work',async()=>{
 const q=setup(),finish=q.loader.start('Conectando');
 assert.equal(q.element('#loading-background').hidden,false);
 assert.equal(q.element('#loading-percent').textContent,'1%');
 assert.equal(q.loader.notificationReady(),false);
 q.element('#loading-background').handlers.click();
 assert.equal(q.element('#loading-overlay').hidden,true);
 finish.update(60,'Proceso en curso');
 assert.equal(q.element('#loading-detail').textContent,'Progreso estimado · Proceso en curso');
 await finish();assert.equal(q.frames.size,0);
});
test('notifications remain blocked while a completed response paints its last percentages',async()=>{
 const q=setup(),finish=q.loader.start('Sincronizando');
 finish.update(60,'Guardando');for(let i=0;i<59;i++)q.frame(1000);
 assert.equal(q.element('#loading-percent').textContent,'60%');
 const completion=finish.complete();
 assert.equal(q.loader.notificationReady(),false);
 for(let i=0;i<39;i++){q.frame();assert.equal(q.loader.notificationReady(),false)}
 q.frame();assert.equal(q.element('#loading-percent').textContent,'100%');assert.equal(q.loader.notificationReady(),true);
 await q.settle(completion);await finish();
});
