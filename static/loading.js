/* A shared loading window for concurrent and nested operations. */
window.cvLoading = (() => {
  const operations = new Map();
  const overlay = document.querySelector('#loading-overlay');
  const label = document.querySelector('#loading-label');
  const bar = document.querySelector('#loading-progress');
  const percent = document.querySelector('#loading-percent');
  const detail = document.querySelector('#loading-detail');
  const hideButton = document.querySelector('#loading-background');
  const background = [...document.querySelectorAll('main, header')];
  let previousFocus = null;
  let previousInert = [];
  let dismissed = false;
  let animation = 0;
  const now = () => performance.now();
  function advance(operation, target) {
    // Every integer is applied in order. A fast completion may paint several in
    // one frame; never hold a finished request open to slow down its counter.
    while (operation.display < target) {
      operation.display += 1;
      if ([...operations.values()][0] === operation) {
        bar.value = operation.display;
        percent.textContent = `${operation.display}%`;
      }
    }
  }
  function animate(timestamp) {
    animation = 0;
    const active = [...operations.values()][0];
    if (!active) return;
    if (active.display < active.progress) {
      const fraction = Math.min(1, (timestamp - active.changedAt) / active.duration);
      advance(active, Math.floor(active.from + (active.progress - active.from) * fraction));
      render();
      if (active.display < active.progress) animation = requestAnimationFrame(animate);
    }
  }
  function unlock() {
    background.forEach((element, index) => { element.inert = previousInert[index]; });
    document.body.classList.remove('is-loading');
  }
  hideButton.addEventListener('click', () => { dismissed = true; render(); unlock(); });
  function render() {
    const active = [...operations.values()][0];
    const current = [...operations.values()].at(-1);
    label.textContent = current?.message || 'Cargando';
    overlay.hidden = operations.size === 0 || dismissed;
    bar.value = active?.display || 1;
    percent.textContent = `${active?.display || 1}%`;
    detail.textContent = active?.stage || 'Solicitud iniciada';
    hideButton.hidden = !active?.durable;
  }
  function start(message = 'Cargando') {
    if (!operations.size) {
      dismissed = false;
      previousFocus = document.activeElement;
      previousInert = background.map(element => element.inert);
      background.forEach(element => { element.inert = true; });
      document.body.classList.add('is-loading');
    }
    const key = Symbol('loading');
    operations.set(key, {message, progress: 1, display: 1, stage: 'Solicitud iniciada', durable: false,
      reportedAt: now(), changedAt: now(), from: 1, duration: 1});
    render();
    if (!overlay.hidden) overlay.focus({preventScroll: true});
    let finished = false;
    const finish = () => {
      if (finished) return;
      finished = true;
      operations.delete(key);
      if (!operations.size && animation) { cancelAnimationFrame(animation); animation = 0; }
      render();
      if (!operations.size) {
        background.forEach((element, index) => { element.inert = previousInert[index]; });
        document.body.classList.remove('is-loading');
        if (previousFocus?.isConnected && !previousFocus.disabled) previousFocus.focus({preventScroll: true});
      }
    };
    finish.update = (progress, stage, durable = false) => {
      const operation = operations.get(key);
      if (!operation) return;
      const target = Math.max(operation.progress, Math.min(99, Number(progress) || 1));
      if (target > operation.progress) {
        const timestamp = now();
        operation.duration = Math.max(1, Math.min(600, timestamp - operation.reportedAt));
        operation.from = operation.display;
        operation.changedAt = timestamp;
        operation.reportedAt = timestamp;
        operation.progress = target;
        if (!animation) animation = requestAnimationFrame(animate);
      }
      operation.stage = stage || operation.stage;
      operation.durable = durable;
      render();
    };
    finish.complete = async () => {
      const operation = operations.get(key);
      if (!operation) return;
      operation.progress = 100;
      advance(operation, 100);
      operation.stage = 'Completado';
      render();
      // Allow the browser to paint confirmation; no countdown after completion.
      if (!overlay.hidden) await new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(resolve)));
    };
    return finish;
  }
  async function run(message, work) {
    const finish = start(message);
    try { const result = await work(finish.update); await finish.complete(); return result; }
    finally { finish(); }
  }
  return {start, run};
})();
