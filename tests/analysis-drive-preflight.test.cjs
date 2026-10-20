const {test}=require('node:test'),assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm');
const source=fs.readFileSync('static/app.js','utf8');
function setup(connected=false){
 const calls=[];const state={bankEnabled:true,user:{uid:'owner'},authEpoch:1};
 const drive={isConnected:()=>connected,connect:async()=>{calls.push('connect');connected=true;}};
 const context={state,window:{cvDrive:drive,cvBackground:{enabled:()=>true,run:async()=>{calls.push('analyze');return {ok:true}}}}};
 vm.runInNewContext(source.slice(source.indexOf('async function analyzeVacancyRequest'),source.indexOf('jobTextInput.addEventListener')),context);
 return {context,calls,drive,state};
}
test('expired or absent Drive authorization reconnects before admitting background analysis',async()=>{const q=setup();await q.context.analyzeVacancyRequest({text:'Offer'});assert.deepEqual(q.calls,['connect','analyze']);});
test('valid Drive authorization is reused without a second synchronization or popup',async()=>{const q=setup(true);await q.context.analyzeVacancyRequest({text:'Offer'});assert.deepEqual(q.calls,['analyze']);});
test('cancelled connection preserves the request and never admits analysis',async()=>{const q=setup();q.drive.connect=async()=>{throw Error('Cancelled')};const payload={text:'Keep offer',file_data:'fixture'};await assert.rejects(q.context.analyzeVacancyRequest(payload),/Cancelled/);assert.deepEqual(q.calls,[]);assert.equal(payload.text,'Keep offer');});
test('account changed during connection cannot submit previous account analysis',async()=>{const q=setup();q.drive.connect=async()=>{q.state.user={uid:'other'};};await assert.rejects(q.context.analyzeVacancyRequest({}),/cuenta cambió/);assert.deepEqual(q.calls,[]);});
test('authorization that does not establish access cannot proceed',async()=>{const q=setup();q.drive.connect=async()=>{};await assert.rejects(q.context.analyzeVacancyRequest({}),/no confirmó/);assert.deepEqual(q.calls,[]);});
