const {test}=require('node:test');
const assert=require('node:assert/strict');
const fs=require('node:fs'),vm=require('node:vm');
const source=fs.readFileSync('static/app.js','utf8');
function setup(state={}) {
  const elements=new Map();
  const $=id=>{if(!elements.has(id))elements.set(id,{disabled:false,focus(){this.focused=true},scrollIntoView(){},click(){this.clicked=true}});return elements.get(id)};
  const context=vm.createContext({window:{},state,$,busyButtons:new WeakMap(),showError:message=>context.error=message});
  vm.runInContext(source.slice(source.indexOf('function updateAnalyzeButton()'),source.indexOf('async function loadModels(')),context);
  return {context,$};
}
test('another device can click Analyze and gets an actionable sign-in message',()=>{
  const {context,$}=setup({authRequired:true,modelAvailable:true,user:null,idToken:null});
  context.updateAnalyzeButton();assert.equal($('#analyze-button').disabled,false);
  assert.equal(context.requireSession('analizar una vacante'),false);
  assert.match(context.error,/en este dispositivo/);assert.equal($('#auth-panel').hidden,false);
  assert.equal($('#google-sign-in').focused,true);
});
test('signed-in and local actions proceed while token renewal keeps busy analysis disabled',()=>{
  const {context,$}=setup({authRequired:true,modelAvailable:true,user:{uid:'alice'},idToken:'fixture'});
  assert.equal(context.requireSession('sincronizar'),true);
  context.busyButtons.set($('#analyze-button'),{});context.updateAnalyzeButton();
  assert.equal($('#analyze-button').disabled,true);
  context.busyButtons.delete($('#analyze-button'));context.updateAnalyzeButton();assert.equal($('#analyze-button').disabled,false);
  context.state.authRequired=false;context.state.user=null;context.state.idToken=null;
  assert.equal(context.requireSession('sincronizar'),true);
});
test('sync without session never opens OAuth or starts a backend operation',async()=>{
  const {context,$}=setup({authRequired:true,user:null,idToken:null});let click;
  $('#sync-bank').addEventListener=(_,handler)=>click=handler;
  vm.runInContext(source.slice(source.indexOf('let synchronizationRunning ='),source.indexOf('async function loadProfileSummary()')),context);
  await click();assert.match(context.error,/sincronizar tu banco/);assert.equal($('#sync-bank').disabled,false);
});
test('a late token from a previous account cannot replace the active token',async()=>{
  let resolve;const alice={uid:'alice',getIdToken:()=>new Promise(done=>resolve=done)};
  const bob={uid:'bob'};const {context}=setup({user:null,activeUserId:null});
  context.state.activeUserId='alice';
  vm.runInContext(source.slice(source.indexOf('async function updateGoogleUserWork('),source.indexOf('async function initializeGoogleAuth(')),context);
  const pending=context.updateGoogleUserWork(alice);context.state.user=bob;context.state.idToken='bob-token';
  resolve('alice-token');await pending;assert.equal(context.state.idToken,'bob-token');
});

test('an account switch during token refresh prevents the request from being sent',async()=>{
  let resolve;const {context}=setup({user:{uid:'alice',getIdToken:()=>new Promise(done=>resolve=done)},idToken:'old'});
  context.fetch=()=>{throw Error('Request must not be sent')};
  vm.runInContext(source.slice(source.indexOf('async function directRequestJson('),source.indexOf('async function processFetch(')),context);
  const pending=context.directRequestJson('/api/analyze',{});
  context.state.user={uid:'bob'};context.state.idToken='bob-token';resolve('alice-token');
  await assert.rejects(pending,/La cuenta cambió/);assert.equal(context.state.idToken,'bob-token');
});

test('failed sign-in SDK loading cannot prevent model setup and offers retry',async()=>{
  const {context,$}=setup();let loaded=false;
  context.document={querySelector:()=>null};context.window={location:{}};
  context.AbortSignal=AbortSignal;context.authenticatedHeaders=()=>({});
  context.fetch=async()=>({ok:true,json:async()=>({auth_required:true,models:[],bank:{},archive:{}})});
  context.loadModels=()=>{loaded=true};context.window.cvDrive={initialize:async()=>{}};
  context.initializeGoogleAuth=async()=>{throw Error('SDK blocked')};
  $('#retry-bootstrap').addEventListener=()=>{};
  vm.runInContext(source.slice(source.indexOf('async function bootstrap()'),source.indexOf('function fileToBase64(')),context);
  await context.bootstrap();assert.equal(loaded,true);assert.equal($('#retry-bootstrap').hidden,false);assert.equal(context.error,'SDK blocked');
});

test('a stalled Firebase script times out and releases startup for retry',async()=>{
  let timeout;const script={remove(){this.removed=true}};
  const context=vm.createContext({document:{createElement:()=>script,head:{append(){}}},setTimeout:fn=>{timeout=fn},clearTimeout(){}});
  vm.runInContext(source.slice(source.indexOf('function loadScript('),source.indexOf('function renderBankStatus(')),context);
  const pending=context.loadScript('/fixture.js');timeout();await assert.rejects(pending,/Reintentar inicio/);assert.equal(script.removed,true);
});


test('same-account token renewal does not restart bank loading during synchronization',async()=>{
 const user={uid:'alice',getIdToken:async()=> 'renewed-local-token'};
 const {context}=setup({user,activeUserId:'alice',authEpoch:1});
 context.synchronizationRunning={owner:'alice',epoch:1};
 context.window.cvBackground={initialize(){throw Error('Duplicate initialization during bank sync')}};
 vm.runInContext(source.slice(source.indexOf('async function updateGoogleUserWork('),source.indexOf('async function initializeGoogleAuth(')),context);
 await context.updateGoogleUserWork(user);
 assert.equal(context.state.idToken,'renewed-local-token');assert.equal(context.state.user,user);
});
