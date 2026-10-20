const {test}=require('node:test');
const assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm');
function setup(time){
 let signsOut=0,clears=0;const user={getIdTokenResult:async()=>({claims:{auth_time:time}})};
 const state={reauthenticateAfter:100,auth:{currentUser:user,signOut:async()=>{signsOut++;state.auth.currentUser=null}}};
 const context={state,updateGoogleUserWork:async value=>{assert.equal(value,null);clears++},showError(){}};
 const source=fs.readFileSync('static/app.js','utf8');vm.runInNewContext(source.slice(source.indexOf('async function enforceSessionPolicy('),source.indexOf('async function updateGoogleUser(')),context);
 return {context,state,user,counts:()=>({signsOut,clears})};
}
test('restored old sessions sign out and clear private UI without touching browser storage',async()=>{
 const q=setup(99);assert.equal(await q.context.enforceSessionPolicy(q.user),true);assert.deepEqual(q.counts(),{signsOut:1,clears:1});
});
test('new sign-ins remain active and the cutoff does not cause a logout loop',async()=>{
 for(const time of [100,101]){const q=setup(time);assert.equal(await q.context.enforceSessionPolicy(q.user),false);assert.deepEqual(q.counts(),{signsOut:0,clears:0});}
});
test('a delayed old-token check never signs out a different current user',async()=>{
 const q=setup(99);q.state.auth.currentUser={};assert.equal(await q.context.enforceSessionPolicy(q.user),true);assert.deepEqual(q.counts(),{signsOut:0,clears:0});
});
test('signed-out users and installations without a cutoff do not request credentials',async()=>{
 const q=setup(99);assert.equal(await q.context.enforceSessionPolicy(null),false);q.state.reauthenticateAfter=0;assert.equal(await q.context.enforceSessionPolicy(q.user),false);assert.deepEqual(q.counts(),{signsOut:0,clears:0});
});
