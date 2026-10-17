const {test}=require('node:test');
const assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm');
const app=fs.readFileSync('static/app.js','utf8');
function part(start,end){return app.slice(app.indexOf(start),app.indexOf(end,app.indexOf(start)));}
test('operation identifiers reuse request nonce and never accept arbitrary private strings',()=>{
 const context={crypto:{randomUUID:()=> '12345678-1234-1234-1234-123456789abc'}};
 vm.runInNewContext(part('function operationIdFor','window.addEventListener(\'cv-client-diagnostic\''),context);
 const id='abcdef0123456789abcdef0123456789';
 assert.equal(context.operationIdFor({request_id:id}),id);
 assert.equal(context.operationIdFor({request_id:'private@example.com'}),'12345678-1234-1234-1234-123456789abc');
});
test('diagnostic failure is ignored and payload never copies untrusted properties',async()=>{
 let handler,calls=[];
 const context={window:{addEventListener:(_,fn)=>handler=fn},state:{user:{uid:'fixture'}},operationIdFor:()=> 'uuid',
 directRequestJson:(...args)=>{calls.push(args);return Promise.reject(Error('offline'));}};
 vm.runInNewContext(part("window.addEventListener('cv-client-diagnostic'",'async function requestJson'),context);
 handler({detail:{service:'drive-api',stage:'oauth-authorization',code:'access_denied',token:'secret',error:'sensitive'}});
 await new Promise(r=>setImmediate(r));
 assert.equal(calls.length,1); assert.deepEqual(JSON.parse(JSON.stringify(calls[0][1])),{service:'drive-api',stage:'oauth-authorization',result:'error',code:'access_denied'});
 handler({detail:{service:'drive-api',stage:'oauth-authorization',code:'secret'}});assert.equal(calls.length,1);
 context.state.user=null;handler({detail:{service:'drive-api',stage:'oauth-authorization',code:'access_denied'}});assert.equal(calls.length,1);
});
test('basic provider requests no Drive or Gmail scopes while authorization requests both',()=>{
 const providers=[];
 function Provider(){this.scopes=[];this.addScope=s=>this.scopes.push(s);this.setCustomParameters=()=>{};providers.push(this);}
 const context={window:{firebase:{auth:{GoogleAuthProvider:Provider}}},state:{driveEnabled:true,multiAccount:true}};
 const provider=part('  const googleProvider =','  window.cvDrive.setAuthorizationHandler');
 vm.runInNewContext(provider+'\nglobalThis.basic=googleProvider();globalThis.drive=googleProvider(true);',context);
 assert.equal(context.basic.scopes.length,0);assert.equal(context.drive.scopes.length,3);
 const login=part('  $("#google-sign-in").addEventListener','  $("#google-sign-out").addEventListener');
 assert.doesNotMatch(login,/verifiedGoogleCredential|acceptCredential/);
});
test('popup reports only a fixed code with nonce and never sends the OAuth error description',async()=>{
 let callbacks;const messages=[];
 const nodes={};const context={location:{search:'?origin=https://cvalamedida.web.app&nonce=12345678-1234-1234-1234-123456789abc'},URLSearchParams,
 document:{querySelector:key=>nodes[key]||(nodes[key]={addEventListener(){}})},window:{opener:{postMessage:(...args)=>messages.push(args)},close(){}},
 fetch:async()=>({ok:true,json:async()=>({client_id:'fixture'})}),google:{accounts:{oauth2:{initTokenClient:settings=>{callbacks=settings;return {};}}}}};
 vm.runInNewContext(fs.readFileSync('static/drive-auth.js','utf8'),context);await new Promise(r=>setImmediate(r));
 callbacks.callback({error:'access_denied',error_description:'private detail',access_token:'secret'});
 assert.deepEqual(JSON.parse(JSON.stringify(messages[0])),[{nonce:'12345678-1234-1234-1234-123456789abc',diagnostic:{code:'access_denied'}},'https://cvalamedida.web.app']);
 callbacks.error_callback({type:'unknown private description'});assert.equal(messages[1][0].diagnostic.code,'oauth_error');
});
