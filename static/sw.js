self.addEventListener('install', () => self.skipWaiting());
self.addEventListener('activate', event => event.waitUntil(self.clients.claim()));
const appWindows = async () => (await self.clients.matchAll({type:'window', includeUncontrolled:true}))
  .filter(client => {
    const url = new URL(client.url);
    return url.origin === self.location.origin && ['/', '/index.html'].includes(url.pathname);
  });
function notificationReady(client) {
  return new Promise(resolve => {
    const channel = new MessageChannel();
    let settled = false;
    const finish = ready => {
      if (settled) return;
      settled = true; clearTimeout(timeout); channel.port1.close();
      resolve(ready);
    };
    const timeout = setTimeout(() => finish(false), 1000);
    channel.port1.onmessage = event => finish(event.data?.ready === true);
    try { client.postMessage({type:'cv-notification-status'}, [channel.port2]); }
    catch { finish(false); }
  });
}
async function notifyCompleted(data, id) {
  const clients = await appWindows();
  clients.forEach(client => client.postMessage({type:'cv-process-finished', job_id:id}));
  // The server is done, but a foreground counter may still be painting 61..100.
  // Recheck windows as well as readiness: closing/hiding the app must not lose
  // the notification or depend on a suspended tab replying to a message.
  for (;;) {
    const visible = (await appWindows()).filter(client => client.visibilityState === 'visible');
    if (!visible.length || (await Promise.all(visible.map(notificationReady))).every(Boolean)) break;
    await new Promise(resolve => setTimeout(resolve, 250));
  }
  await self.registration.showNotification('CV a la medida', {
    body:data.body || 'Tu proceso llegó al 100%. Abre la app para ver el resultado.',
    icon:'/app-icon.png', tag:id, data:{job_id:id, state:'done', progress:100},
  });
}
async function recordAdminPush(data) {
  if(!/^[a-f0-9]{64}$/.test(data.receipt||'') || !/^[A-Za-z0-9_-]{43}$/.test(data.receipt_token||''))return false;
  for(let attempt=0;attempt<3;attempt++) {
    const controller=new AbortController();
    const timeout=setTimeout(()=>controller.abort(),8000);
    try {
      const response=await fetch('/api/admin/connections/push/receipt',{
        method:'POST',headers:{'Content-Type':'application/json'},cache:'no-store',credentials:'omit',
        body:JSON.stringify({receipt:data.receipt,token:data.receipt_token}),signal:controller.signal,
      });
      if(response.ok)return true;
      if(response.status===400||response.status===403)return false;
    }catch(_){ /* A failed acknowledgement must not send the notification twice. */ }
    finally{clearTimeout(timeout);}
  }
  return false;
}
self.addEventListener('push', event => {
  let data = {};
  try { data = event.data?.json() || {}; } catch { /* Ignore malformed payloads. */ }
  if(data.type==='cv-admin-probe' && /^[a-f0-9-]{36}$/.test(data.nonce||'')) {
    event.waitUntil((async()=>{
      await self.registration.showNotification('CV a la medida · Prueba Push',{
        body:'El canal Push respondió en este dispositivo.',tag:'cv-admin-probe',
        data:{admin_probe:true,receipt:data.receipt,receipt_token:data.receipt_token,nonce:data.nonce},
      });
      // Acknowledge directly from the worker: an iOS page can be suspended or
      // absent even though the OS successfully displayed its notification.
      const receiptRecorded=await recordAdminPush(data);
      const windows=await self.clients.matchAll({type:'window',includeUncontrolled:true});
      windows.filter(client=>new URL(client.url).pathname.startsWith('/admin/conexiones'))
        .forEach(client=>client.postMessage({type:'cv-admin-probe-received',nonce:data.nonce,receiptRecorded}));
    })());
    return;
  }
  const id = /^web-[0-9a-f-]{36}$/.test(data.job_id || '') ? data.job_id : '';
  if (!id || data.state !== 'done' || data.progress !== 100) return;
  event.waitUntil(notifyCompleted(data, id));
});
self.addEventListener('notificationclick', event => {
  event.notification.close();
    if(event.notification.data?.admin_probe){event.waitUntil((async()=>{
      await recordAdminPush(event.notification.data);
      await self.clients.openWindow('/admin/conexiones');
    })());return;}
  const id = event.notification.data?.job_id || '';
  const url = new URL('/', self.location.origin);
  if (/^web-[0-9a-f-]{36}$/.test(id)) url.searchParams.set('job', id);
  event.waitUntil(self.clients.matchAll({type: 'window', includeUncontrolled: true}).then(async clients => {
    const client = clients.find(item => new URL(item.url).origin === self.location.origin);
    if (client) { client.postMessage({type: 'cv-process-finished', job_id: id}); return client.focus(); }
    return self.clients.openWindow(url.href);
  }));
});
