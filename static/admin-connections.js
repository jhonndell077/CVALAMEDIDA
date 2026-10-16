const labels={hosting:'Web publicada',api:'API y exigencia de autenticación'};
let busy=false,lastSuccess=0,authEpoch=0;
let auth;
function stale(){document.querySelectorAll('#node-api,#node-hosting').forEach(node=>{delete node.dataset.state;node.querySelector('.status').textContent='? Estado vencido / sin conexión';});}
async function update(){
 if(busy||!auth?.currentUser||document.hidden)return;const epoch=authEpoch;busy=true;document.getElementById('refresh').disabled=true;
 try{
  const token=await auth.currentUser.getIdToken();
  if(epoch!==authEpoch)return;
  const response=await fetch('/api/admin/connections',{headers:{Authorization:'Bearer '+token},cache:'no-store',signal:AbortSignal.timeout(20000)});
  if(epoch!==authEpoch)return;
  if(response.status===401||response.status===403){document.querySelector('main').hidden=true;document.getElementById('access-message').textContent='Acceso reservado al administrador. Inicia sesión con la cuenta autorizada.';throw new Error('access');}
  if(!response.ok)throw new Error('monitor');const data=await response.json();
  if(!Array.isArray(data.checks)||data.checks.length!==1||!Number.isFinite(Date.parse(data.at))||Date.now()-Date.parse(data.at)>90000)throw new Error('stale');
  const hostingStarted=Date.now();
  try{const hosting=await fetch('/',{cache:'no-store',signal:AbortSignal.timeout(12000)});data.checks.unshift({id:'hosting',state:hosting.ok&&(hosting.headers.get('content-type')||'').includes('text/html')?'ok':'error',detail:'Comprobación HTTP de la página principal desde este navegador.',checkedAt:new Date().toISOString(),ms:Date.now()-hostingStarted});}catch(_){data.checks.unshift({id:'hosting',state:'unknown',detail:'No se pudo comprobar la página principal desde este dispositivo.',checkedAt:new Date().toISOString(),ms:Date.now()-hostingStarted});}
  if(epoch!==authEpoch)return;
  document.querySelector('main').hidden=false;document.getElementById('access-message').textContent='Acceso de administrador validado.';
  const container=document.getElementById('checks');container.replaceChildren();
  for(const check of data.checks){
   if(!labels[check.id]||!['ok','error','unknown'].includes(check.state))throw new Error('schema');
   const node=document.getElementById('node-'+check.id);node.dataset.state=check.state;
   node.querySelector('.status').textContent=check.state==='ok'?'✓ Recurso responde':check.state==='error'?'✕ Fallo observado':'? No se pudo comprobar';
   const card=document.createElement('article'),title=document.createElement('h3'),detail=document.createElement('p'),time=document.createElement('p');
   title.textContent=labels[check.id]+' · '+node.querySelector('.status').textContent;detail.textContent=check.detail;
   time.textContent='Comprobación: '+new Date(check.checkedAt).toLocaleString('es-DO')+' · '+check.ms+' ms';time.className='small';card.append(title,detail,time);container.append(card);
  }
  lastSuccess=Date.parse(data.at);document.getElementById('freshness').textContent='Última lectura: '+new Date(data.at).toLocaleTimeString('es-DO');
 }catch(_){if(epoch!==authEpoch)return;stale();document.getElementById('freshness').textContent='Sin estado actual: revisa tu sesión y la conexión. No se conservan verdes anteriores.';}
 finally{if(epoch===authEpoch){busy=false;document.getElementById('refresh').disabled=false;}}
}
document.getElementById('refresh').addEventListener('click',update);setInterval(update,60000);setInterval(()=>{if(lastSuccess&&Date.now()-lastSuccess>90000){stale();document.getElementById('freshness').textContent='Estado vencido: esperando una nueva lectura.';}},5000);

const message=document.getElementById('access-message');
try {
 auth=window.firebase.auth();
 auth.onAuthStateChanged(user=>{
  authEpoch++;busy=false;lastSuccess=0;stale();document.querySelector('main').hidden=true;document.getElementById('checks').replaceChildren();
  document.getElementById('signin').disabled=false;document.getElementById('signout').hidden=!user;
  message.textContent=user?'Verificando acceso de administrador…':'Inicia sesión con tu cuenta de administrador.';
  if(user)update();
 });
 document.getElementById('signin').addEventListener('click',()=>{
  const provider=new firebase.auth.GoogleAuthProvider();provider.setCustomParameters({prompt:'select_account'});
  auth.signInWithPopup(provider).catch(error=>{message.textContent='No se pudo iniciar sesión. Permite ventanas emergentes e inténtalo de nuevo.';});
 });
 document.getElementById('signout').addEventListener('click',()=>auth.signOut().catch(()=>{message.textContent='No se pudo cerrar sesión. Inténtalo de nuevo.';}));
 document.addEventListener('visibilitychange',()=>{if(!document.hidden)update();});
} catch (_) {message.textContent='Google no pudo cargarse. Revisa la conexión y recarga la página.';}
