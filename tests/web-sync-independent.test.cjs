const {test}=require('node:test');
const assert=require('node:assert/strict');
const vm=require('node:vm'),fs=require('node:fs');
const source=fs.readFileSync('static/app.js','utf8');
for(const telegram of [undefined,{synchronize(){throw Error('Telegram unavailable')},restore(){throw Error('Telegram unavailable')}}]){
 test(`web synchronization works with Telegram ${telegram?'failing':'absent'} and no Gmail`,async()=>{
  let click;const calls=[];const button={addEventListener:(type,handler)=>click=handler};
  const context=vm.createContext({window:{cvTelegram:telegram,cvDrive:{connect:async()=>calls.push('drive'),isConnected:()=>true},cvLoading:{run:async(label,work)=>work(()=>{})}},$:()=>button,state:{authRequired:true,user:{uid:'a'}},clearError(){},showError(message){throw Error(message)},synchronizeBank:async()=>calls.push('bank'),loadProfileSummaryWork:async()=>calls.push('profile')});
  context.requireSession=()=>true;
  vm.runInContext(source.slice(source.indexOf('let synchronizationRunning ='),source.indexOf('async function loadProfileSummary()')),context);
  await click();assert.deepEqual(calls,['drive','bank','profile']);assert.equal(button.disabled,false);
 });
}
test('Google popup starts synchronously without requesting a Telegram session',async()=>{
 let authorize,opened=false;
 const user={getIdToken:async()=>'id',reauthenticateWithPopup(){opened=true;return Promise.resolve({user,credential:{accessToken:'drive-token'}})}};
 const context=vm.createContext({state:{user},googleProvider:()=>({}),window:{cvDrive:{setAuthorizationHandler:fn=>authorize=fn},cvTelegram:{restore(){throw Error('Must not use Telegram')}}}});
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
