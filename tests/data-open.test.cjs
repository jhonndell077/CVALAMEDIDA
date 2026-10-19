const {test}=require('node:test');
const assert=require('node:assert/strict');
const fs=require('node:fs'),vm=require('node:vm');
const source=fs.readFileSync('static/app.js','utf8');
function setup({connected=true,profile=null,load=async()=>{}}={}) {
 const state={authRequired:true,user:{uid:'a'},authEpoch:1,bankEnabled:true,profileDraft:profile};
 const panel={hidden:!profile};let loads=0,syncs=0,logins=0,options;
 const context={state,Promise,$:id=>id==='#profile-panel'?panel:{click(){logins++}},window:{cvDrive:{isConnected:()=>connected}},loadProfileSummaryWork:()=>{loads++;return load()},startBankSynchronization:async args=>{options=args;syncs++}};
 vm.runInNewContext(source.slice(source.indexOf('let dataOpenOperation = null;'),source.indexOf('// A single close transaction')),context);
 return {state,panel,open:()=>context.openDataProfile(),counts:()=>({loads,syncs,logins}),options:()=>options};
}
test('Datos with connected Drive loads profile without synchronization',async()=>{const x=setup();await x.open();assert.deepEqual(x.counts(),{loads:1,syncs:0,logins:0});});
test('Datos with disconnected Drive starts authorization and inline synchronization',async()=>{const x=setup({connected:false});await x.open();assert.deepEqual(x.counts(),{loads:0,syncs:1,logins:0});assert.equal(x.options().inline,true);assert.equal(x.options().throwOnError,true);});
test('Datos preserves loaded edits instead of reloading the profile',async()=>{const x=setup({profile:{candidate:{name:'unsaved'}}});await x.open();assert.equal(x.counts().loads,0);});
test('duplicate open joins loading and a rejected request can be retried',async()=>{let reject;const x=setup({load:()=>new Promise((resolve,r)=>reject=r)});const a=x.open(),b=x.open();assert.equal(a,b);reject(Error('offline'));await assert.rejects(a,/offline/);assert.equal(x.counts().loads,1);const c=x.open();reject(Error('retry'));await assert.rejects(c,/retry/);assert.equal(x.counts().loads,2);});
test('new account never joins the previous account request',async()=>{let releases=[];const x=setup({load:()=>new Promise(r=>releases.push(r))});const a=x.open();x.state.user={uid:'b'};x.state.authEpoch++;const b=x.open();assert.notEqual(a,b);releases.forEach(r=>r());await Promise.all([a,b]);assert.equal(x.counts().loads,2);});
test('guest starts sign-in without loading a protected profile',async()=>{const x=setup();x.state.user=null;await assert.rejects(x.open(),/inicio de sesión/);assert.deepEqual(x.counts(),{loads:0,syncs:0,logins:1});});


test('inline synchronization authorizes once, joins concurrent opens and does not overlay Datos',async()=>{
 let release,connects=0,profiles=0;const gate=new Promise(r=>release=r);
 const state={user:{uid:'a'},authEpoch:1,authRequired:true,multiAccount:false};
 const node={disabled:false};
 const context={state,Promise,crypto:{randomUUID:()=> 'local-operation'},$:()=>node,
 requireSession(){throw Error('Must not close Datos while the identity token initializes')},clearError(){},showError(){throw Error('No global error overlay')},
 directRequestJson:async()=>({ok:true}),synchronizeBank:async()=>({}),loadProfileSummaryWork:async()=>profiles++,
 window:{cvDrive:{connect(){connects++;return gate},isConnected:()=>true,headers:()=>({})},cvLoading:{run(){throw Error('No loading overlay')}},cvOnboarding:{check(){throw Error('No onboarding overlay')}}}};
 vm.runInNewContext(source.slice(source.indexOf('let synchronizationRunning = false;'),source.indexOf('window.cvSynchronizeBank =')),context);
 const a=context.startBankSynchronization({inline:true,throwOnError:true});const b=context.startBankSynchronization({inline:true,throwOnError:true});
 release();await Promise.all([a,b]);assert.equal(connects,1);assert.equal(profiles,1);assert.equal(node.disabled,false);
});
