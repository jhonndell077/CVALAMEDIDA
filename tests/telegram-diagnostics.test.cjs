const {test}=require('node:test'),assert=require('node:assert/strict'),vm=require('node:vm'),fs=require('node:fs');
const settle=()=>new Promise(r=>setImmediate(r));
async function setup(failTelemetry=false){
 const elements=new Map(), reports=[],clients=[],timers=[];
 const element=id=>{if(!elements.has(id))elements.set(id,{handlers:{},addEventListener(k,f){this.handlers[k]=f;},removeAttribute(){}});return elements.get(id);};
 const window={google:{accounts:{oauth2:{}}},cvLoading:{start:()=>()=>{}},cvDrive:{isConnected:()=>false,acceptCredential:async()=>{}},cvGmail:{isConnected:()=>false}};
 let serial=0;
 const context=vm.createContext({window,Date,Error,Promise,JSON,crypto:{randomUUID:()=>String(++serial).padStart(32,'a')},
  setTimeout:f=>{timers.push(f);return timers.length;},clearTimeout(){},document:{querySelector:element},
  google:{accounts:{oauth2:{initCodeClient:config=>{clients.push(config);return {requestCode(){}};}}}},
  fetch:async(path,options)=>{if(path==='/api/diagnostics/client'){reports.push({data:JSON.parse(options.body),headers:options.headers});if(failTelemetry)throw Error('offline');return {ok:true};}return {ok:true,json:async()=>({client_id:'public-fixture',drive_connected:false,message:'fixture'})};}});
 vm.runInContext(fs.readFileSync('static/telegram.js','utf8'),context);
 const user=uid=>({uid,email:'fixture@example.test',getIdToken:async()=> 'not-recorded'});
 await window.cvTelegram.initialize(user('alice'),()=>({}));
 return {telegram:window.cvTelegram,clients,reports,timers,user,element};
}
test('Telegram reports pending and OAuth mismatch with one operation and no sensitive content',async()=>{
 const ui=await setup(),pending=ui.telegram.synchronize();
 ui.clients[0].callback({error:'origin_mismatch',error_description:'private text',code:null});
 await assert.rejects(pending,/no concedió/);await settle();
 assert.deepEqual(ui.reports.map(r=>r.data.code),['authorization_pending','origin_mismatch']);
 assert.equal(ui.reports[1].data.component,'telegram');
 assert.equal(ui.reports[0].headers['X-CV-Operation-ID'],ui.reports[1].headers['X-CV-Operation-ID']);
 assert.doesNotMatch(JSON.stringify(ui.reports.map(r=>r.data)),/private|not-recorded|fixture@example/);
});
test('closed popup and missing callback timeout report warnings without inventing origin mismatch',async()=>{
 const ui=await setup();let pending=ui.telegram.synchronize();ui.clients[0].error_callback({type:'popup_closed'});
 await assert.rejects(pending,/autorización se cerró/);await settle();
 assert.equal(ui.reports.at(-1).data.code,'popup_closed');
 pending=ui.telegram.synchronize();ui.timers.at(-1)();
 await assert.rejects(pending,/no confirmó/);await settle();
 assert.equal(ui.reports.at(-1).data.code,'authorization_timeout');
 assert.equal(new Set(ui.reports.map(r=>r.headers['X-CV-Operation-ID'])).size,1,'retry preserves the grant operation for confirmed resolution');
 assert.equal(ui.reports.filter(r=>r.data.code==='origin_mismatch').length,0);
});
test('late callback after account switch cannot settle or report the next authorization',async()=>{
 const ui=await setup(),first=ui.telegram.synchronize();const rejection=assert.rejects(first,/cuenta cambió/);
 await ui.telegram.initialize(ui.user('bob'),()=>({}));await rejection;
 const second=ui.telegram.synchronize();ui.clients[0].error_callback({type:'origin_mismatch'});await settle();
 assert.equal(ui.reports.filter(r=>r.data.code==='origin_mismatch').length,0);
 ui.clients.at(-1).error_callback({type:'popup_closed'});await assert.rejects(second,/se cerró/);
});
test('timed-out attempt cannot cancel or submit a code for a newer attempt',async()=>{
 const ui=await setup(),first=ui.telegram.synchronize(),old=ui.clients.at(-1);
 ui.timers.at(-1)();await assert.rejects(first,/no confirmó/);
 const second=ui.telegram.synchronize();old.callback({code:'old-code'});old.error_callback({type:'popup_closed'});await settle();
 assert.equal(ui.reports.filter(r=>r.data.code==='popup_closed').length,0);
 ui.clients.at(-1).error_callback({type:'access_denied'});await assert.rejects(second,/se cerró/);
});
test('Google wait timeout cannot fire after a code was received during backend processing',async()=>{
 const ui=await setup(),pending=ui.telegram.synchronize();ui.clients.at(-1).callback({code:'fresh-code'});
 ui.timers.at(-1)();await pending;await settle();
 assert.equal(ui.reports.filter(r=>r.data.code==='authorization_timeout').length,0);
});
test('diagnostic transport failure does not alter the original OAuth failure',async()=>{
 const ui=await setup(true),pending=ui.telegram.synchronize();ui.clients[0].error_callback({type:'popup_closed'});
 await assert.rejects(pending,/se cerró/);await settle();
 assert.equal(ui.reports.at(-1).data.code,'popup_closed');
});
