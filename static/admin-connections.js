const labels={hosting:'Web publicada',api:'API autenticada',google:'Identidad Google / Firebase',drive:'Drive · carpetas',vertex:'Vertex · generación sintética',storage:'Cloud Storage · lectura',tasks:'Cloud Tasks · cola',worker:'Worker · disponibilidad',telegram:'Telegram · bot y webhook',gmail:'Gmail · permiso de envío',push:'Push · entrega pendiente'};
const groups={queue:['tasks','worker'],jobs:['storage','tasks','worker','vertex'],channels:['telegram','gmail','push']};
const states={};
let busy=false,lastSuccess=0,authEpoch=0;
let auth;
let pushNonce='';
async function readyPushWorker(registration){
 const worker=registration.installing||registration.waiting||registration.active;
 if(!worker)throw new Error('worker');
 if(worker.state==='activated')return;
 await new Promise((resolve,reject)=>{
  const finish=error=>{clearTimeout(timer);worker.removeEventListener('statechange',check);error?reject(error):resolve();};
  const check=()=>{if(worker.state==='activated')finish();else if(worker.state==='redundant')finish(new Error('worker'));};
  const timer=setTimeout(()=>finish(new Error('worker timeout')),15000);
  worker.addEventListener('statechange',check);check();
 });
}
async function adminPost(path,body){
 const epoch=authEpoch,user=auth?.currentUser;if(!user)throw new Error('session');
 const token=await user.getIdToken();if(epoch!==authEpoch||user!==auth.currentUser)throw new Error('session');
 const response=await fetch(path,{method:'POST',headers:{Authorization:'Bearer '+token,'X-Requested-With':'XmlHttpRequest','Content-Type':'application/json'},body:JSON.stringify(body),signal:AbortSignal.timeout(30000)});
 if(!response.ok)throw new Error('request');return response.json();
}
function stale(){
 for(const key of Object.keys(states))delete states[key];
 document.querySelectorAll('.node').forEach(node=>{delete node.dataset.state;node.querySelector('.status').textContent='? Sin lectura actual';});
 document.querySelectorAll('[data-resource] .tag').forEach(tag=>{tag.textContent='? Sin lectura actual';tag.style.color='';});
 document.getElementById('checks').replaceChildren();
}
function renderNodes(){
 const combined={...states};
 for(const [key,ids] of Object.entries(groups))combined[key]={state:ids.some(id=>states[id]?.state==='error')?'error':ids.every(id=>states[id]?.state==='ok')?'ok':'unknown'};
 for(const [key,check] of Object.entries(combined)){
  const label=check.state==='ok'?'✅ Prueba correcta':check.state==='error'?'✕ Fallo observado':'? Requiere comprobación';
  const node=document.getElementById('node-'+key);
  if(node){node.dataset.state=check.state;node.querySelector('.status').textContent=label;}
  const tag=document.querySelector('[data-resource="'+key+'"] .tag');
  if(tag){tag.textContent=label+' · ver alcance arriba';tag.style.color=check.state==='ok'?'var(--accent)':check.state==='error'?'var(--bad)':'';}
 }
}
async function update(){
 if(busy||!auth?.currentUser||document.hidden)return;const epoch=authEpoch;busy=true;document.getElementById('refresh').disabled=true;
 try{
  const token=await auth.currentUser.getIdToken();
  if(epoch!==authEpoch)return;
  const started=Date.now();
  const response=await fetch('/api/admin/connections',{headers:{Authorization:'Bearer '+token},cache:'no-store',signal:AbortSignal.timeout(70000)});
  if(epoch!==authEpoch)return;
  if(response.status===401||response.status===403){document.querySelector('main').hidden=true;document.getElementById('access-message').textContent='Acceso reservado al administrador. Inicia sesión con la cuenta autorizada.';throw new Error('access');}
  if(!response.ok)throw new Error('monitor');const data=await response.json();
  if(!Array.isArray(data.checks)||!data.checks.length||!Number.isFinite(Date.parse(data.at))||Date.now()-Date.parse(data.at)>90000)throw new Error('stale');
  const seen=new Set();
  for(const check of data.checks){if(!labels[check.id]||seen.has(check.id)||!['ok','error','unknown'].includes(check.state)||!Number.isFinite(Date.parse(check.checkedAt)))throw new Error('schema');seen.add(check.id);}
  const api=data.checks.find(check=>check.id==='api');if(!api)throw new Error('schema');api.ms=Date.now()-started;
  const hostingStarted=Date.now();
  try{const hosting=await fetch('/',{cache:'no-store',signal:AbortSignal.timeout(12000)});data.checks.unshift({id:'hosting',state:hosting.ok&&(hosting.headers.get('content-type')||'').includes('text/html')?'ok':'error',detail:'Comprobación HTTP de la página principal desde este navegador.',checkedAt:new Date().toISOString(),ms:Date.now()-hostingStarted});}catch(_){data.checks.unshift({id:'hosting',state:'unknown',detail:'No se pudo comprobar la página principal desde este dispositivo.',checkedAt:new Date().toISOString(),ms:Date.now()-hostingStarted});}
  if(epoch!==authEpoch)return;
  document.querySelector('main').hidden=false;document.getElementById('access-message').textContent='Acceso de administrador validado.';
  stale();const container=document.getElementById('checks');container.replaceChildren();
  for(const check of data.checks){
   if(!labels[check.id]||!['ok','error','unknown'].includes(check.state))throw new Error('schema');
   if(Date.now()-Date.parse(check.checkedAt)>(check.validForSeconds||90)*1000){check.state='unknown';check.detail='La comprobación venció; esperando nueva lectura.';}
   states[check.id]=check;
   const card=document.createElement('article'),title=document.createElement('h3'),detail=document.createElement('p'),time=document.createElement('p');
   card.dataset.state=check.state;title.textContent=labels[check.id]+' · '+(check.state==='ok'?'✅':check.state==='error'?'✕':'?');detail.textContent=check.detail;
   time.textContent='Comprobación: '+new Date(check.checkedAt).toLocaleString('es-DO')+' · '+check.ms+' ms';time.className='small';card.append(title,detail,time);container.append(card);
  }
  renderNodes();lastSuccess=Date.parse(data.at);document.getElementById('freshness').textContent='Última lectura: '+new Date(data.at).toLocaleTimeString('es-DO');
 }catch(_){if(epoch!==authEpoch)return;stale();document.getElementById('freshness').textContent='Sin estado actual: revisa tu sesión y la conexión. No se conservan verdes anteriores.';}
 finally{if(epoch===authEpoch){busy=false;document.getElementById('refresh').disabled=false;}}
}
document.getElementById('refresh').addEventListener('click',update);setInterval(update,60000);setInterval(()=>{if(lastSuccess&&Date.now()-lastSuccess>90000){stale();document.getElementById('freshness').textContent='Estado vencido: esperando una nueva lectura.';}},5000);

const message=document.getElementById('access-message');
const actionMessage=document.getElementById('action-message');
try {
 auth=window.firebase.auth();
 auth.onAuthStateChanged(user=>{
  authEpoch++;pushNonce='';actionMessage.textContent='';busy=false;lastSuccess=0;stale();document.querySelector('main').hidden=true;document.getElementById('checks').replaceChildren();
  document.getElementById('signin').disabled=false;document.getElementById('signout').hidden=!user;
  message.textContent=user?'Verificando acceso de administrador…':'Inicia sesión con tu cuenta de administrador.';
  if(user)update();
 });
 document.getElementById('signin').addEventListener('click',()=>{
  const provider=new firebase.auth.GoogleAuthProvider();provider.setCustomParameters({prompt:'select_account'});
  auth.signInWithPopup(provider).catch(error=>{message.textContent='No se pudo iniciar sesión. Permite ventanas emergentes e inténtalo de nuevo.';});
 });
 document.getElementById('signout').addEventListener('click',()=>auth.signOut().catch(()=>{message.textContent='No se pudo cerrar sesión. Inténtalo de nuevo.';}));
 document.getElementById('gmail-check').addEventListener('click',()=>{
  if(!auth.currentUser)return;const epoch=authEpoch;actionMessage.textContent='Comprobando autorización de Drive y Gmail…';
  const provider=new firebase.auth.GoogleAuthProvider();provider.addScope('https://www.googleapis.com/auth/gmail.send');provider.addScope('https://www.googleapis.com/auth/drive.readonly');provider.setCustomParameters({login_hint:auth.currentUser.email,include_granted_scopes:'true'});
  auth.currentUser.reauthenticateWithPopup(provider).then(async result=>{
   if(epoch!==authEpoch)return;const access=result.credential?.accessToken;if(!access)throw new Error('grant');
   const token=await auth.currentUser.getIdToken();if(epoch!==authEpoch)return;
   const response=await fetch('/api/admin/connections/google',{method:'POST',headers:{Authorization:'Bearer '+token,'X-Drive-Access-Token':access,'X-Requested-With':'XmlHttpRequest'},signal:AbortSignal.timeout(30000)});
   if(!response.ok)throw new Error('grant');const grantResult=await response.json();if(epoch===authEpoch){actionMessage.textContent=grantResult.check.detail+' '+(grantResult.drive?.detail||'');update();}
  }).catch(()=>{actionMessage.textContent='No se pudo comprobar Gmail. Autoriza la cuenta administradora y vuelve a intentarlo.';});
 });
 document.getElementById('push-check').addEventListener('click',async()=>{
  if(!auth.currentUser)return;const epoch=authEpoch;
  try{
   if(!('serviceWorker' in navigator)||!('PushManager' in window)||!('Notification' in window))throw new Error('unsupported');
   actionMessage.textContent='Solicitando permiso de notificaciones. Si aparece un aviso del navegador, permite las notificaciones para completar la prueba.';
   if(await Notification.requestPermission()!=='granted')throw new Error('permission');
   if(epoch!==authEpoch)return;
   const registration=await navigator.serviceWorker.register('/sw.js',{updateViaCache:'none'});await registration.update();
   await readyPushWorker(registration);
   const ready=await navigator.serviceWorker.ready;
   let subscription=await ready.pushManager.getSubscription();
   if(!subscription){
    const config=await adminPost('/api/notifications/config',{});
    const encoded=config.public_key.replace(/-/g,'+').replace(/_/g,'/');
    const bytes=Uint8Array.from(atob(encoded+'='.repeat((4-encoded.length%4)%4)),char=>char.charCodeAt(0));
    subscription=await ready.pushManager.subscribe({userVisibleOnly:true,applicationServerKey:bytes});
   }
   if(epoch!==authEpoch)return;
   await adminPost('/api/notifications/subscribe',subscription.toJSON());
   if(epoch!==authEpoch)return;pushNonce=crypto.randomUUID();
   const result=await adminPost('/api/admin/connections/push/test',{endpoint:subscription.endpoint,nonce:pushNonce});
   if(epoch!==authEpoch)return;if(states.push?.state!=='ok')actionMessage.textContent=result.check.detail;
  }catch(_){if(epoch===authEpoch)actionMessage.textContent='No se pudo probar Push. Permite notificaciones en este navegador compatible y vuelve a intentarlo.';}
 });
 if('serviceWorker' in navigator)navigator.serviceWorker.addEventListener('message',async event=>{
  if(event.data?.type!=='cv-admin-probe-received'||!pushNonce||event.data.nonce!==pushNonce||!auth.currentUser)return;
  const epoch=authEpoch,nonce=pushNonce;
  try{const result=await adminPost('/api/admin/connections/push/confirm',{nonce});if(epoch===authEpoch){pushNonce='';states.push=result.check;renderNodes();actionMessage.textContent='✅ Push recibido y confirmación guardada.';update();}}catch(_){if(epoch===authEpoch)actionMessage.textContent='El dispositivo recibió Push. Pulsa Actualizar estado para recuperar su confirmación persistente.';}
 });
 document.addEventListener('visibilitychange',()=>{if(!document.hidden)update();});
} catch (_) {message.textContent='Google no pudo cargarse. Revisa la conexión y recarga la página.';}
