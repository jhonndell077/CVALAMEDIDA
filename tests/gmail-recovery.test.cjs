const {test}=require('node:test');
const assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm');
function fixture(){
 const elements=new Map();const $=id=>{if(!elements.has(id))elements.set(id,{value:'',textContent:'',hidden:true,addEventListener(){}});return elements.get(id)};
 const state={pdf:{id:'fixture'},user:{uid:'fixture',getIdToken:async()=> 'synthetic'},authEpoch:1,draft:{position:'Fixture'},analysis:{},applications:[]};
 $('#application-email').value='self@example.test';$('#application-message').value='Fixture message';
 const calls=[];const context={state,$,crypto:{randomUUID:()=> 'same-application'},authenticatedHeaders:h=>h,setBusy(){},renderApplications(){},window:{cvDrive:{isConnected:()=>true,headers:()=>({})},cvGmail:{connect:async()=>{},headers:()=>({}),reset(){}}},processFetch:async(path,options)=>{calls.push(JSON.parse(options.body));return {ok:true,json:async()=>({entry:{status:'gmail_accepted',application_id:'same-application'}})}}};
 const source=fs.readFileSync('static/app.js','utf8');vm.runInNewContext(source.slice(source.indexOf('async function sendApplicationGmail('),source.indexOf('$("#send-whatsapp").addEventListener')),context);
 return {context,state,$,calls};
}
test('safe admission conflict exposes resend and reuses the application without regenerating',async()=>{
 const q=fixture(),send=q.context.processFetch;let first=true;
 q.context.processFetch=async(...args)=>{if(first){first=false;throw Object.assign(new Error('Busy'),{status:409,code:'account_write_busy',externalOutcome:'not_started'})}return send(...args)};
 await q.context.sendApplicationGmail();assert.equal(q.state.gmailAttempt.unknown,false);assert.equal(q.$('#retry-gmail').hidden,false);
 const identifier=q.state.gmailAttempt.id;await q.context.sendApplicationGmail();assert.equal(q.calls.length,1);assert.equal(q.calls[0].application_id,identifier);assert.equal(q.state.gmailAttempt.sent,true);
 await q.context.sendApplicationGmail();assert.equal(q.calls.length,1);
});
test('direct safe 409 is retryable but ambiguous 409 and lost responses remain protected',async()=>{
 for(const safe of [true,false]){const q=fixture();let calls=0;q.context.processFetch=async()=>{calls++;return {ok:false,status:409,json:async()=>safe?{code:'account_write_busy',externalOutcome:'not_started',error:'Busy'}:{error:'Unconfirmed'}}};
 await q.context.sendApplicationGmail();assert.equal(q.state.gmailAttempt.unknown,!safe);assert.equal(q.$('#retry-gmail').hidden,!safe);await q.context.sendApplicationGmail();assert.equal(calls,safe?2:1);}
 const q=fixture();q.context.processFetch=async()=>{throw Error('Lost connection')};await q.context.sendApplicationGmail();assert.equal(q.state.gmailAttempt.unknown,true);assert.equal(q.$('#retry-gmail').hidden,true);
});
