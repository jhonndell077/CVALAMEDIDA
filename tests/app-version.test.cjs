const {test}=require('node:test');
const assert=require('node:assert/strict');
const fs=require('node:fs');
const vm=require('node:vm');
const code=fs.readFileSync('static/app-version.js','utf8');
function fixture({loaded='v1',previous=null,latest='v1',storageFails=false}={}) {
 const listeners={}; const nodes=[]; const values=new Map(previous?[['cv-acknowledged-build',previous]]:[]);
 let interval, replacement, loading=false, fail=false, requests=0;
 const element=tag=>({tag,children:[],events:{},setAttribute(){},append(...children){this.children.push(...children);},addEventListener(name,callback){this.events[name]=callback;}});
 const document={hidden:false,querySelector:()=>({content:loaded}),createElement:element,addEventListener:(name,cb)=>{listeners[name]=cb;},body:{append:node=>nodes.push(node),classList:{contains:()=>loading}}};
 const window={location:{href:'https://example.com/?test=1',replace:url=>{replacement=url;}},setInterval:(cb,ms)=>{assert.equal(ms,60000);interval=cb;},addEventListener:(name,cb)=>{listeners[name]=cb;}};
 const localStorage={getItem:key=>{if(storageFails)throw Error();return values.get(key)||null;},setItem:(key,value)=>{if(storageFails)throw Error();values.set(key,value);}};
 vm.runInNewContext(code,{window,document,localStorage,URL,Date,fetch:async(url,opts)=>{requests++;assert.equal(opts.cache,'no-store');if(fail)throw Error('offline');return {ok:true,json:async()=>({buildId:latest})};}});
 return {nodes,values,listeners,check:()=>interval(),setLatest:v=>{latest=v;},loading:v=>{loading=v;},offline:()=>{fail=true;},replacement:()=>replacement,requests:()=>requests};
}
const flush=()=>new Promise(resolve=>setImmediate(resolve));
test('first visit and unchanged version do not announce an update',async()=>{const f=fixture();await flush();assert.equal(f.nodes.length,0);assert.equal(f.values.get('cv-acknowledged-build'),'v1');await f.check();assert.equal(f.nodes.length,0);});
test('new deployment produces one banner, preserves page until explicit click',async()=>{const f=fixture();await flush();f.setLatest('v2');await f.check();await f.check();assert.equal(f.nodes.length,1);assert.equal(f.nodes[0].children[0].children[0].textContent,'Nueva actualización disponible');assert.equal(f.replacement(),undefined);const button=f.nodes[0].children[1];f.loading(true);button.events.click();assert.equal(f.replacement(),undefined);f.loading(false);button.events.click();assert.equal(new URL(f.replacement()).searchParams.get('cv_v'),'v2');assert.equal(f.values.get('cv-acknowledged-build'),'v2');});
test('newly opened page announces changed version once per accepted version',async()=>{const f=fixture({loaded:'v2',previous:'v1',latest:'v2'});await flush();assert.equal(f.nodes.length,1);const accepted=fixture({loaded:'v2',previous:'v2',latest:'v2'});await flush();assert.equal(accepted.nodes.length,0);});
test('another tab acknowledgment never masks this tab’s stale loaded code',async()=>{const f=fixture({loaded:'v1',previous:'v2',latest:'v2'});await flush();assert.equal(f.nodes.length,1);assert.equal(f.nodes[0].children[1].textContent,'Actualizar');});
test('offline checks, hidden tabs, invalid versions and blocked storage are harmless',async()=>{const f=fixture({storageFails:true});await flush();f.offline();await f.check();assert.equal(f.nodes.length,0);const invalid=fixture({latest:'<bad>'});await flush();assert.equal(invalid.nodes.length,0);});
