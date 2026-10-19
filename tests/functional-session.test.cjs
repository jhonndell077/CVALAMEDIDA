const {test}=require('node:test'), assert=require('node:assert/strict');
const fs=require('node:fs'), vm=require('node:vm');
const source=fs.readFileSync('static/functional-session.js','utf8');
const tick=()=>new Promise(r=>setImmediate(r));
function fixture(fetcher) {
  const elements=[], events={}, calls=[];
  function element(tag) { const x={tag,children:[],textContent:'',hidden:false,
    append(...nodes){this.children.push(...nodes);},replaceChildren(){this.children=[];},
    setAttribute(){},addEventListener(name,handler){this[name]=handler;}};elements.push(x);return x; }
  const container=element('container'), sidebar=element('sidebar');
  const window={addEventListener:(n,f)=>events[n]=f};
  const document={hidden:false,querySelector:s=>s==='#workspace-sidebar'?sidebar:container,createElement:element,
    addEventListener:(n,f)=>events[n]=f};
  vm.runInNewContext(source,{window,document,AbortController,setTimeout,clearTimeout,
    setInterval:f=>events.poll=f,fetch:async(...args)=>{calls.push(args);return fetcher(...args);}});
  return {api:window.cvFunctionalSession,elements,events,calls,sidebar,
    user:uid=>({uid,getIdToken:async()=>uid}),status:()=>elements.find(x=>x.tag==='p').textContent};
}
const state=n=>({ok:true,json:async()=>({available:true,scope:'account',errorCount:n,
  incidents:Array.from({length:n},()=>({service:'api',endpoint:'/api/background/jobs',code:503}))})});
test('seventy independent browser sessions show the same five confirmed incidents',async()=>{
  const clients=Array.from({length:70},()=>fixture(async()=>state(5)));
  clients.forEach(x=>x.api.initialize(x.user('same-account')));await tick();
  clients.forEach(x=>{assert.match(x.status(),/^5 incidencias/);assert.equal(x.calls.length,1);});
});
test('local offline failure preserves last server evidence and retries online',async()=>{
  let offline=false;const x=fixture(async()=>{if(offline)throw Error('offline');return state(5);});
  x.api.initialize(x.user('a'));await tick();offline=true;x.events.online();await tick();
  assert.match(x.status(),/^5 incidencias/);assert.match(x.status(),/No se pudo actualizar/);
  offline=false;x.events.online();await tick();assert.doesNotMatch(x.status(),/No se pudo actualizar/);
});
test('late previous account response cannot overwrite new owner and token refresh preserves evidence',async()=>{
  let resolve;const x=fixture(async()=>x.calls.length===1?new Promise(r=>resolve=r):state(0));
  x.api.initialize(x.user('old'));await tick();x.api.initialize(x.user('new'));await tick();
  resolve(state(5));await tick();assert.match(x.status(),/^0 incidencias/);
  x.api.initialize(x.user('new'));assert.match(x.status(),/^0 incidencias/);
  x.api.initialize(null);assert.equal(x.elements.find(x=>x.tag==='details').hidden,true);
});
test('unknown server evidence never presents zero errors as healthy',async()=>{
  const x=fixture(async()=>({ok:true,json:async()=>({available:false,scope:'account',incidents:[]})}));
  x.api.initialize(x.user('a'));await tick();assert.match(x.status(),/No se ha confirmado/);
  assert.doesNotMatch(x.status(),/^0/);
});
test('closed sidebar does not continually poll the global evidence store',async()=>{
  const x=fixture(async()=>state(5));x.api.initialize(x.user('a'));await tick();
  x.events.poll();x.events.focus();await tick();assert.equal(x.calls.length,1);
  const details=x.elements.find(e=>e.tag==='details');details.open=true;details.toggle();await tick();
  assert.equal(x.calls.length,2);x.events.poll();await tick();assert.equal(x.calls.length,2);
  x.sidebar.open=true;x.events.poll();await tick();assert.equal(x.calls.length,3);
  assert.match(x.status(),/400 eventos globales/);
});
