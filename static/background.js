/* Browser storage contains job IDs only; the server owns execution and results. */
window.cvBackground = (() => {
  const titles = {'/api/analyze': 'Análisis de vacante', '/api/bank/sync': 'Sincronización del banco',
    '/api/draft': 'Generación de CV', '/api/profile/information': 'Guardar información',
    '/api/export/pdf': 'Guardar PDF', '/api/export/docx': 'Guardar Word',
    '/api/gmail/send': 'Enviar postulación', '/api/applications': 'Guardar postulación'};
  let options, owner = '', records = [], restoring = false;
  const watchers = new Map(), rows = new Map(), delivered = new Set();
  const progressListeners = new Map();
  const panel = document.querySelector('#background-panel');
  const list = document.querySelector('#background-processes');
  const button = document.querySelector('#enable-notifications');
  const notice = document.querySelector('#notifications-status');
  const enabled = () => Boolean(options?.enabled && options.user());
  function persist() {
    try { localStorage.setItem(`cv-processes-${owner}`, JSON.stringify(records.slice(-20))); } catch { /* Work stays on the server. */ }
  }
  function remember(record) {
    if (!records.some(item => item.id === record.id)) records.push(record);
    persist();
  }
  function render(record, job) {
    panel.hidden = false;
    let row = rows.get(record.id);
    if (!row) { row = document.createElement('div'); row.className = 'background-process'; list.prepend(row); rows.set(record.id, row); }
    row.replaceChildren();
    const title = document.createElement('strong'); title.textContent = titles[job.path || record.path] || 'Proceso';
    const detail = document.createElement('p'); detail.textContent = `${job.progress || 1}% · ${job.stage || 'Solicitud guardada'}`;
    const progress = document.createElement('progress'); progress.max = 100; progress.value = job.progress || 1;
    progress.setAttribute('aria-label', title.textContent); row.append(title, progress, detail);
    if (job.state === 'failed') { detail.textContent = job.error || 'El proceso necesita atención.'; row.classList.add('process-failed'); }
    if (job.state === 'done' && job.result?.driveUrl?.startsWith('https://drive.google.com/')) {
      const link = document.createElement('a'); link.href = job.result.driveUrl; link.target = '_blank'; link.rel = 'noopener'; link.textContent = 'Abrir CV guardado en Drive'; row.append(link);
    }
    if (job.state === 'done' && ['/api/analyze', '/api/draft'].includes(job.path || record.path)) {
      const open = document.createElement('button'); open.type = 'button'; open.className = 'text-button';
      open.textContent = (job.path || record.path) === '/api/draft' ? 'Ver este CV' : 'Ver este an\u00e1lisis';
      open.addEventListener('click', () => window.dispatchEvent(new CustomEvent('cv-background-result', {
        detail: {path: job.path || record.path, result: job.result}
      }))); row.append(open);
    }
    if (job.state === 'done' && job.operation === 'export') {
      const download = document.createElement('button'); download.type = 'button'; download.className = 'text-button'; download.textContent = 'Descargar archivo';
      download.addEventListener('click', () => downloadResult(job.result).catch(error => { detail.textContent = error.message; })); row.append(download);
    }
  }
  const status = id => options.request(`/api/background/jobs/${id}`, {});
  async function watch(record, recover = false, onProgress = null) {
    const watchOwner = owner;
    if (watchers.has(record.id)) {
      if (onProgress) {
        if (!progressListeners.has(record.id)) progressListeners.set(record.id, new Set());
        progressListeners.get(record.id).add(onProgress);
      }
      return watchers.get(record.id);
    }
    const finish = recover ? Object.assign(() => {}, {update() {}}) : onProgress ? Object.assign(() => {}, {update: onProgress}) : window.cvLoading.start(titles[record.path] || 'Recuperando proceso');
    finish.update(1, 'Solicitud guardada; el servidor seguirá trabajando', true);
    const promise = (async () => {
      let failures = 0, progress = 1, activeThisSession = !recover;
      for (;;) {
        if (!enabled() || owner !== watchOwner) throw new Error('La sesión cambió. El proceso permanece en su cuenta original.');
        try {
          const job = await status(record.id); failures = 0;
          if (owner !== watchOwner) throw Object.assign(new Error('La sesión cambió.'), {terminal:true});
          record.path = job.path || record.path;
          // A job may have finished while this browser was closed.
          if (!activeThisSession && ['done', 'failed'].includes(job.state)) {
            record.state = job.state; persist(); delivered.add(record.id);
            return job.result;
          }
          activeThisSession = true;
          render(record, job);
          progress = Math.min(job.state === 'done' ? 100 : 99, job.progress || progress);
          finish.update(progress, job.stage, true);
          for (const listener of progressListeners.get(record.id) || []) listener(progress, job.stage, true);
          if (job.state === 'done' || job.state === 'failed') {
            record.state = job.state; persist();
            if (job.state === 'failed') throw Object.assign(new Error(job.error || 'No se pudo completar el proceso.'), {terminal: true});
            if (finish.complete) await finish.complete();
            if (owner !== watchOwner) throw Object.assign(new Error('La sesión cambió.'), {terminal:true});
            delivered.add(record.id);
            if (recover && !['/api/analyze', '/api/draft'].includes(record.path)) window.dispatchEvent(new CustomEvent('cv-background-result', {detail: {path: record.path, result: job.result}}));
            return job.result;
          }
        } catch (error) {
          if (error.terminal) throw error;
          finish.update(progress, 'Reconectando. El proceso continúa en el servidor.', true);
          if (++failures > 5) throw new Error('No se pudo consultar el progreso. Vuelve a abrir la app para recuperar el proceso guardado.');
        }
        await new Promise(resolve => setTimeout(resolve, document.hidden ? 10000 : 2000));
      }
    })();
    watchers.set(record.id, promise);
    try { return await promise; } finally { watchers.delete(record.id); progressListeners.delete(record.id); finish(); }
  }
  async function run(path, payload, headers = {}, onProgress = null) {
    const startedOwner = owner;
    const existing = records.find(record => record.path === path && !['done', 'failed'].includes(record.state));
    if (path === '/api/bank/sync' && existing) return watch(existing, false, onProgress);
    const record = {id: `web-${crypto.randomUUID()}`, path, state: 'queued'};
    remember(record); render(record, {progress: 1, stage: 'Guardando la solicitud en el servidor'});
    try {
      const submitted = await options.request('/api/background/jobs', {path, payload, request_id: record.id.slice(4)}, headers);
      record.id = submitted.job_id; persist();
    } catch (error) {
      if (error.terminal || startedOwner !== owner) throw error;
      if (error.status && error.status < 500) {
        record.state = 'failed'; persist(); render(record, {state: 'failed', error: error.message}); throw error;
      }
      notice.textContent = 'Comprobando si el servidor recibió la solicitud.';
    }
    return watch(record, false, onProgress);
  }
  async function downloadResult(result) {
    const startedOwner = owner;
    const response = await options.file(result.download_url);
    if (!response.ok) throw new Error('No se pudo recuperar el archivo. Puedes abrir la copia guardada en Drive.');
    const blob = await response.blob();
    if (startedOwner !== owner) throw new Error('La cuenta cambió. Descarga el archivo desde su cuenta original.');
    const link = document.createElement('a'); link.href = URL.createObjectURL(blob); link.download = result.fileName;
    link.click(); setTimeout(() => URL.revokeObjectURL(link.href), 30000);
  }
  async function resume(id = '') {
    if (!enabled() || restoring) return;
    restoring = true;
    try {
      if (/^web-[0-9a-f-]{36}$/.test(id)) remember({id, path: '', state: 'queued'});
      for (const record of records) {
        if (!['done', 'failed'].includes(record.state)) {
          watch(record, true).catch(error => { notice.textContent = error.message; });
        }
      }
    } finally { restoring = false; }
  }
  async function registerSubscription() {
    const registration = await navigator.serviceWorker.ready;
    const config = await options.request('/api/notifications/config', {});
    const base64 = config.public_key.replaceAll('-', '+').replaceAll('_', '/');
    const key = Uint8Array.from(atob(base64), c => c.charCodeAt(0));
    const subscription = await registration.pushManager.getSubscription() || await registration.pushManager.subscribe({userVisibleOnly: true, applicationServerKey: key});
    await options.request('/api/notifications/subscribe', subscription.toJSON());
    notice.textContent = 'Notificaciones activadas. Recibirás un aviso al terminar cada proceso.';
  }
  async function initialize(settings) {
    const nextOwner = settings.user()?.uid || '';
    const sameOwner = Boolean(owner && owner === nextOwner);
    if (owner && owner !== nextOwner && 'serviceWorker' in navigator) {
      const registration = await navigator.serviceWorker.getRegistration();
      const subscription = await registration?.pushManager.getSubscription();
      if (subscription) await subscription.unsubscribe();
      watchers.clear(); progressListeners.clear();
    }
    options = settings;
    if (sameOwner) { await resume(); return; }
    owner = nextOwner; delivered.clear();
    rows.clear(); list.replaceChildren(); records = [];
    button.disabled = !enabled(); panel.hidden = !enabled();
    if (!enabled()) return;
    try { records = JSON.parse(localStorage.getItem(`cv-processes-${owner}`) || '[]').filter(r => /^web-[0-9a-f-]{36}$/.test(r.id)); } catch { records = []; }
    notice.textContent = 'Activa las notificaciones para recibir un aviso aunque cierres esta página.';
    if ('serviceWorker' in navigator) {
      navigator.serviceWorker.register('/sw.js').then(() => {
        if ('Notification' in window && 'PushManager' in window && Notification.permission === 'granted') return registerSubscription();
      }).catch(() => { notice.textContent = 'Los procesos continúan en el servidor; las notificaciones aún no están conectadas.'; });
    }
    resume(new URL(location.href).searchParams.get('job') || '').catch(error => { notice.textContent = error.message; });
  }
  button.addEventListener('click', async () => {
    if (!enabled()) return;
    if (!('Notification' in window && 'PushManager' in window)) { notice.textContent = 'Este navegador no admite notificaciones push.'; return; }
    try {
      const permission = await Notification.requestPermission();
      if (permission !== 'granted') { notice.textContent = 'Permite las notificaciones en la configuración del navegador para recibir avisos.'; return; }
      await navigator.serviceWorker.register('/sw.js'); await registerSubscription();
    } catch { notice.textContent = 'No se pudieron activar las notificaciones. Tus procesos seguirán en el servidor.'; }
  });
  navigator.serviceWorker?.addEventListener('message', event => {
    if (event.data?.type === 'cv-process-finished') resume(event.data.job_id).catch(() => {});
  });
  document.addEventListener('visibilitychange', () => { if (!document.hidden) resume().catch(() => {}); });
  window.addEventListener('online', () => resume().catch(() => {}));
  return {initialize, enabled, handles: path => path in titles, run, downloadResult,
    hasActive: () => records.some(record => !['done', 'failed'].includes(record.state))};
})();
