const assert=require('node:assert/strict');
const {test}=require('node:test');
const vm=require('node:vm'),fs=require('node:fs');
test('Telegram pairing UI keeps expiring links and pending identities inside their account',async()=>{
  const elements=new Map();
  function element(id){if(!elements.has(id))elements.set(id,{hidden:true,handlers:{},removeAttribute(name){delete this[name];},addEventListener(name,handler){this.handlers[name]=handler;}});return elements.get(id);}
  let account='alice',pending=null;
  const context=vm.createContext({Date,Error,Promise,JSON,
    document:{querySelector:element},google:{accounts:{oauth2:{initCodeClient:()=>({requestCode(){}})}}},
    window:{google:{accounts:{oauth2:{}}},cvLoading:{start:()=>()=>{}}},
    fetch:async path=>({ok:true,json:async()=>path==='/api/telegram/link'?{bot_url:'https://t.me/TestBot?start=alice-private-link',expires_in:600}:{multi_account:true,linked:false,drive_connected:true,client_id:'test',message:'Vincula tu Telegram.',pending:account==='alice'?pending:null}})
  });
  vm.runInContext(fs.readFileSync('static/telegram.js','utf8'),context);
  const telegram=context.window.cvTelegram;
  await telegram.initialize({getIdToken:async()=>'alice-token',email:'alice@example.com'},()=>({}));
  assert.equal(element('#telegram-link').hidden,false);
  await element('#telegram-link').handlers.click();
  assert.equal(element('#telegram-open-bot').href,'https://t.me/TestBot?start=alice-private-link');
  pending={telegram_id:321,telegram_name:'Alice TG',telegram_username:'alice'};
  element('#telegram-check-link').handlers.click();
  await new Promise(setImmediate);
  assert.equal(element('#telegram-confirm-link').hidden,false);
  assert.match(element('#telegram-status').textContent,/Alice TG/);
  account='bob';
  await telegram.initialize({getIdToken:async()=>'bob-token',email:'bob@example.com'},()=>({}));
  assert.equal(element('#telegram-open-bot').hidden,true);
  assert.equal(element('#telegram-open-bot').href,undefined);
  assert.equal(element('#telegram-confirm-link').hidden,true);
  assert.doesNotMatch(element('#telegram-status').textContent,/Alice TG/);
});
