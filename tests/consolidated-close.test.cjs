const {test}=require('node:test');
const assert=require('node:assert/strict');
const fs=require('node:fs'),vm=require('node:vm');
const source=fs.readFileSync('static/app.js','utf8');
function setup({save=async()=>true,sync=async()=>{}}={}) {
 const state={user:{uid:'a'},authEpoch:1,profileDirty:true,bankEnabled:true,bankPending:true};
 const error={};let saves=0,syncs=0;
 const context={state,window:{},$:()=>error,saveProfileChangesWork:async()=>{saves++;const ok=await save();if(ok)state.profileDirty=false;return ok;},synchronizeBank:async()=>{syncs++;const result=await sync();state.bankPending=Boolean(result?.pending);}};
 vm.runInNewContext(source.slice(source.indexOf('let dataClosePromise = null;'),source.indexOf('\nasync function updateGoogleUser(user)')),context);
 return {state,error,close:()=>context.window.cvDataPanel.beforeClose(),counts:()=>[saves,syncs]};
}
test('double close shares persistence and synchronization',async()=>{
 let release;const gate=new Promise(r=>release=r);const x=setup({save:()=>gate});
 const first=x.close(),second=x.close();assert.equal(first,second);release(true);
 assert.equal(await first,true);assert.deepEqual(x.counts(),[1,1]);assert.equal(x.state.dataCloseStatus,'confirmed');
});
test('save failure preserves edits and retry recovers',async()=>{
 let works=false;const x=setup({save:async()=>works});assert.equal(await x.close(),false);
 assert.equal(x.state.profileDirty,true);assert.deepEqual(x.counts(),[1,0]);works=true;
 assert.equal(await x.close(),true);assert.deepEqual(x.counts(),[2,1]);
});
test('synchronization failure retains pending work and can recover',async()=>{
 let works=false;const x=setup({sync:async()=>{if(!works)throw Error('offline')}});
 assert.equal(await x.close(),false);assert.equal(x.state.bankPending,true);assert.equal(x.state.dataCloseStatus,'recoverable-error');
 works=true;assert.equal(await x.close(),true);assert.deepEqual(x.counts(),[1,2]);
});
test('account change during save never starts next account synchronization',async()=>{
 let release;const x=setup({save:()=>new Promise(r=>release=r)});const pending=x.close();
 x.state.user={uid:'b'};x.state.authEpoch++;release(true);assert.equal(await pending,false);assert.deepEqual(x.counts(),[1,0]);
});
test('no pending work avoids bank calls',async()=>{
 const x=setup();x.state.profileDirty=false;x.state.bankPending=false;assert.equal(await x.close(),true);assert.deepEqual(x.counts(),[0,0]);
});

test('pending background result keeps dialog close unconfirmed',async()=>{
 const x=setup({sync:async()=>({pending:2})});
 assert.equal(await x.close(),false);assert.equal(x.state.bankPending,true);
 assert.equal(x.state.dataCloseStatus,'recoverable-error');assert.match(x.error.textContent,/pendientes/);
});
test('manual save and close share the same PUT transaction',async()=>{
 let release,calls=0;
 const state={user:{uid:'a'},authEpoch:1,profileDirty:true,bankEnabled:false};
 const context={state,window:{},$:()=>({}),saveProfileChangesTransaction:async()=>{
   calls++;await new Promise(r=>release=r);state.profileDirty=false;return true;
 }};
 const wrapper=source.slice(source.indexOf('let saveProfilePromise = null;'),source.indexOf('async function saveProfileChangesTransaction()'));
 const close=source.slice(source.indexOf('let dataClosePromise = null;'),source.indexOf('\nasync function updateGoogleUser(user)'));
 vm.runInNewContext(wrapper+close,context);
 const manual=context.saveProfileChangesWork();
 const closing=context.window.cvDataPanel.beforeClose();
 assert.equal(calls,1);release();assert.equal(await manual,true);assert.equal(await closing,true);assert.equal(calls,1);
});
test('account change while token refresh prevents a bank request',async()=>{
 let release,requests=0;
 const state={bankEnabled:true,user:{uid:'a',getIdToken:()=>new Promise(r=>release=r)},authEpoch:1};
 const context={state,window:{cvBackground:{enabled:()=>false}},$:()=>({}),setBusy(){},requestJson:async()=>{requests++;return {pending:0}},renderBankStatus(){}};
 vm.runInNewContext(source.slice(source.indexOf('async function synchronizeBank('),source.indexOf('\nlet synchronizationRunning')),context);
 const pending=context.synchronizeBank();state.user={uid:'b'};state.authEpoch++;release('obsolete');
 await assert.rejects(pending,/cuenta cambió/);assert.equal(requests,0);assert.equal(state.idToken,undefined);
});
