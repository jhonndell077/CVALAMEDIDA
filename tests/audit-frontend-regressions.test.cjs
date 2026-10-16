const {test} = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs'), vm = require('node:vm');
const {parseHTML} = require('linkedom');
const source = fs.readFileSync('static/app.js', 'utf8');
const tick = () => new Promise(setImmediate);
function setup(extra = {}) {
  const elements = new Map();
  const $ = id => { if (!elements.has(id)) elements.set(id, {textContent:'', value:'', hidden:true, addEventListener(){}, replaceChildren(){}, append(){},classList:{add(){}},style:{setProperty(){}}}); return elements.get(id); };
  const state = {user:{uid:'alice',getIdToken:async()=> 'synthetic'},authEpoch:1, applications:[], profile:{name:'Alice'},profileDraft:{name:'Alice'},bankEnabled:true};
  const context = vm.createContext({state,$,structuredClone,URLSearchParams,Date,crypto:{randomUUID:()=> 'fixture-id'},authenticatedHeaders:h=>h||{},setBusy(){},renderProfileTree(){},analysisPanel:{},cvPanel:{},jobPanel:{},window:{cvDrive:{connect:async()=>{},isConnected:()=>true,headers:()=>({})}},...extra});
  return {context, state, $};
}
test('H02 late profile save does not replace another account profile or render its result', async()=>{
  let release, renders=0;
  const qa=setup({fetch:()=>new Promise(resolve=>release=resolve),renderProfileTree(){renders++;}});
  vm.runInContext(source.slice(source.indexOf('async function saveProfileChangesWork()'),source.indexOf('async function updateGoogleUser(')),qa.context);
  const pending=qa.context.saveProfileChangesWork();await tick();
  qa.state.user={uid:'bob'};qa.state.authEpoch++;qa.state.profile={name:'Bob'};
  release({ok:true,json:async()=>({profile:{name:'PRIVATE_ALICE'}})});await pending;
  assert.equal(qa.state.profile.name,'Bob');assert.equal(renders,0);
});
test('H02 sign out then return to the same UID still discards the earlier history response', async()=>{
  let release;
  const qa=setup({applicationRequest:()=>new Promise(resolve=>release=resolve),renderApplications(){}});
  vm.runInContext(source.slice(source.indexOf('async function refreshApplications('),source.indexOf('async function prepareApplication(')),qa.context);
  const pending=qa.context.refreshApplications();await tick();qa.state.authEpoch+=2;
  release({entries:[{application_id:'PRIVATE_ALICE'}]});await pending;
  assert.equal(qa.state.applications.length,0);
});
test('H02 discarded edits are not restored by a late save response',async()=>{
  let release;const qa=setup({fetch:()=>new Promise(resolve=>release=resolve)});
  vm.runInContext(source.slice(source.indexOf('async function saveProfileChangesWork()'),source.indexOf('async function updateGoogleUser(')),qa.context);
  const pending=qa.context.saveProfileChangesWork();await tick();
  qa.state.profileEditEpoch=(qa.state.profileEditEpoch||0)+1;qa.state.profileDraft={name:'Discarded'};
  release({ok:true,json:async()=>({profile:{name:'OLD_EDIT'}})});await pending;
  assert.equal(qa.state.profileDraft.name,'Discarded');
});
test('H02 profile photo completion after logout cannot create an object URL',async()=>{
  let release,created=0;const qa=setup({fetch:()=>new Promise(resolve=>release=resolve),getTemplateDetails:()=>({name:'Fixture'}),addText:()=>({append(){}}),document:{createElement:()=>({})},URL:{createObjectURL(){created++;return 'blob:private'},revokeObjectURL(){}}});
  vm.runInContext(source.slice(source.indexOf('async function renderDraft('),source.indexOf('async function download(')),qa.context);
  const pending=qa.context.renderDraft({candidate:{name:'Alice',phones:[]},position:'Fixture',skills:[],education:[],courses:[],experiences:[],references:[]});await tick();
  qa.state.user=null;qa.state.authEpoch++;
  release({ok:true,blob:async()=>({})});await pending;
  assert.equal(created,0);assert.notEqual(qa.state.photoUrl,'blob:private');
});
test('H02 export does not download or retain an artifact after switching accounts',async()=>{
  let release,downloads=0;const qa=setup({document:{createElement:()=>({click(){downloads++;}})},URL:{createObjectURL:()=> 'blob:private',revokeObjectURL(){}},processFetch:()=>new Promise(resolve=>release=resolve)});
  qa.state.analysis={vacancy:'Alice'};
  vm.runInContext(source.slice(source.indexOf('async function download('),source.indexOf('$("#download-pdf").addEventListener')),qa.context);
  const pending=qa.context.download('pdf');await tick();qa.state.user={uid:'bob'};qa.state.authEpoch++;
  release({ok:true,headers:{get:()=>''},blob:async()=>({})});await pending;
  assert.equal(downloads,0);assert.equal(qa.state.pdf,undefined);
});
test('H09 Gmail needs explicit granted send scope',()=>{
  const context=vm.createContext({window:{},Date,Promise});vm.runInContext(fs.readFileSync('static/gmail.js','utf8'),context);
  assert.equal(context.window.cvGmail.acceptCredential('synthetic-without-scopes'),false);
  assert.equal(context.window.cvGmail.isConnected(),false);
  assert.equal(context.window.cvGmail.acceptCredential('synthetic',3600,'https://www.googleapis.com/auth/gmail.send'),true);
});
test('H11 unknown send blocks only its own identity and stays protected when returning',async()=>{
  let sent=0;const qa=setup({processFetch:async()=>{sent++;throw Error('offline');},renderApplications(){}});
  qa.context.window.cvGmail={connect:async()=>{},headers:()=>({})};qa.state.draft={position:'A'};qa.$('#application-email').value='a@example.test';qa.$('#application-message').value='A';
  vm.runInContext(source.slice(source.indexOf('async function sendApplicationGmail('),source.indexOf('$("#send-whatsapp").addEventListener')),qa.context);
  await qa.context.sendApplicationGmail();await qa.context.sendApplicationGmail();assert.equal(sent,1);
  qa.state.draft={position:'B'};qa.$('#application-email').value='b@example.test';qa.$('#application-message').value='B';
  await qa.context.sendApplicationGmail();assert.equal(sent,2,'different application can send');
  qa.state.draft={position:'A'};qa.$('#application-email').value='a@example.test';qa.$('#application-message').value='A';
  await qa.context.sendApplicationGmail();assert.equal(sent,2,'original uncertain send must remain protected');
});
test('H12 history can load a subsequent cursor and appends without duplicated records',async()=>{
  const calls=[];const qa=setup({applicationRequest:async(payload,options)=>{calls.push(options);return calls.length===1?{entries:[{application_id:'one'}],has_more:true,next_cursor:'opaque-next'}:{entries:[{application_id:'one'},{application_id:'two'}],has_more:false,next_cursor:null};},renderApplications(){}});
  vm.runInContext(source.slice(source.indexOf('async function refreshApplications('),source.indexOf('async function prepareApplication(')),qa.context);
  await qa.context.refreshApplications();await qa.context.refreshApplications(true);
  assert.equal(calls[1]?.cursor,'opaque-next');assert.equal(qa.state.applications.length,2);assert.equal(qa.state.applications[0].application_id,'one');
});
test('H02 closing/resetting profile dialog removes moved private rows',()=>{
  const html=fs.readFileSync('static/index.html','utf8');const {window,document}=parseHTML(html);
  const tree=document.querySelector('#profile-tree');tree.innerHTML='<details class="profile-node" data-category="candidate"><summary><span class="profile-card-title">Nombre</span></summary><div class="profile-fields"><label class="profile-field">PRIVATE_ALICE</label></div></details>';
  const dialog=document.querySelector('#profile-category-dialog');dialog.showModal=()=>{dialog.open=true;};dialog.close=()=>{dialog.open=false;dialog.dispatchEvent(new window.Event('close'));};
  vm.runInContext(fs.readFileSync('static/profile-dialog.js','utf8'),vm.createContext({window,document}));
  tree.querySelector('summary').click();assert.match(document.querySelector('#profile-category-content').textContent,/PRIVATE_ALICE/);
  window.cvProfileDialog.reset?.();tree.replaceChildren();
  assert.equal(dialog.open,false);assert.doesNotMatch(document.querySelector('#profile-category-content').textContent,/PRIVATE_ALICE/);
});
test('H08 OAuth explanation discloses readonly access to all Drive files',()=>{
  const text=fs.readFileSync('static/drive-auth.js','utf8');
  assert.doesNotMatch(text,/Tu permiso se limita a los archivos y la carpeta que selecciones/);
  assert.match(text,/todos los archivos de (?:tu )?Drive/);
});
test('H10 initial preview banner explicitly identifies draft without claiming archived file',()=>{
  const {document}=parseHTML(fs.readFileSync('static/index.html','utf8'));
  assert.match(document.querySelector('#template-confirmation').textContent,/borrador/i);
  assert.doesNotMatch(document.querySelector('#template-confirmation').textContent,/se archiva/);
});
test('H14 configured Vertex can be used while availability is explicitly unverified',async()=>{
  const select={closest:()=>({}),replaceChildren(){},add(){}};const qa=setup({modelSelect:select,Option:class{},updateAnalyzeButton(){}});
  vm.runInContext(source.slice(source.indexOf('async function loadModels('),source.indexOf('function loadScript(')),qa.context);
  await qa.context.loadModels({provider:'vertex-ai',model_available:false,model_configured:true,model_status:'not_verified',models:[{name:'fixture-model'}]});
  assert.equal(qa.state.modelAvailable,true);assert.match(qa.$('#model-help').textContent,/sin verificar|no verificada/i);
  assert.match(qa.$('#privacy-note').innerHTML,/Cloud Storage/);assert.match(qa.$('#privacy-note').innerHTML,/privacy\.html/);
});
test('H02 late delete response cannot replace the next account profile',async()=>{
  let release,remove;
  const qa=setup({fetch:()=>new Promise(resolve=>release=resolve),canDeleteProfilePath:()=>true,profileEntryTitle:()=> 'Fixture',addText:()=>({setAttribute(){},addEventListener:(_,handler)=>remove=handler})});
  qa.state.profile={courses:[{id:'one',title:'Private'}]};qa.state.profileDraft=structuredClone(qa.state.profile);
  qa.context.window.confirm=()=>true;qa.context.window.cvLoading={run:(_,fn)=>fn()};
  vm.runInContext(source.slice(source.indexOf('function addProfileDeleteButton('),source.indexOf('function renderProfileField(')),qa.context);
  qa.context.addProfileDeleteButton({},['courses',0],qa.state.profile.courses[0]);
  const pending=remove({preventDefault(){},stopPropagation(){}});await tick();
  qa.state.user={uid:'bob'};qa.state.authEpoch++;qa.state.profile={name:'Bob'};
  release({ok:true,json:async()=>({profile:{name:'PRIVATE_ALICE'}})});await pending;
  assert.equal(qa.state.profile.name,'Bob');
});
test('H02 Gmail authorization completed after account switch never submits a message',async()=>{
  let release,submitted=0;const qa=setup({processFetch:async()=>{submitted++;throw Error('must not send');},renderApplications(){}});
  qa.context.window.cvGmail={connect:()=>new Promise(resolve=>release=resolve),headers:()=>({})};
  qa.state.draft={position:'A'};qa.$('#application-email').value='a@example.test';qa.$('#application-message').value='A';
  vm.runInContext(source.slice(source.indexOf('async function sendApplicationGmail('),source.indexOf('$("#send-whatsapp").addEventListener')),qa.context);
  const pending=qa.context.sendApplicationGmail();await tick();qa.state.user={uid:'bob'};qa.state.authEpoch++;release();await pending;
  assert.equal(submitted,0);assert.notEqual(qa.state.idToken,'synthetic');
});
test('H02 a confirmed Gmail response from an earlier account does not populate current history',async()=>{
  let release;const qa=setup({processFetch:()=>new Promise(resolve=>release=resolve),renderApplications(){}});
  qa.context.window.cvGmail={connect:async()=>{},headers:()=>({})};qa.state.draft={position:'A'};qa.$('#application-email').value='a@example.test';qa.$('#application-message').value='A';
  vm.runInContext(source.slice(source.indexOf('async function sendApplicationGmail('),source.indexOf('$("#send-whatsapp").addEventListener')),qa.context);
  const pending=qa.context.sendApplicationGmail();await tick();qa.state.user={uid:'bob'};qa.state.authEpoch++;qa.state.applications=[];
  release({ok:true,json:async()=>({entry:{application_id:'PRIVATE_ALICE',status:'gmail_accepted'}})});await pending;
  assert.equal(qa.state.applications.length,0);
});
test('H02 a canceled information form does not apply its delayed result',async()=>{
  let handler,release,applied=0;const form={hidden:false,addEventListener:(_,fn)=>handler=fn};
  const qa=setup({informationForm:form,informationSaving:false,informationRequestId:null,informationRequestSignature:null,FormData:class{*[Symbol.iterator](){yield ['type','courses'];yield ['title','Fixture'];}},requestJson:()=>new Promise(resolve=>release=resolve),applySavedProfile(){applied++;}});
  qa.context.window.cvRepeaters={collect:()=>({})};
  vm.runInContext(source.slice(source.indexOf('informationForm.addEventListener("submit"'),source.indexOf('const templateDetails')),qa.context);
  const pending=handler({preventDefault(){}});await tick();qa.state.informationEpoch=(qa.state.informationEpoch||0)+1;form.hidden=true;
  release({profile:{name:'PRIVATE_ALICE'}});await pending;assert.equal(applied,0);
});
test('H02 logout cancels the old Drive popup and ignores its late credential',async()=>{
  const listeners=new Map();let closed=false,checks=0;
  const popup={close(){closed=true;},closed:false};
  const context=vm.createContext({Date,Promise,Event,crypto:{randomUUID:()=> 'nonce'},location:{origin:'https://cvalamedida.web.app'},setInterval:()=>1,clearInterval(){},
    document:{querySelector:()=>({addEventListener(){}})},fetch:async()=>{checks++;return {ok:true,json:async()=>({})};},
    window:{open:()=>popup,addEventListener:(type,fn)=>listeners.set(type,fn),removeEventListener:type=>listeners.delete(type),dispatchEvent(){},cvLoading:{start:()=>()=>{}}}});
  vm.runInContext(fs.readFileSync('static/drive.js','utf8'),context);const drive=context.window.cvDrive;
  await drive.initialize({provider:'drive'},()=>({}));const pending=drive.connect();const receive=listeners.get('message');drive.reset();
  receive({origin:'https://cv-a-la-medida-jhonn.firebaseapp.com',source:popup,data:{nonce:'nonce',result:{access_token:'PRIVATE_ALICE'}}});
  await assert.rejects(pending,/cuenta cambió|sesión cambió/);assert.equal(closed,true);assert.equal(checks,0);assert.equal(drive.isConnected(),false);
});
test('H09 Firebase login verifies actual granted scopes through the authenticated backend',async()=>{
  const calls=[];const qa=setup({directRequestJson:async(...args)=>{calls.push(args);return {scope:'https://www.googleapis.com/auth/drive.file',expires_in:3500};}});
  const match=source.match(/async function verifiedGoogleCredential\([\s\S]*?(?=async function initializeGoogleAuth\()/);
  if (match) vm.runInContext(match[0],qa.context);
  assert.equal(typeof qa.context.verifiedGoogleCredential,'function','Firebase credentials must obtain confirmed scopes');
  const grant=await qa.context.verifiedGoogleCredential('synthetic-google');
  assert.equal(calls[0][0],'/api/google/grant');assert.equal(calls[0][2]['X-Drive-Access-Token'],'synthetic-google');
  assert.equal(grant.scope,'https://www.googleapis.com/auth/drive.file');assert.equal(grant.gmailRequested,undefined);
});
