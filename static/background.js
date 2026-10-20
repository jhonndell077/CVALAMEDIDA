/* Process results belong to the current signed-in page session only. */
window.cvBackground = (() => {
  const titles = {'/api/analyze': 'Análisis de vacante', '/api/bank/sync': 'Sincronización del banco',
    '/api/draft': 'Generación de CV', '/api/profile/information': 'Guardar información',
    '/api/export/pdf': 'Guardar PDF', '/api/export/docx': 'Guardar Word',
    '/api/gmail/send': 'Enviar postulación', '/api/applications': 'Guardar postulación'};
  let options, owner = '', records = [], restoring = false, generation = 0;
  const watchers = new Map(), rows = new Map(), delivered = new Set();
  const progressListeners = new Map();
  const wakeups = new Map();
  // Retry identity stays in this account's page memory, never browser storage.
  // Reusing it lets the server reconcile an uncertain dispatch without repeating work.
  const submissions = new Map();
  const panel = document.querySelector('#background-panel');
  const list = document.querySelector('#background-processes');
  const button = document.querySelector('#enable-notifications');
  const notice = document.querySelector('#notifications-status');
  const toast = document.querySelector('#process-completed-toast');
  const sessions = new Map();
  const jobs = new Map();
  const pageId = `${Date.now()}-${Math.random().toString(36).slice(2)}`;
  let toastTimer = 0, queuedToast = false;
  function completedToast(recordIds = []) {
    for (const id of recordIds) {
      const record = records.find(item => item.id === id);
      if (record) record.pendingNotice = true;
    }
    if (recordIds.length) persist();
    if (!toast) return;
    if (document.hidden) { queuedToast = true; return; }
    if (window.cvLoading.notificationReady && !window.cvLoading.notificationReady()) {
      queuedToast = true;
      clearTimeout(toastTimer);
      toastTimer = setTimeout(completedToast, 250);
      return;
    }
    queuedToast = false;
    clearTimeout(toastTimer);
    toast.hidden = false;
    toast.textContent = 'Estado Completado';
    try { toast.showPopover?.(); } catch { toast.removeAttribute('popover'); }
    records.filter(record => record.pendingNotice).forEach(record => {
      record.pendingNotice = false; record.announced = true;
    });
    persist();
    toastTimer = setTimeout(() => { toast.hidePopover?.(); toast.hidden = true; }, 5000);
  }
  const enabled = () => Boolean(options?.enabled && options.user());
  function persist() {
    // Older versions persisted job IDs and replayed previous CVs at login.
    // Keep live work in memory; the server still owns execution and results.
    try { localStorage.removeItem(`cv-processes-${owner}`); } catch { /* Storage can be unavailable. */ }
  }
  function remember(record) {
    if (!records.some(item => item.id === record.id)) records.push(record);
    persist();
  }
  function render(record, job) {
    jobs.set(record.id, job);
    const members = record.actionId ? records.filter(item => item.actionId === record.actionId) : [record];
    const rowKey = record.actionId || record.id;
    const failed = members.some(item => jobs.get(item.id)?.state === 'failed');
    const pending = members.some(item => !['done','failed'].includes(jobs.get(item.id)?.state || item.state));
    const running = record.sessionId != null && window.cvLoading.currentSession?.() === record.sessionId;
    const completed = !failed && !pending && !running && job.state === 'done';
    const displayed = {...job, state:failed?'failed':completed?'done':'processing',
      progress:completed?100:Math.min(99, job.progress || 1)};
    panel.hidden = false;
    let row = rows.get(rowKey);
    if (!row) { row = document.createElement('div'); row.className = 'background-process'; list.prepend(row); rows.set(rowKey, row); }
    row.replaceChildren();
    row.classList.toggle('process-done', displayed.state === 'done');
    row.classList.toggle('process-failed', displayed.state === 'failed');
    const title = document.createElement('strong'); title.textContent = record.actionTitle || titles[job.path || record.path] || record.title || 'Proceso';
    const detail = document.createElement('p'); detail.textContent = displayed.state === 'done'
      ? '100% · Estado Completado' : `${displayed.progress}% · ${job.stage || 'Solicitud guardada'}`;
    const progress = document.createElement('progress'); progress.max = 100; progress.value = displayed.progress;
    progress.setAttribute('aria-label', title.textContent); row.append(title, progress, detail);
    if (job.state === 'failed') {
      detail.textContent = job.error || 'El proceso necesita atención.';
      const code = job.errorCode || job.code;
      if (typeof code === 'string' && /^[a-z][a-z0-9_]{0,79}$/.test(code)) detail.textContent += ` · Código: ${code}`;
      if (typeof job.correlationId === 'string' && /^[a-f0-9-]{32,36}$/.test(job.correlationId)) detail.textContent += ` · Referencia: ${job.correlationId}`;
      row.classList.add('process-failed');
    }
    if ((job.path || record.path) === '/api/bank/sync' && job.result?.warnings?.length) {
      const review = document.createElement('details');
      review.open = job.state === 'failed';
      const summary = document.createElement('summary');
      summary.textContent = job.state === 'failed' ? 'Documentos que requieren revisión' : 'Observaciones del banco';
      review.append(summary);
      for (const warning of job.result.warnings) {
        const item = document.createElement('p');
        item.textContent = `${warning.severity === 'notice' ? 'Observación' : 'Requiere revisión'} · ${warning.name || 'Banco'}: ${warning.message || 'Consulta el documento original.'}`;
        if (typeof warning.file_id === 'string' && /^[A-Za-z0-9_-]+$/.test(warning.file_id)) {
          const link = document.createElement('a');
          link.href = 'https://drive.google.com/file/d/' + encodeURIComponent(warning.file_id) + '/view';
          link.target = '_blank'; link.rel = 'noopener'; link.textContent = 'Abrir documento'; item.append(' ', link);
        }
        review.append(item);
      }
      row.append(review);
    }
    for (const member of members) {
    const job = jobs.get(member.id) || {};
    const record = member;
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
  }
  async function status(id) {
    const controller = typeof AbortController === 'undefined' ? null : new AbortController();
    let timeout, interrupt;
    const interrupted = new Promise((resolve, reject) => {
      interrupt = () => {
        controller?.abort();
        reject(Object.assign(new Error('Recuperando la conexión del proceso.'), {wakeup:true}));
      };
      timeout = setTimeout(interrupt, 20000);
      wakeups.set(id, interrupt);
    });
    try {
      return await Promise.race([options.request(`/api/background/jobs/${id}`, {}, {},
        {signal:controller?.signal}), interrupted]);
    } finally {
      clearTimeout(timeout);
      if (wakeups.get(id) === interrupt) wakeups.delete(id);
    }
  }
  function pause(id, milliseconds) {
    return new Promise(resolve => {
      const finish = () => { clearTimeout(timer); if (wakeups.get(id) === finish) wakeups.delete(id); resolve(); };
      const timer = setTimeout(finish, milliseconds);
      wakeups.set(id, finish);
    });
  }
  async function watch(record, recover = false, onProgress = null) {
    const watchOwner = owner;
    const watchGeneration = generation;
    const current = () => owner === watchOwner && generation === watchGeneration;
    if (watchers.has(record.id)) {
      if (onProgress) {
        if (!progressListeners.has(record.id)) progressListeners.set(record.id, new Set());
        progressListeners.get(record.id).add(onProgress);
      }
      return watchers.get(record.id);
    }
    const finish = recover ? Object.assign(() => {}, {update() {}}) : onProgress ? Object.assign(() => {}, {update: onProgress}) : window.cvLoading.start(titles[record.path] || 'Recuperando proceso');
    finish.update(1, 'Solicitud guardada; el servidor seguirá trabajando', true);
    render(record, jobs.get(record.id) || {progress:1, stage:'Recuperando el estado del proceso'});
    const promise = (async () => {
      let failures = 0, progress = 1;
      const wasPending = !['done', 'failed'].includes(record.state);
      for (;;) {
        if (!enabled() || !current()) throw new Error('La sesión cambió. El proceso permanece en su cuenta original.');
        try {
          const job = await status(record.id); failures = 0;
          if (!current()) throw Object.assign(new Error('La sesión cambió.'), {terminal:true});
          record.path = job.path || record.path;
          render(record, job);
          progress = Math.min(job.state === 'done' ? 100 : 99, job.progress || progress);
          finish.update(progress, job.stage, true);
          for (const listener of progressListeners.get(record.id) || []) listener(progress, job.stage, true);
          if (job.state === 'done' || job.state === 'failed') {
            record.state = job.state; persist();
            if (job.state === 'failed') throw Object.assign(new Error(job.error || 'No se pudo completar el proceso.'), {terminal: true,
              code:job.errorCode || job.code, stage:job.stage, correlationId:job.correlationId, operationId:job.operationId,
              retryable:job.retryable, safeNextAction:job.safeNextAction, externalOutcome:job.externalOutcome, buildId:job.buildId,
              ...(record.path === '/api/bank/sync' && job.result ? {bankStatus:job.result} : {})});
            if (finish.complete) await finish.complete();
            if (!current()) throw Object.assign(new Error('La sesión cambió.'), {terminal:true});
            delivered.add(record.id);
            if (!window.cvLoading.currentSession?.()) notice.textContent = '100% · Estado Completado';
            if (record.pendingNotice || (recover && wasPending || record.backgrounded && !window.cvLoading.currentSession?.()) && !record.announced) {
              completedToast([record.id]);
            }
            if (recover && !['/api/analyze', '/api/draft'].includes(record.path)) window.dispatchEvent(new CustomEvent('cv-background-result', {detail: {path: record.path, result: job.result}}));
            return job.result;
          }
        } catch (error) {
          if (error.terminal) throw error;
          if (!current()) throw Object.assign(new Error('La sesión cambió.'), {terminal:true});
          if (error.wakeup) continue;
          if ([400, 401, 403, 404].includes(error.status)) {
            const message = error.status === 404 ? 'Este proceso ya no está disponible. Puedes iniciar una nueva acción.' : error.message;
            record.state = error.status === 401 || error.status === 403 ? 'needs-auth' : 'failed';
            persist(); render(record, {state:'failed', progress, error:message});
            throw Object.assign(new Error(message), {terminal:true});
          }
          finish.update(progress, 'Reconectando. El proceso continúa en el servidor.', true);
          failures++;
          render(record, {...jobs.get(record.id), stage:'Esperando conexión. Reintentando automáticamente.'});
          notice.textContent = 'Recuperando el progreso. No necesitas repetir la acción.';
        }
        await pause(record.id, document.hidden || failures > 5 ? 10000 : 2000);
      }
    })();
    watchers.set(record.id, promise);
    try { return await promise; }
    catch (error) { finish.cancel?.(); throw error; }
    finally {
      if (current()) { watchers.delete(record.id); progressListeners.delete(record.id); finish(); }
    }
  }
  async function run(path, payload, headers = {}, onProgress = null) {
    const startedOwner = owner;
    const startedGeneration = generation;
    const current = () => startedOwner === owner && startedGeneration === generation;
    const existing = records.find(record => record.path === path && !['done', 'failed'].includes(record.state));
    if (path === '/api/bank/sync' && existing) return watch(existing, false, onProgress);
    const requestedOperation = headers['X-CV-Operation-ID'];
    const submissionKey = JSON.stringify([path, payload]);
    const retry = submissions.get(submissionKey);
    const identifier = retry?.id.slice(4) || (path === '/api/bank/sync' && /^[a-f0-9]{8}(?:-[a-f0-9]{4}){3}-[a-f0-9]{12}$/i.test(requestedOperation || '')
      ? requestedOperation : crypto.randomUUID());
    const record = retry || {id: `web-${identifier}`, path, state: 'queued'};
    record.state = 'queued';
    const currentSession = window.cvLoading.currentSession?.();
    if (currentSession != null) { record.sessionId = currentSession; record.actionId = `${pageId}:${currentSession}`; }
    const sessionId = window.cvLoading.backgroundSession?.();
    if (sessionId != null) {
      record.backgrounded = true; record.sessionId = sessionId;
      const local = sessions.get(sessionId);
      if (local) { rows.get(local.id)?.remove(); rows.delete(local.id); sessions.delete(sessionId); }
    }
    remember(record); render(record, {progress: 1, stage: 'Guardando la solicitud en el servidor'});
    try {
      let submitted;
      for (let attempt = 0; ; attempt++) {
        if (!current()) throw Object.assign(new Error('La sesión cambió.'), {terminal:true});
        try {
          submitted = await options.request('/api/background/jobs', {path, payload, request_id: record.id.slice(4)}, {...headers, 'X-CV-Operation-ID': record.id.slice(4)});
          break;
        } catch (error) {
          // Only a confirmed pre-admission conflict permits automatic replay.
          // Keep the same durable ID and never retry an uncertain external effect.
          if (error.status !== 409 || error.code !== 'account_write_busy' || error.externalOutcome !== 'not_started' || attempt >= 4) throw error;
          notice.textContent = 'Esperando a que termine la operación anterior. Tus datos se conservan.';
          await pause(record.id, Math.min(4000, 1000 * 2 ** attempt));
        }
      }
      if (!current()) throw Object.assign(new Error('La sesión cambió.'), {terminal:true});
      record.id = submitted.job_id; persist();
      submissions.delete(submissionKey);
    } catch (error) {
      if (error.terminal || !current()) throw error;
      if (!error.status || error.status >= 500 || error.code === 'account_write_busy' && error.externalOutcome === 'not_started') {
        // Never infer admission from a 5xx or connection loss. An explicit retry
        // uses the same ID; the server alone decides whether execution exists.
        submissions.set(submissionKey, record);
      } else {
        submissions.delete(submissionKey);
      }
      record.state = 'failed'; persist();
      render(record, {state:'failed', progress:1, error:error.message});
      notice.textContent = error.code === 'job_dispatch_unavailable'
        ? 'La solicitud está guardada. Reintenta la misma acción para recuperar su despacho sin duplicarla.'
        : error.status ? error.message : 'No se confirmó la recepción. Reintenta la misma acción para comprobarla sin duplicarla.';
      throw error;
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
      // A push notification may refer to an earlier login. Only reconnect work
      // explicitly started in this session; never import its historical result.
      if (id && !records.some(record => record.id === id)) return;
      for (const record of records) {
        if (record.pendingNotice || !['done', 'failed'].includes(record.state) ||
            record.backgrounded && record.actionId && !rows.has(record.actionId)) {
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
    if (!sameOwner) generation++;
    const initializedGeneration = generation;
    if (owner && owner !== nextOwner) {
      wakeups.forEach(wake => wake()); wakeups.clear();
      watchers.clear(); progressListeners.clear();
      if ('serviceWorker' in navigator) {
        try {
          const registration = await navigator.serviceWorker.getRegistration();
          const subscription = await registration?.pushManager.getSubscription();
          if (subscription) await subscription.unsubscribe();
        } catch { /* Account cleanup must not depend on the push provider. */ }
        if (initializedGeneration !== generation) return;
      }
    }
    options = settings;
    if (sameOwner) { await resume(); return; }
    // Startup itself can already have been moved to the background before the
    // first account is initialized. Keep that local loading session.
    if (owner) sessions.clear();
    owner = nextOwner; delivered.clear();
    queuedToast = false; clearTimeout(toastTimer); if (toast) { toast.hidePopover?.(); toast.hidden = true; }
    rows.clear(); jobs.clear(); submissions.clear(); list.replaceChildren(); records = [];
    button.disabled = !enabled(); panel.hidden = !enabled();
    for (const record of sessions.values()) render(record, {progress:1, stage:record.title});
    if (!enabled()) return;
    persist();
    notice.textContent = 'Activa las notificaciones para recibir un aviso aunque cierres esta página.';
    if ('serviceWorker' in navigator) {
      navigator.serviceWorker.register('/sw.js').then(() => {
        if ('Notification' in window && 'PushManager' in window && Notification.permission === 'granted') return registerSubscription();
      }).catch(() => { notice.textContent = 'Los procesos continúan en el servidor; las notificaciones aún no están conectadas.'; });
    }
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
    if (event.data?.type === 'cv-notification-status') {
      event.ports?.[0]?.postMessage({ready: window.cvLoading?.notificationReady?.() ?? false});
      return;
    }
    if (event.data?.type === 'cv-process-finished') resume(event.data.job_id).catch(() => {});
  });
  window.addEventListener('cv-loading-background', event => {
    const {id, message} = event.detail;
    const active = records.filter(record => record.sessionId === id || !['done','failed'].includes(record.state));
    if (active.length) {
      active.forEach(record => { record.backgrounded = true; record.sessionId = id; record.actionTitle = message; }); persist();
    } else {
      const record = {id:`loading-${id}`, path:'', title:message};
      sessions.set(id, record);
      render(record, {progress:1, stage:message});
    }
  });
  window.addEventListener('cv-loading-finished', event => {
    const {id, message, success} = event.detail;
    const associated = records.filter(record => record.sessionId === id);
    const local = sessions.get(id);
    if (!local && !associated.length) return;
    const completed = success && associated.every(record => record.state === 'done');
    if (local) {
      render(local, {state:completed?'done':'failed', progress:completed?100:1,
        error:'El proceso no se completó. Revisa el aviso de la operación.', stage:message});
      sessions.delete(id);
    }
    if (completed) {
      associated.forEach(record => {
        render(record, jobs.get(record.id) || {state:'done',progress:100});
      });
      notice.textContent = '100% · Estado Completado';
      persist();
      if (event.detail.backgrounded !== false) completedToast(associated.map(record => record.id));
    }
  });
  function returnToApp() {
    if (document.hidden) return;
    wakeups.forEach(wake => wake());
    if (queuedToast) completedToast();
    resume().catch(() => {});
  }
  document.addEventListener('visibilitychange', returnToApp);
  window.addEventListener('pageshow', returnToApp);
  window.addEventListener('focus', returnToApp);
  window.addEventListener('online', returnToApp);
  return {initialize, enabled, handles: path => path in titles, run, downloadResult,
    hasActive: () => records.some(record => !['done', 'failed'].includes(record.state))};
})();
