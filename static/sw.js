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
self.addEventListener('push', event => {
  let data = {};
  try { data = event.data?.json() || {}; } catch { /* Ignore malformed payloads. */ }
  const id = /^web-[0-9a-f-]{36}$/.test(data.job_id || '') ? data.job_id : '';
  if (!id || data.state !== 'done' || data.progress !== 100) return;
  event.waitUntil(notifyCompleted(data, id));
});
self.addEventListener('notificationclick', event => {
  event.notification.close();
  const id = event.notification.data?.job_id || '';
  const url = new URL('/', self.location.origin);
  if (/^web-[0-9a-f-]{36}$/.test(id)) url.searchParams.set('job', id);
  event.waitUntil(self.clients.matchAll({type: 'window', includeUncontrolled: true}).then(async clients => {
    const client = clients.find(item => new URL(item.url).origin === self.location.origin);
    if (client) { client.postMessage({type: 'cv-process-finished', job_id: id}); return client.focus(); }
    return self.clients.openWindow(url.href);
  }));
});
