const {test}=require('node:test');
const assert=require('node:assert/strict');
const fs=require('node:fs'),vm=require('node:vm');
const {parseHTML}=require('linkedom');
const builder=require('../generate_functional_map.cjs');
test('inventory resolves root, initial guards, handlers and conservative API relationships',()=>{
 const map=builder.discover();assert.equal(map.pages.some(p=>p.path==='/'),true);
 assert.equal(map.pages.some(p=>p.path.includes('admin-')),false);
 const sync=map.controls.find(c=>c.key==='/::#sync-bank');
 assert.equal(sync.initialDisabled,true);assert.ok(sync.handlers.some(h=>h.endpoints.includes('/api/bank/sync')));
 assert.ok(sync.guards.length);assert.equal(new Set(map.controls.map(c=>c.key)).size,map.controls.length);
 assert.equal(map.controls.some(c=>c.page.startsWith('//')),false);
 const history=map.controls.find(c=>c.id==='refresh-application-history');
 assert.ok(history.handlers[0].endpoints.includes('/api/applications'));
 assert.ok(history.handlers[0].loading.includes('window.cvLoading.start'));
 assert.deepEqual(history.handlers[0].loadingLabels,['Cargando historial de envío']);
});
test('version diff distinguishes additions removals and changed semantics',()=>{
 const before={controls:[{key:'a',fingerprint:'1'},{key:'b',fingerprint:'1'}]};
 const after={controls:[{key:'a',fingerprint:'2'},{key:'c',fingerprint:'1'}]};
 const changes=builder.diff(before,after);
 assert.deepEqual(changes.added.map(c=>c.key),['c']);assert.deepEqual(changes.removed.map(c=>c.key),['b']);assert.deepEqual(changes.changed.map(c=>c.key),['a']);
});
test('same-source repeated predeploy preserves baseline and previous release',()=>{
 const first=builder.build(null,null,'first');
 const second=builder.build(first,{sourceHash:'wrong',passed:true},'second');
 assert.equal(second.baseline.buildId,'first');assert.equal(second.previous.buildId,'first');assert.equal(second.tests.passed,null);
 const third=builder.build(second,{sourceHash:second.current.sourceHash,passed:true},'third');
 assert.equal(third.previous.buildId,'first');assert.equal(third.tests.passed,true);
});
test('URLs omit queries and external paths',()=>{
 assert.equal(builder.safeTarget('/api/job?token=private'),'/api/job');
 assert.equal(builder.safeTarget('https://example.test/private?token=fixture'),'https://example.test');
});
function telemetry({enabled=true,foreign=false}={}){
 const {window}=parseHTML('<html><body><button id="generate" disabled>Private CV name</button><input id="profile" value="private-profile"></body></html>');
 const messages=[],listeners={},document=window.document;
 const parent={closed:false,location:{origin:foreign?'https://foreign.test':'https://app.test'},postMessage:data=>messages.push(data)};
 const location={origin:'https://app.test',href:'https://app.test/?cv-observe=1',pathname:'/',search:enabled?'?cv-observe=1':''};
 let fetches=0;const original=()=>{fetches++;return Promise.resolve({status:200,json:async()=>({current:{controls:[]}})});};
 const browser={opener:parent,fetch:original,addEventListener:(event,fn)=>{listeners[event]=fn;}};
 const ctx={window:browser,location,document,URL,URLSearchParams,MutationObserver:class{observe(){}disconnect(){}},getComputedStyle:()=>({display:'block',visibility:'visible'}),setTimeout(){},clearTimeout(){}};
 // linkedom has no layout; the fixture supplies only visibility geometry.
 for(const element of document.querySelectorAll('*'))element.getClientRects=()=>[{}];
 vm.runInNewContext(fs.readFileSync('static/functional-telemetry.js','utf8'),ctx);
 return {browser,original,messages,listeners,parent,fetches:()=>fetches};
}
test('telemetry is completely dormant without opt-in or with foreign opener',()=>{
 for(const options of [{enabled:false},{foreign:true}]){const fixture=telemetry(options);assert.equal(fixture.browser.fetch,fixture.original);assert.equal(fixture.messages.length,0);assert.equal(fixture.fetches(),0);}
});
test('observer reports boolean availability but no field values or labels; stop requires same origin and source',async()=>{
 const fixture=telemetry();assert.equal(fixture.messages[0].type,'snapshot');
 const serialized=JSON.stringify(fixture.messages);assert.doesNotMatch(serialized,/private-profile|Private CV name/);
 assert.equal(fixture.messages[0].controls[0].disabled,true);
 fixture.listeners.message({origin:'https://foreign.test',source:fixture.parent,data:{channel:'cv-functional-stop'}});
 assert.notEqual(fixture.browser.fetch,fixture.original);
 await fixture.browser.fetch('/api/private/user@example.test?token=secret');await new Promise(r=>setImmediate(r));
 const http=fixture.messages.find(m=>m.type==='http');assert.equal(http.target,'/ruta-no-inventariada');assert.doesNotMatch(JSON.stringify(fixture.messages),/secret|user@example/);
 fixture.listeners.message({origin:'https://app.test',source:fixture.parent,data:{channel:'cv-functional-stop'}});
 assert.equal(fixture.browser.fetch,fixture.original);
});
