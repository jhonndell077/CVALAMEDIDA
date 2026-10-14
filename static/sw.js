self.addEventListener('install', () => self.skipWaiting());
self.addEventListener('activate', event => event.waitUntil(self.clients.claim()));
self.addEventListener('push', event => {
  let data = {};
  try { data = event.data?.json() || {}; } catch { /* Ignore malformed payloads. */ }
  const id = /^web-[0-9a-f-]{36}$/.test(data.job_id || '') ? data.job_id : '';
  event.waitUntil(Promise.all([
    self.registration.showNotification('CV a la medida', {
      body: data.body || 'Tu proceso terminó. Abre la app para ver el resultado.',
      icon: '/app-icon.png',
      tag: id || 'cv-process', data: {job_id: id},
    }),
    self.clients.matchAll({type: 'window', includeUncontrolled: true}).then(clients => {
      clients.forEach(client => client.postMessage({type: 'cv-process-finished', job_id: id}));
    }),
  ]));
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
