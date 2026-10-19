/* Account evidence comes from the server; never from another browser's storage. */
(() => {
  'use strict';
  let user = null, epoch = 0, pending = null, snapshot = null;
  const container = document.querySelector('#workspace-services');
  const sidebar = document.querySelector('#workspace-sidebar');
  const details = document.createElement('details');
  const summary = document.createElement('summary');
  const status = document.createElement('p');
  const list = document.createElement('ul');
  const refresh = document.createElement('button');
  details.hidden = true;
  details.setAttribute('data-functional-session', '');
  summary.textContent = 'Estado compartido de tu cuenta';
  status.setAttribute('role', 'status');
  refresh.type = 'button';
  refresh.className = 'button button-secondary';
  refresh.textContent = 'Actualizar estado';
  details.append(summary, status, list, refresh);
  container?.append(details);

  function render(stale = false) {
    details.hidden = !user;
    list.replaceChildren();
    if (!snapshot?.available) {
      status.textContent = 'Estado compartido pendiente de actualizar. No se ha confirmado ausencia de errores.';
      return;
    }
    status.textContent = `${snapshot.errorCount} incidencias registradas en la ventana disponible (hasta una hora y 400 eventos globales).${stale ? ' No se pudo actualizar en este dispositivo.' : ''} La ausencia de registros no confirma recuperación ni certifica todos los servicios.`;
    for (const incident of snapshot.incidents) {
      const item = document.createElement('li');
      item.textContent = `${incident.service}: ${incident.endpoint} · código ${incident.code ?? 'sin código'}`;
      list.append(item);
    }
  }

  async function update() {
    if (!user || pending) return;
    const owner = user, expected = epoch;
    const controller = new AbortController();
    const timeout = setTimeout(() => controller.abort(), 10000);
    pending = controller;
    const current = () => epoch === expected && user?.uid === owner.uid;
    try {
      const token = await Promise.race([
        owner.getIdToken(),
        new Promise((_, reject) => controller.signal.addEventListener('abort',
          () => reject(new Error('unavailable')), {once: true}))
      ]);
      if (!current()) return;
      const response = await fetch('/api/session/state', {
        cache: 'no-store', signal: controller.signal,
        headers: {Authorization: `Bearer ${token}`}
      });
      if (!response.ok) throw new Error('unavailable');
      const next = await response.json();
      if (!current()) return;
      if (next.scope !== 'account' || !Array.isArray(next.incidents) ||
          (next.available && (!Number.isInteger(next.errorCount) || next.errorCount < 0))) {
        throw new Error('invalid state');
      }
      snapshot = next;
      render();
    } catch (_) {
      if (current()) render(true);
    } finally {
      clearTimeout(timeout);
      if (pending === controller) pending = null;
    }
  }

  function initialize(next) {
    if (user?.uid === next?.uid) { user = next; return; }
    epoch++;
    pending?.abort();
    pending = null;
    user = next;
    snapshot = null;
    render();
    void update();
  }
  refresh.addEventListener('click', () => void update());
  details.addEventListener('toggle', () => { if (details.open) void update(); });
  window.addEventListener('online', () => void update());
  window.addEventListener('focus', () => { if (details.open && sidebar?.open) void update(); });
  document.addEventListener('visibilitychange', () => {
    if (!document.hidden && details.open && sidebar?.open) void update();
  });
  setInterval(() => { if (!document.hidden && details.open && sidebar?.open) void update(); }, 20000);
  window.cvFunctionalSession = {initialize};
})();
