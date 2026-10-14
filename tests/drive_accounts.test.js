const assert = require('node:assert/strict');
const {test} = require('node:test');
const vm = require('node:vm');
const fs = require('node:fs');
function deferred() { let resolve; const promise = new Promise(r => {resolve=r;}); return {promise,resolve}; }
function environment() {
  const elements = new Map(), events = [];
  const element = id => {
    if (!elements.has(id)) elements.set(id,{textContent:'',addEventListener(){}});
    return elements.get(id);
  };
  const context = vm.createContext({Date,Number,Boolean,Error,Promise,Object,JSON,
    CustomEvent:class {constructor(type,data){this.type=type;this.detail=data.detail;}},
    Event:class {constructor(type){this.type=type;}},
    document:{querySelector:element,createElement:()=>({}),head:{append:node=>node.onload()}},
    gapi:{load:(name,options)=>options.callback()},
    window:{dispatchEvent:event=>events.push(event),cvLoading:{start:()=>()=>{}},cvGmail:{acceptCredential(){},isConnected:()=>false}}
  });
  vm.runInContext(fs.readFileSync('static/drive.js','utf8'),context);
  return {context,drive:context.window.cvDrive,elements,events};
}
test('Drive requires confirmed setup and rejects responses after account switches',async()=>{
  const {context,drive,elements,events}=environment();
  await drive.initialize({provider:'drive',multi_account:true},()=>({Authorization:'Bearer alice'}));
  context.fetch=async()=>({ok:false,status:403,json:async()=>({error:'Selecciona tus carpetas'})});
  await assert.rejects(drive.acceptCredential('alice-drive'),/Selecciona/);
  assert.equal(drive.isConnected(),false);
  assert.equal(drive.headersIfConnected()['X-Drive-Access-Token'],'alice-drive');
  const response=deferred();
  context.fetch=()=>response.promise;
  const loading=drive.acceptCredential('alice-drive');
  drive.reset();
  response.resolve({ok:true,json:async()=>({ready:true,bank_id:'alice-bank',archive_id:'alice-cv'})});
  await assert.rejects(loading,/sesión cambió/);
  assert.equal(drive.isConnected(),false);
  assert.equal(events.length,0);
  assert.notEqual(elements.get('#bank-folder')?.href,'https://drive.google.com/drive/folders/alice-bank');
  context.fetch=async()=>({ok:true,json:async()=>({ready:true,bank_id:'bob-bank',archive_id:'bob-cv'})});
  await drive.acceptCredential('bob-drive');
  assert.equal(drive.isConnected(),true);
  assert.equal(drive.headersIfConnected()['X-Drive-Access-Token'],'bob-drive');
  assert.equal(elements.get('#bank-folder').href,'https://drive.google.com/drive/folders/bob-bank');
});
test('An OAuth result pending at logout cannot connect the previous Drive',async()=>{
  const {drive}=environment();
  await drive.initialize({provider:'drive',multi_account:true},()=>({}));
  const consent=deferred(); drive.setAuthorizationHandler(()=>consent.promise);
  const connection=drive.connect(); drive.reset();
  consent.resolve({access_token:'alice-drive'});
  await assert.rejects(connection,/cuenta cambió/);
  assert.equal(drive.isConnected(),false);
  assert.equal(Object.keys(drive.headersIfConnected()).length,0);
});

test('manual folder selection closes both pickers and submits the selected pair',async()=>{
 const {context,drive}=environment();const selections=['manual-bank','manual-cv'];let closed=0;const bodies=[];
 class View {setIncludeFolders(){return this;}setSelectFolderEnabled(){return this;}setMimeTypes(){return this;}}
 class Builder {
  addView(){return this;}setOAuthToken(){return this;}setDeveloperKey(){return this;}setAppId(){return this;}setOrigin(){return this;}setTitle(){return this;}
  setCallback(callback){this.callback=callback;return this;}
  build(){const callback=this.callback;return {setVisible(show){if(show)queueMicrotask(()=>callback({action:'picked',docs:[{id:selections.shift()}]}));else closed++;}};}
 }
 context.google={picker:{DocsView:View,PickerBuilder:Builder,ViewId:{FOLDERS:'folders'},Action:{PICKED:'picked',CANCEL:'cancel'}}};
 context.location={origin:'https://cvalamedida.web.app'};
 context.fetch=async(path,options)=>{bodies.push(JSON.parse(options.body));return {ok:true,json:async()=>({ready:true,bank_id:'bank',archive_id:'archive'})};};
 await drive.initialize({provider:'drive',multi_account:true,picker_api_key:'configured-key',app_id:'project'},()=>({}));
 await drive.acceptCredential('account-token');await drive.chooseFolders();
 assert.deepEqual(bodies[1],{bank_id:'manual-bank',archive_id:'manual-cv'});assert.equal(closed,2);
});
