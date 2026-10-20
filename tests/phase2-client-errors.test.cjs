const {test}=require('node:test');
const assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm');
function setup(){
 const nodes=new Map();
 const document={querySelector:key=>{if(!nodes.has(key))nodes.set(key,{textContent:'',value:'DATOS SIN GUARDAR',addEventListener(){}});return nodes.get(key)}};
 const context={window:{cvLoading:{start:()=>()=>{}},dispatchEvent(){}},document,Date,Promise,Event,
  CustomEvent:class{constructor(type,options){this.type=type;this.detail=options.detail}}};
 vm.runInNewContext(fs.readFileSync('static/drive.js','utf8'),context);
 return {context,drive:context.window.cvDrive,nodes};
}
test('gateway HTML, empty and missing error bodies retain HTTP and correlation without claiming a folder failure',async()=>{
 for(const multi of [false,true]) for(const status of [502,504]) for(const body of ['html','empty','missing','null']){
  const q=setup();q.context.fetch=async()=>({ok:false,status,headers:{get:()=> 'b'.repeat(32)},json:async()=>{
   if(body==='html'||body==='empty')throw Error('PRIVATE TOKEN CV');return body==='null'?null:{private:'PRIVATE TOKEN CV'};
  }});
  await q.drive.initialize({provider:'drive',multi_account:multi},()=>({}));
  await assert.rejects(q.drive.acceptCredential('fixture'),error=>{
   assert.equal(error.status,status);assert.equal(error.correlationId,'b'.repeat(32));
   assert.equal(error.stage,multi?'drive-prepare':'drive-access-check');
   assert.doesNotMatch(error.message,/No se pudo comprobar la carpeta|PRIVATE|TOKEN|CV$/);
   assert.match(error.message,new RegExp(`HTTP ${status}`));return true;
  });
 }
});
test('busy account offers explicit retry, preserves input and does not revoke authorization or replay',async()=>{
 const q=setup();let calls=0;
 q.context.fetch=async()=>{calls++;return {ok:false,status:409,json:async()=>({code:'account_write_busy',error:'PRIVATE TOKEN CV'})}};
 await q.drive.initialize({provider:'drive',multi_account:true},()=>({}));
 q.nodes.set('#job-text',{value:'MI BORRADOR'});
 await assert.rejects(q.drive.acceptCredential('fixture'),error=>error.code==='account_write_busy'&&error.retryable===true&&/Reintenta/.test(error.message)&&!error.message.includes('PRIVATE'));
 assert.equal(q.nodes.get('#job-text').value,'MI BORRADOR');assert.equal(calls,1);
 assert.equal(q.drive.headersIfConnected()['X-Drive-Access-Token'],'fixture');
});
test('only confirmed expiry invalidates the credential across the unified client contract',async()=>{
 for(const code of ['drive_access_undetermined','drive_folder_permission','google_permissions_missing','google_authorization_expired']){
  const q=setup();q.context.fetch=async()=>({ok:false,status:403,json:async()=>({code})});
  await q.drive.initialize({provider:'drive',multi_account:true},()=>({}));
  await assert.rejects(q.drive.acceptCredential('fixture'));
  assert.equal(Boolean(q.drive.headersIfConnected()['X-Drive-Access-Token']),code!=='google_authorization_expired');
 }
});
