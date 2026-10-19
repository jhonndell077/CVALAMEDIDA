const test = require('node:test');
const assert = require('node:assert/strict');
const {detect, destination} = require('../static/employment.js');
const fs = require('node:fs');
const vm = require('node:vm');

test('GPS se solicita al invocar detect con alta precisión y timeout', async () => {
  let calls = 0;
  const navigator = {geolocation:{getCurrentPosition(success,error,options) {
    calls++; assert.deepEqual(options,{enableHighAccuracy:true,timeout:12000,maximumAge:0});
    success({coords:{latitude:18.4885,longitude:-69.8571,accuracy:30}});
  }}};
  assert.equal(calls,0);
  assert.deepEqual(await detect(navigator),{lat:18.4885,lng:-69.8571,accuracy_m:30});
  assert.equal(calls,1);
});
for (const [code, message] of [[1,/Permiso rechazado/],[2,/no disponible/],[3,/tiempo de espera/]]) {
  test(`GPS maneja error ${code}`, async () => {
    await assert.rejects(detect({geolocation:{getCurrentPosition(success,error) {error({code});}}}),message);
  });
}
test('GPS ausente permite corrección manual', async () => {
  await assert.rejects(detect({}),/coordenadas/);
});
test('marcador actualiza coordenadas geodésicas', () => {
  const center = {lat:18.4885,lng:-69.8571};
  assert.ok(destination(center,1000,0).lng > center.lng);
  assert.ok(destination(center,0,1000).lat > center.lat);
  assert.ok(Math.abs(destination(center,0,0).lat-center.lat)<1e-10);
});
test('marcador cruza correctamente el meridiano 180', () => {
  const point = destination({lat:0,lng:179.999},1000,0);
  assert.ok(point.lng < -179.9 && point.lng >= -180);
});

function authBridge(state) {
  let handler;
  const source=fs.readFileSync('static/app.js','utf8');
  const code=source.slice(source.indexOf('window.cvEmployment?.initialize'),source.indexOf('window.cvTelegram?.initialize'));
  vm.runInNewContext(code,{state,user:state.user,Error,window:{cvEmployment:{initialize(user,callback) {handler=callback; return Promise.resolve();}}},
    authenticatedHeaders(headers) {if (state.idToken) headers.Authorization=`Bearer ${state.idToken}`; return {...headers,'X-Drive-Access-Token':'fixture-drive-token'};}});
  return handler;
}
test('ubicación usa solo identidad Firebase; búsquedas reutilizan Drive con token renovado',async()=>{
  const state={user:{uid:'alice',getIdToken:async()=>'renewed-fixture-token'},idToken:'expired-fixture-token'};
  const handler=authBridge(state);
  const location=await handler('location');
  assert.equal(location.Authorization,'Bearer renewed-fixture-token'); assert.equal(location['X-Drive-Access-Token'],undefined);
  const search=await handler('search');
  assert.equal(search.Authorization,'Bearer renewed-fixture-token'); assert.equal(search['X-Drive-Access-Token'],'fixture-drive-token');
});
test('cambio de cuenta durante renovación bloquea la operación y conserva la nueva sesión',async()=>{
  let finish;
  const state={user:{uid:'alice',getIdToken:()=>new Promise(resolve=>{finish=resolve;})},idToken:'alice-old-fixture'};
  const pending=authBridge(state)('search'); state.user={uid:'bob'}; state.idToken='bob-fixture'; finish('alice-new-fixture');
  await assert.rejects(pending,/cuenta cambió/); assert.equal(state.idToken,'bob-fixture');
});
test('seleccionar otra vacante restablece el paso y evita reutilizar un CV anterior',()=>{
  const source=fs.readFileSync('static/app.js','utf8');
  const code=source.slice(source.indexOf("window.addEventListener('cv-employment-vacancy'"),source.indexOf('window.addEventListener("pageshow"'));
  let handler,clicks=0,step=0; const elements=new Map();
  const get=key=>{if(!elements.has(key)) elements.set(key,{disabled:false,click(){clicks++;}}); return elements.get(key);};
  const state={analysis:{old:true},draft:{old:true},pdf:'old-fixture'},jobTextInput={},fileInput={value:'old.pdf'};
  const jobPanel={hidden:true,scrollIntoView(){}},analysisPanel={hidden:false},cvPanel={hidden:false};
  vm.runInNewContext(code,{window:{addEventListener(name,fn){handler=fn;}},state,jobTextInput,fileInput,jobPanel,analysisPanel,cvPanel,
    $:get,resetVacancyChoice(){},updateRemoveTextButton(){},setActiveStep(value){step=value;}});
  handler({detail:{text:'Nueva oferta real'},preventDefault(){}});
  assert.equal(state.analysis,null); assert.equal(state.draft,null); assert.equal(state.pdf,null);
  assert.equal(jobTextInput.value,'Nueva oferta real'); assert.equal(fileInput.value,'');
  assert.equal(jobPanel.hidden,false); assert.equal(cvPanel.hidden,true); assert.equal(analysisPanel.hidden,true); assert.equal(step,1); assert.equal(clicks,1);
});


test('GPS completa país sin sustituir el punto y permite remotos', async () => {
  const source=fs.readFileSync('static/employment.js','utf8');
  const code=source.slice(source.indexOf('  async function resolveCountry()'),source.indexOf("  $('#employment-location-button').addEventListener"));
  const fields={}; const point={lat:18.4885,lng:-69.8571};
  const context={point:()=>point,field:name=>fields[name] ||= {},Error,
    request:async(path,method,payload)=>{
      assert.equal(path,'reverse-geocode'); assert.equal(method,'POST'); assert.deepEqual(payload,point);
      return {results:[{country:'DO',city:'Fixture',lat:19,lng:-70}]};
    }};
  vm.runInNewContext(code+';globalThis.resolve=resolveCountry;',context);
  await context.resolve();
  assert.equal(fields.country.value,'DO'); assert.equal(fields.allowed_countries.value,'DO');
  assert.equal(fields.allow_remote.checked,true); assert.equal(point.lat,18.4885);
  context.request=async()=>{point.lat=19;return {results:[{country:'DO'}]};};
  // Each point read must represent the current coordinate values, as in the browser.
  context.point=()=>({...point});
  await assert.rejects(context.resolve(),/punto cambió/);
});


test('session initialization and searches do not load application history',()=>{
 const source=fs.readFileSync('static/employment.js','utf8');
 const initialize=source.slice(source.indexOf('  api.initialize ='),source.indexOf('  async function resolveCountry'));
 assert.ok(initialize.includes('currentApplications.clear()'));
 assert.ok(!initialize.includes('renderApplications()'));
 const search=source.slice(source.indexOf('  async function searchJobs('));
 assert.ok(!search.includes('await renderApplications()'));
});

test('application panel only renders candidacies explicitly selected in the current session',async()=>{
 const source=fs.readFileSync('static/employment.js','utf8');
 const code=source.slice(source.indexOf('  async function renderApplications()'),source.indexOf('  let latestPublications'));
 const cards=[];const container={replaceChildren(){cards.length=0},append(card){cards.push(card)}};
 const context=vm.createContext({$:()=>container,currentApplications:new Set(['current']),
 request:async()=>({applications:[{id:'old',position:'Previous',status:'CANCELADA'},{id:'current',position:'Selected',status:'CANCELADA'}]}),
 root:{document:{createElement:()=>({append(){}})}}});
 vm.runInContext(code,context);await context.renderApplications();assert.equal(cards.length,1);
 context.currentApplications.clear();await context.renderApplications();assert.equal(cards.length,0);
});
