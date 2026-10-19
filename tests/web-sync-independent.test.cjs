const {test}=require('node:test');
const assert=require('node:assert/strict');
const vm=require('node:vm'),fs=require('node:fs');
const crypto=require('node:crypto').webcrypto;
const source=fs.readFileSync('static/app.js','utf8');
for(const telegram of [undefined,{synchronize(){throw Error('Telegram unavailable')},restore(){throw Error('Telegram unavailable')}}]){
 test(`web synchronization verifies Google on server with Telegram ${telegram?'failing':'absent'}`,async()=>{
  let click;const calls=[];const button={addEventListener:(type,handler)=>click=handler};
  const context=vm.createContext({crypto,window:{cvTelegram:telegram,cvDrive:{connect:async()=>calls.push('drive'),isConnected:()=>true,headers:()=>({})},cvLoading:{run:async(label,work)=>work(()=>{})}},$:()=>button,state:{authRequired:true,user:{uid:'a'}},clearError(){},showError(message){throw Error(message)},directRequestJson:async path=>{assert.equal(path,'/api/account/connections/verify');calls.push('verify');return {ok:true};},synchronizeBank:async()=>{calls.push('bank');return {pending:0};},loadProfileSummaryWork:async()=>calls.push('profile')});
  context.requireSession=()=>true;
  vm.runInContext(source.slice(source.indexOf('let synchronizationRunning ='),source.indexOf('async function loadProfileSummary()')),context);
  await click();assert.deepEqual(calls,['drive','verify','bank','profile']);assert.equal(button.disabled,false);
 });
}
test('Google popup starts synchronously without requesting a Telegram session',async()=>{
 let authorize,opened=false;
 const user={uid:'fixture',getIdToken:async()=>'id',reauthenticateWithPopup(){opened=true;return Promise.resolve({user,credential:{accessToken:'drive-token'}})}};
 const context=vm.createContext({state:{user},verifiedGoogleCredential:async token=>({access_token:token,scope:'https://www.googleapis.com/auth/drive.file'}),googleProvider:()=>({}),window:{cvDrive:{setAuthorizationHandler:fn=>authorize=fn},cvTelegram:{restore(){throw Error('Must not use Telegram')}}}});
 vm.runInContext(source.slice(source.indexOf('  window.cvDrive.setAuthorizationHandler('),source.indexOf('  state.auth.onIdTokenChanged')),context);
 const promise=authorize();assert.equal(opened,true);assert.equal((await promise).access_token,'drive-token');
});
test('automatic folder setup needs neither Picker scripts nor installed apps',async()=>{
 const elements=new Map();let path;
 const context=vm.createContext({window:{cvLoading:{start:()=>()=>{}},dispatchEvent(){}},document:{querySelector:id=>{if(!elements.has(id))elements.set(id,{addEventListener(){}});return elements.get(id)},head:{append(){throw Error('Picker must not load')}},createElement(){throw Error('No scripts needed')}},Event,CustomEvent:class {},fetch:async url=>{path=url;return {ok:true,json:async()=>({bank_id:'bank',archive_id:'archive'})}}});
 vm.runInContext(fs.readFileSync('static/drive.js','utf8'),context);
 const drive=context.window.cvDrive;await drive.initialize({provider:'drive',multi_account:true},()=>({}));
 drive.setAuthorizationHandler(async()=>({access_token:'token'}));await drive.connect();
 assert.equal(path,'/api/account/setup');assert.equal(drive.isConnected(),true);
});


test('sync starts authorization before loading UI and shares one operation for repeated taps',async()=>{
 let click,resolve;const calls=[];const button={addEventListener:(_,fn)=>click=fn};
 let oauthId,verifiedId,syncId;
 const context=vm.createContext({crypto,state:{user:{uid:'a'},authEpoch:1},window:{cvDrive:{connect(options){oauthId=options.operationId;assert.equal(options.requireGmail,true);calls.push('oauth');return new Promise(done=>resolve=done)},isConnected:()=>true,headers:()=>({})},cvLoading:{run:async(_,work)=>{calls.push('loading');return work(()=>{})}}},$:()=>button,requireSession:()=>true,clearError(){},showError:assert.fail,directRequestJson:async(_,payload,headers)=>{verifiedId=headers['X-CV-Operation-ID'];calls.push('verify');return {ok:true};},synchronizeBank:async(_,id)=>{syncId=id;calls.push('bank');return {pending:0};},loadProfileSummaryWork:async()=>{}});
 vm.runInContext(source.slice(source.indexOf('let synchronizationRunning ='),source.indexOf('async function loadProfileSummary()')),context);
 const operation=context.window.cvSynchronizeBank();assert.deepEqual(calls,['oauth','loading']);
 await click();assert.deepEqual(calls,['oauth','loading']);resolve();await operation;
 assert.deepEqual(calls,['oauth','loading','verify','bank']);assert.equal(button.disabled,false);
 assert.equal(oauthId,verifiedId);assert.equal(verifiedId,syncId);
});

for(const failure of ['access','bank-warning','account-change']) {
 test(`synchronization never reports complete after ${failure}`,async()=>{
  const calls=[],errors=[],button={addEventListener(){}};
  const state={user:{uid:'a'},authEpoch:1};
  const context=vm.createContext({crypto,state,$:()=>button,requireSession:()=>true,clearError(){},showError:message=>errors.push(message),
   window:{cvDrive:{connect:async()=>{},isConnected:()=>true,headers:()=>({})},cvLoading:{run:async(_,work)=>work((percent)=>calls.push(percent))}},
   directRequestJson:async()=>{if(failure==='access')throw Error('Permiso revocado');return {ok:true};},
   synchronizeBank:async()=>{calls.push('bank');if(failure==='account-change'){state.user={uid:'b'};state.authEpoch++;}return {pending:0,warnings:failure==='bank-warning'?[{}]:[]};},
   loadProfileSummaryWork:async()=>calls.push('profile')});
  vm.runInContext(source.slice(source.indexOf('let synchronizationRunning ='),source.indexOf('async function loadProfileSummary()')),context);
  await assert.rejects(context.window.cvSynchronizeBank({throwOnError:true}));
  assert.equal(calls.includes(99),false);assert.equal(calls.includes('profile'),false);
  if(failure==='access')assert.equal(calls.includes('bank'),false);
  if(failure==='account-change')assert.deepEqual(errors,[]);
 });
}

test('new account can synchronize while previous account authorization is pending',async()=>{
 const state={user:{uid:'a'},authEpoch:1},pending=[],button={addEventListener(){}};let verifications=0;
 const context=vm.createContext({crypto,state,$:()=>button,requireSession:()=>true,clearError(){},showError:assert.fail,
  window:{cvDrive:{connect:()=>new Promise(resolve=>pending.push(resolve)),isConnected:()=>true,headers:()=>({})},cvLoading:{run:async(_,work)=>work(()=>{})}},
  directRequestJson:async()=>{verifications++;return {ok:true};},synchronizeBank:async()=>({pending:0}),loadProfileSummaryWork:async()=>{}});
 vm.runInContext(source.slice(source.indexOf('let synchronizationRunning ='),source.indexOf('async function loadProfileSummary()')),context);
 const first=context.window.cvSynchronizeBank();
 state.user={uid:'b'};state.authEpoch++;
 const second=context.window.cvSynchronizeBank();assert.equal(pending.length,2);
 pending[0]();await first;
 const duplicate=context.window.cvSynchronizeBank();await duplicate;assert.equal(pending.length,2);
 pending[1]();await second;assert.equal(verifications,1);
});

test('local mode rechecks Drive without claiming Firebase or Gmail verification',async()=>{
 const calls=[],button={addEventListener(){}};
 const context=vm.createContext({crypto,state:{authRequired:false,user:null},$:()=>button,requireSession:()=>true,clearError(){},showError:assert.fail,
  window:{cvDrive:{connect:async options=>{assert.equal(options.requireGmail,false);},isConnected:()=>true,verify:async()=>calls.push('drive')},cvLoading:{run:async(_,work)=>work(()=>{})}},
  directRequestJson:async()=>assert.fail('No account endpoint in unauthenticated local mode'),
  synchronizeBank:async()=>{calls.push('bank');return {pending:0};},loadProfileSummaryWork:async()=>{}});
 vm.runInContext(source.slice(source.indexOf('let synchronizationRunning ='),source.indexOf('async function loadProfileSummary()')),context);
 await context.window.cvSynchronizeBank();assert.deepEqual(calls,['drive','bank']);
});

for (const scenario of ['notice','blocking','legacy','save-failure']) test(`sync applies bank review policy and initial verification: ${scenario}`,async()=>{
 const calls=[],button={addEventListener(){}};
 const warning={severity:scenario==='notice'?'notice':scenario==='legacy'?undefined:'blocking',message:'fixture'};
 const state={authRequired:true,multiAccount:true,user:{uid:'a'},authEpoch:1};
 const context=vm.createContext({crypto,state,$:()=>button,requireSession:()=>true,clearError(){},showError(){},
  window:{cvDrive:{connect:async()=>{},isConnected:()=>true,headers:()=>({})},cvLoading:{run:async(_,work)=>work(()=>{})},cvRequiredSync:{ready:()=>false,account:status=>{assert.equal(status.initial_sync_completed,true);calls.push('unlock');}}},
  directRequestJson:async path=>{calls.push(path);if(path==='/api/account/initial-sync'){if(scenario==='save-failure')throw Error('No se pudo guardar');return {completed:true};}return {ok:true};},
  synchronizeBank:async()=>({pending:0,warnings:scenario==='save-failure'?[]:[warning],sync:{state:['notice','save-failure'].includes(scenario)?'ready':'blocked'}}),loadProfileSummaryWork:async()=>{}});
 vm.runInContext(source.slice(source.indexOf('let synchronizationRunning ='),source.indexOf('async function loadProfileSummary()')),context);
 if(scenario==='notice') {assert.equal((await context.window.cvSynchronizeBank({throwOnError:true})).completed,true);assert.ok(calls.includes('unlock'));}
 else {await assert.rejects(context.window.cvSynchronizeBank({throwOnError:true}));assert.equal(calls.includes('unlock'),false);}
 if(scenario==='save-failure')assert.ok(calls.includes('/api/account/initial-sync'));
});
