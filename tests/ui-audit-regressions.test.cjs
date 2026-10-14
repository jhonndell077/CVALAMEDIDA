const {test}=require('node:test');
const assert=require('node:assert/strict');
const fs=require('node:fs'),vm=require('node:vm');
test('expired Telegram Drive permissions expose the renewal action',async()=>{
 const elements=new Map();
 const element=id=>{if(!elements.has(id))elements.set(id,{hidden:true,addEventListener(){},removeAttribute(){}});return elements.get(id)};
 const context=vm.createContext({Date,Error,Promise,JSON,document:{querySelector:element},
  google:{accounts:{oauth2:{initCodeClient:()=>({requestCode(){}})}}},
  window:{google:{accounts:{oauth2:{}}},cvLoading:{start:()=>()=>{}},cvDrive:{isConnected:()=>false},cvGmail:{isConnected:()=>false}},
  fetch:async path=>({ok:path!=='/api/telegram/drive/session',status:path==='/api/telegram/drive/session'?409:200,json:async()=>({drive_connected:true,client_id:'fixture',message:'Fixture'})})});
 vm.runInContext(fs.readFileSync('static/telegram.js','utf8'),context);
 await context.window.cvTelegram.initialize({uid:'fixture',email:'fixture@example.com',getIdToken:async()=>''},()=>({}));
 assert.equal(element('#telegram-authorize-drive').hidden,true);
 await assert.rejects(context.window.cvTelegram.synchronize(),/renovar/);
 assert.equal(element('#telegram-authorize-drive').hidden,false);
 assert.equal(element('#telegram-authorize-drive').disabled,false);
});
test('loading uses the top layer, blocks Escape and releases it after failure',async()=>{
 const elements=new Map();const background=[];let closed=0;
 const overlay={hidden:true,open:false,handlers:{},addEventListener:(n,fn)=>overlay.handlers[n]=fn,showModal(){this.open=true},close(){this.open=false;closed++},focus(){}};
 const context=vm.createContext({window:{},document:{activeElement:null,body:{classList:{add(){},remove(){}}},querySelector:s=>s==='#loading-overlay'?overlay:(elements.has(s)?elements.get(s):(elements.set(s,{addEventListener(){}}),elements.get(s))),querySelectorAll:()=>background},performance:{now:()=>0},requestAnimationFrame:fn=>setImmediate(()=>fn(1000)),cancelAnimationFrame:clearImmediate});
 vm.runInContext(fs.readFileSync('static/loading.js','utf8'),context);
 const finish=context.window.cvLoading.start('Fixture');assert.equal(overlay.open,true);
 let prevented=false;overlay.handlers.cancel({preventDefault(){prevented=true}});assert.equal(prevented,true);
 finish();assert.equal(overlay.open,false);assert.equal(closed,1);
 await assert.rejects(context.window.cvLoading.run('Failure',async()=>{throw Error('fixture')}),/fixture/);assert.equal(overlay.hidden,true);assert.equal(overlay.open,false);
});
test('recovered CV preview clears unrelated analysis and keeps a known draft association',async()=>{
 const source=fs.readFileSync('static/app.js','utf8');let listener;
 const context=vm.createContext({window:{addEventListener:(_,fn)=>listener=fn,cvDraftAnalyses:new WeakMap()},state:{analysis:{wrong:true}},renderDraft:async()=>{},jobPanel:{},analysisPanel:{},cvPanel:{},setActiveStep(){}});
 vm.runInContext(source.slice(source.indexOf("window.addEventListener('cv-background-result'"),source.indexOf('function setActiveStep(')),context);
 const draft={position:'Fixture'};await listener({detail:{path:'/api/draft',result:{draft}}});assert.equal(context.state.analysis,null);
 const analysis={correct:true};context.window.cvDraftAnalyses.set(draft,analysis);await listener({detail:{path:'/api/draft',result:{draft}}});assert.equal(context.state.analysis,analysis);
});
