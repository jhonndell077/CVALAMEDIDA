/* Shared, frame-by-frame loading feedback for concurrent operations. */
window.cvLoading = (() => {
  const operations = new Map();
  const overlay = document.querySelector('#loading-overlay');
  const label = document.querySelector('#loading-label');
  const bar = document.querySelector('#loading-progress');
  const percent = document.querySelector('#loading-percent');
  const detail = document.querySelector('#loading-detail');
  const hideButton = document.querySelector('#loading-background');
  const background = [...document.querySelectorAll('main, header')];
  let previousFocus = null, previousInert = [], dismissed = false, animation = 0;
  let session = 0, sessionMessage = '', sessionFailed = false;
  const emit = (type, detail) => {
    if (window.dispatchEvent && typeof CustomEvent !== 'undefined') window.dispatchEvent(new CustomEvent(type, {detail}));
  };
  const now = () => performance.now();
  const first = () => operations.values().next().value;
  overlay.addEventListener?.('cancel', event => event.preventDefault());
  function unlock() {
    background.forEach((element, index) => { element.inert = previousInert[index]; });
    document.body.classList.remove('is-loading');
  }
  hideButton.addEventListener('click', () => {
    if (!dismissed) emit('cv-loading-background', {id:session, message:sessionMessage});
    dismissed = true; render(); unlock();
  });
  function render() {
    const active = first();
    const current = [...operations.values()].at(-1);
    label.textContent = current?.message || 'Cargando';
    overlay.hidden = !active || dismissed;
    if (!overlay.hidden && overlay.showModal && !overlay.open) overlay.showModal();
    else if (overlay.hidden && overlay.open) overlay.close();
    bar.value = active?.display || 1;
    percent.textContent = `${active?.display || 1}%`;
    detail.textContent = active ? `${active.completing ? '' : 'Progreso estimado · '}${active.stage}` : '';
    hideButton.hidden = !active;
  }
  function schedule() {
    if (!animation && operations.size) animation = requestAnimationFrame(animate);
  }
  function animate(timestamp) {
    animation = 0;
    const active = first();
    if (!active) return;
    // Estimate only between confirmed stages, slowing as an unknown wait grows.
    // Never claim completion while the operation is still pending.
    const elapsed = Math.max(0, timestamp - active.reportedAt);
    const ceiling = active.progress + (99 - active.progress) * elapsed / (elapsed + active.estimateMs);
    const target = active.completing ? 100 : Math.min(99, Math.floor(ceiling));
    // One integer per painted frame, even after a delayed frame or a 1 -> 100 response.
    if (active.display < target) active.display++;
    render();
    if (active.completing && active.display === 100) {
      // The next frame lets 100% paint before callers close the dialog.
      const resolve = active.resolve;
      animation = requestAnimationFrame(() => { animation = 0; active.resolve = null; resolve?.(); });
    } else if (active.display < 99 || active.completing) schedule();
  }
  function remove(key) {
    const operation = operations.get(key);
    if (!operation) return;
    operations.delete(key);
    operation.resolve?.();
    if (animation) { cancelAnimationFrame(animation); animation = 0; }
    render();
    if (!operations.size) {
      unlock();
      emit('cv-loading-finished', {id:session, message:sessionMessage, success:!sessionFailed, backgrounded:dismissed});
      if (previousFocus?.isConnected && !previousFocus.disabled && (!previousFocus.getClientRects || previousFocus.getClientRects().length)) previousFocus.focus({preventScroll: true});
    } else schedule();
  }
  function start(message = 'Cargando') {
    if (!operations.size) {
      dismissed = false;
      session++; sessionMessage = message; sessionFailed = false;
      previousFocus = document.activeElement;
      previousInert = background.map(element => element.inert);
      background.forEach(element => { element.inert = true; });
      document.body.classList.add('is-loading');
    }
    const key = Symbol('loading');
    operations.set(key, {message, progress:1, display:1, stage:'Solicitud iniciada', durable:false,
      reportedAt:now(), estimateMs:12000, completing:false, completion:null, resolve:null});
    render(); schedule();
    if (!overlay.hidden) overlay.focus({preventScroll:true});
    let closing = null;
    const finish = () => {
      if (closing) return closing;
      const operation = operations.get(key);
      if (!operation) return Promise.resolve();
      // Inner actions do not complete the outer synchronization's counter.
      if (operations.size > 1) { remove(key); return Promise.resolve(); }
      closing = finish.complete().then(() => remove(key));
      return closing;
    };
    finish.cancel = () => { if (operations.has(key)) sessionFailed = true; remove(key); };
    finish.update = (progress, stage, durable = false) => {
      const operation = operations.get(key);
      if (!operation || operation.completing) return;
      const target = Math.max(operation.progress, Math.min(99, Number(progress) || 1));
      if (target > operation.progress) {
        const timestamp = now();
        // Slow stages give subsequent interpolation more time; rapid ones speed it up.
        operation.estimateMs = Math.max(1000, Math.min(60000,
          (timestamp - operation.reportedAt) * (100 - target) / (target - operation.progress)));
        operation.progress = target;
        operation.reportedAt = timestamp;
      }
      operation.stage = stage || operation.stage;
      operation.durable = durable;
      render(); schedule();
    };
    finish.complete = () => {
      const operation = operations.get(key);
      if (!operation) return Promise.resolve();
      if (operation.completion) return operation.completion;
      if (operation !== first() || dismissed || document.hidden) {
        operation.display = operation.progress = 100;
        operation.stage = 'Completado';
        render();
        return Promise.resolve();
      }
      operation.completing = true;
      operation.stage = 'Completado';
      operation.completion = new Promise(resolve => { operation.resolve = resolve; });
      schedule();
      return operation.completion;
    };
    return finish;
  }
  async function run(message, work) {
    const finish = start(message);
    try { const result = await work(finish.update); await finish(); return result; }
    catch (error) { finish.cancel(); throw error; }
  }
  // Hidden tabs cannot paint consecutive frames. Release completed work promptly.
  document.addEventListener?.('visibilitychange', () => {
    if (document.hidden) for (const [key, operation] of operations) if (operation.completing) {
      operation.display = operation.progress = 100;
      render();
      remove(key);
    }
  });
  return {start, run, currentSession: () => operations.size ? session : null,
    backgroundSession: () => dismissed ? session : null,
    notificationReady: () => dismissed || document.hidden ||
    [...operations.values()].every(operation => operation.display === 100)};
})();
