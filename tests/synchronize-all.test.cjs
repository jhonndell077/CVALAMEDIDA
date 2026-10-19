const {test}=require('node:test');
const assert=require('node:assert/strict');
const vm=require('node:vm'),fs=require('node:fs');
test('one authorization connects Telegram, Drive and Gmail; reuse and cancellation settle',async()=>{
  const elements=new Map();
  const element=id=>{if(!elements.has(id))elements.set(id,{listeners:{},addEventListener(type,handler){this.listeners[type]=handler;},removeAttribute(){}});return elements.get(id);};
  let oauth, requests=0, connected=false, accepted=0, confirmed=0, links=0, linked=true;
  const window={google:{accounts:{oauth2:{}}},cvLoading:{start:()=>()=>{}},
    cvDrive:{isConnected:()=>connected,acceptCredential:async token=>{assert.equal(token,'shared');connected=true;accepted++;}},
    cvGmail:{isConnected:()=>connected}};
  const context=vm.createContext({window,Date,Error,Promise,JSON,document:{querySelector:element},
    google:{accounts:{oauth2:{initCodeClient:settings=>{oauth=settings;return {requestCode(){requests++;}};}}}},
    fetch:async path=>({ok:true,json:async()=>{
      if(path.endsWith('/disconnect')) { connected=false; linked=false; return {}; }
      if(path.endsWith('/link')) { links++; linked=true; return {}; }
      if(path.endsWith('/session'))return {access_token:'shared',scope:'https://www.googleapis.com/auth/gmail.send',expires_in:3600};
      if(path.endsWith('/authorize'))return {access_token:'shared'};
      if(path.endsWith('/confirm')){confirmed++;return {};}
      return {client_id:'test',drive_connected:connected,message:'Listo',linked};
    }})});
  vm.runInContext(fs.readFileSync('static/telegram.js','utf8'),context);
  await window.cvTelegram.initialize({uid:'alice',email:'test@example.com',getIdToken:async()=>'id'},()=>({}));
  const first=window.cvTelegram.synchronize();
  assert.equal(requests,1);
  assert.equal(window.cvTelegram.synchronize(),first);
  await window.cvTelegram.initialize({uid:'alice',email:'test@example.com',getIdToken:async()=>'renewed-id'},()=>({}));
  assert.equal(window.cvTelegram.synchronize(),first);
  oauth.callback({code:'code'});await first;
  assert.equal(accepted,1);assert.equal(confirmed,1);
  await window.cvTelegram.synchronize();assert.equal(requests,1);
  connected=false;
  await window.cvTelegram.synchronize();assert.equal(requests,1);assert.equal(accepted,2);
  await element('#telegram-disconnect').listeners.click();
  assert.equal(element('#telegram-authorize-drive').hidden,false);
  const relink=element('#telegram-link').listeners.click();
  assert.equal(requests,2,'relink requests Google authorization from the same click');
  assert.equal(links,0,'link waits for successful authorization');
  oauth.callback({code:'renewed'});await relink;
  assert.equal(links,1);assert.equal(element('#telegram-authorize-drive').hidden,true);
  connected=false;
  await window.cvTelegram.initialize({email:'test@example.com',getIdToken:async()=>'id'},()=>({}));
  const cancelled=window.cvTelegram.synchronize();oauth.error_callback();
  await assert.rejects(cancelled,/autorización se cerró/);
  const retried=window.cvTelegram.synchronize();oauth.callback({error:'access_denied'});
  await assert.rejects(retried,/no concedió/);
});
