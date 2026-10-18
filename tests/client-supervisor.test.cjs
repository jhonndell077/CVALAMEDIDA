const {test}=require('node:test'),assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm');
const source=fs.readFileSync('static/client-supervisor.js','utf8');
const tick=()=>new Promise(r=>setImmediate(r));
function setup(fetcher){const calls=[],events={};let n=0;const window={addEventListener:(name,handler)=>events[name]=handler};vm.runInNewContext(source,{window,AbortSignal,Date,Set,crypto:{randomUUID:()=> (++n).toString(16).padStart(32,'0')},fetch:async(...args)=>{calls.push(args);return fetcher?fetcher(...args):{ok:true}}});return {api:window.cvClientSupervisor,calls,events,user:uid=>({uid,getIdToken:async()=>uid})};}
const signal={service:'drive-api',stage:'oauth-authorization',code:'popup_failed_to_open',operationId:'a'.repeat(32)};
test('browser signals never send UID, token detail, raw errors or provider confirmation',async()=>{const x=setup();x.api.initialize(x.user('account-one'));x.api.report({...signal,uid:'other',email:'private',token:'secret',error:'raw'});await tick();assert.equal(x.calls.length,1);const payload=JSON.parse(x.calls[0][1].body);assert.deepEqual(payload,{component:'google',service:'drive-api',stage:'oauth-authorization',result:'error',code:'popup_failed_to_open'});assert.equal(x.calls[0][1].headers['X-CV-Operation-ID'],'a'.repeat(32));assert.doesNotMatch(x.calls[0][1].body,/account-one|other|private|secret|raw|confirmed/);});
test('offline browser signals retry on online without polling and deduplicate',async()=>{let online=false;const x=setup(async()=>{if(!online)throw Error('offline');return {ok:true}});x.api.initialize(x.user('a'));x.api.report(signal);await tick();assert.equal(x.calls.length,1);x.api.report(signal);await tick();assert.equal(x.calls.length,1);online=true;x.events.online();await tick();assert.equal(x.calls.length,2);x.events.online();await tick();assert.equal(x.calls.length,2);});
test('switching accounts discards offline reports and stale token callbacks',async()=>{let done;const x=setup();x.api.initialize({uid:'old',getIdToken:()=>new Promise(r=>done=r)});x.api.report(signal);x.api.initialize(x.user('new'));done('old-token');await tick();assert.equal(x.calls.length,0);x.events.online();await tick();assert.equal(x.calls.length,0);});
test('network telemetry only identifies fixed components and safe codes',async()=>{const x=setup();x.api.initialize(x.user('a'));x.api.network('/api/profile?private=secret',Error('sensitive data'),'b'.repeat(32));await tick();const payload=JSON.parse(x.calls[0][1].body);assert.equal(payload.component,'bank');assert.equal(payload.code,'network_error');assert.equal(payload.stage,'browser-request');assert.doesNotMatch(x.calls[0][1].body,/secret|sensitive|private/);x.api.network('/api/diagnostics/client',Error('offline'));await tick();assert.equal(x.calls.length,1);});
test('unrecognized signals and signed-out errors never queue for another account',async()=>{const x=setup();x.api.report(signal);x.api.initialize(x.user('a'));x.api.report({...signal,code:'sensitive'});x.events.online();await tick();assert.equal(x.calls.length,0);});


test('queue saturation during a pending request never removes an unsent successor',async()=>{
 let finish;const x=setup(async()=>x.calls.length===1?new Promise(r=>finish=r):{ok:true});
 x.api.initialize(x.user('a'));x.api.report({...signal,operationId:'1'.padStart(32,'0')});await tick();
 for(let i=2;i<=13;i++)x.api.report({...signal,operationId:i.toString(16).padStart(32,'0')});
 finish({ok:true});await tick();
 assert.equal(x.calls.length,13);assert.deepEqual(x.calls.map(c=>parseInt(c[1].headers['X-CV-Operation-ID'],16)),Array.from({length:13},(_,i)=>i+1));
});
test('account switch during report fetch cannot consume the new account queue',async()=>{
 let finish;const x=setup(async()=>x.calls.length===1?new Promise(r=>finish=r):{ok:true});
 x.api.initialize(x.user('old'));x.api.report(signal);await tick();
 x.api.initialize(x.user('new'));x.api.report({...signal,operationId:'b'.repeat(32)});
 finish({ok:true});await tick();assert.equal(x.calls.length,2);
 assert.equal(x.calls[1][1].headers.Authorization,'Bearer new');assert.equal(x.calls[1][1].headers['X-CV-Operation-ID'],'b'.repeat(32));
});
