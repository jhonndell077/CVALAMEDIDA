const assert=require('node:assert/strict');
const test=require('node:test');
const fs=require('node:fs');
const vm=require('node:vm');
const source=fs.readFileSync('static/app.js','utf8');
function context(responses){
  const calls=[];
  const sandbox=vm.createContext({window:{cvBackground:{enabled:()=>false}},state:{authRequired:true,provider:'vertex-ai'},crypto:{randomUUID:()=> 'unique-request'},setTimeout:fn=>fn(),requestJson:async(url,payload)=>{calls.push({url,payload});return responses.shift();}});
  vm.runInContext(source.slice(source.indexOf('async function analyzeVacancyRequest'),source.indexOf('jobTextInput.addEventListener')),sandbox);
  return {sandbox,calls};
}
test('web polls its original job instead of repeating slow Vertex requests',async()=>{
  const result={selection_required:true,positions:['A','B']};
  const {sandbox,calls}=context([{job_id:'web-original'},{state:'queued'},{state:'processing'},{state:'done',result}]);
  assert.equal(await sandbox.analyzeVacancyRequest({text:'Oferta',selected_position:'A'}),result);
  assert.equal(calls[0].url,'/api/analyze/jobs');
  assert.equal(calls[0].payload.selected_position,'A');
  assert.equal(calls.slice(1).every(call=>call.url==='/api/analyze/jobs/web-original'),true);
});
test('durable failure leaves a readable message for the existing loading handler',async()=>{
  const {sandbox}=context([{job_id:'web-original'},{state:'failed',error:'Tiempo agotado'}]);
  await assert.rejects(sandbox.analyzeVacancyRequest({text:'Oferta'}),/Tiempo agotado/);
});
