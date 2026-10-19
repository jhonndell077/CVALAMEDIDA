(() => {
  'use strict';
  const dialog = document.querySelector('#data-dialog');
  const button = document.querySelector('#data-toggle');
  const panel = document.querySelector('#profile-panel');
  const closeButton = document.querySelector('#data-close');
  const actions = document.querySelector('#data-actions');
  const actionsHome = actions.parentNode;
  const syncButton = document.querySelector('#data-sync');
  const originalSync = document.querySelector('#sync-bank');
  const unavailable = document.querySelector('#data-unavailable');
  // Move the original nodes: all listeners, counters and profile state stay intact.
  document.querySelector('#data-content').append(panel);
  let closing = false;
  let scrollY = 0;
  let bodyStyle;
  let opener;
  const reduced = matchMedia('(prefers-reduced-motion: reduce)');
  function motion(opening) {
    if (reduced.matches || !dialog.animate) return Promise.resolve();
    const frames = [{opacity: 0, transform: 'translateY(24px)'}, {opacity: 1, transform: 'translateY(0)'}];
    return dialog.animate(opening ? frames : frames.slice().reverse(), {duration: 180, easing: 'ease-out'}).finished.catch(() => {});
  }
  function unlock() {
    actionsHome.append(actions);
    if (!bodyStyle) return;
    Object.assign(document.body.style, bodyStyle);
    bodyStyle = null;
    window.scrollTo({top: scrollY, behavior: 'instant'});
    button.setAttribute('aria-expanded', 'false');
    if (opener?.isConnected && !opener.hidden) opener.focus({preventScroll: true});
  }
  async function close() {
    if (!dialog.open || closing) return;
    closing = true;
    try {
      if (window.cvDataPanel && !await window.cvDataPanel.beforeClose()) return;
      if (!dialog.open) return;
      await motion(false);
      dialog.close();
    } finally {
      closing = false;
    }
  }
  button.addEventListener('click', () => {
    if (closing) return;
    if (dialog.open) { close(); return; }
    opener = document.activeElement;
    scrollY = window.scrollY;
    bodyStyle = Object.fromEntries(['position', 'top', 'width', 'overflow', 'paddingRight'].map(key => [key, document.body.style[key]]));
    const gutter = window.innerWidth - document.documentElement.clientWidth;
    Object.assign(document.body.style, {position: 'fixed', top: `-${scrollY}px`, width: '100%', overflow: 'hidden', paddingRight: `${gutter}px`});
    dialog.append(actions); // Keep both controls in the modal's top layer too.
    dialog.showModal(); // Native modal supplies focus containment and inert background.
    button.setAttribute('aria-expanded', 'true');
    closeButton.focus({preventScroll: true});
    motion(true);
    ensureProfile();
  });
  closeButton.addEventListener('click', close);
  dialog.addEventListener('keydown', event => {
    if (event.key !== 'Tab' || event.defaultPrevented) return;
    const focusable = [...dialog.querySelectorAll('button, a[href], input, select, textarea, summary, [tabindex]')]
      .filter(element => !element.disabled && element.tabIndex >= 0 && element.getClientRects().length);
    const first = focusable[0];
    const last = focusable[focusable.length - 1];
    if (event.shiftKey && document.activeElement === first) {
      event.preventDefault(); last?.focus();
    } else if (!event.shiftKey && document.activeElement === last) {
      event.preventDefault(); first?.focus();
    }
  });
  dialog.addEventListener('cancel', event => {event.preventDefault(); close();});
  dialog.addEventListener('close', unlock);
  let outside = false;
  function isOutside(event) {
    const rect = dialog.getBoundingClientRect();
    return event.clientX < rect.left || event.clientX > rect.right || event.clientY < rect.top || event.clientY > rect.bottom;
  }
  dialog.addEventListener('pointerdown', event => {outside = event.target === dialog && isOutside(event);});
  dialog.addEventListener('click', event => {
    if (outside && event.target === dialog && isOutside(event)) close();
    outside = false;
  });
  let signedIn = false;
  let generation = 0;
  let opening = false;
  const content = document.querySelector('#data-content');
  const connectionError = document.createElement('p');
  connectionError.id = 'data-connection-error';
  connectionError.className = 'error';
  connectionError.setAttribute('role', 'alert');
  connectionError.hidden = true;
  content.prepend(connectionError);
  const retry = document.createElement('button');
  retry.id = 'data-retry';
  retry.type = 'button';
  retry.className = 'button button-secondary';
  retry.textContent = 'Cargar mis datos';
  unavailable.after(retry);
  const preview = document.createElement('section');
  preview.id = 'data-preview';
  preview.setAttribute('aria-label', 'Banco profesional');
  const heading = document.createElement('h2');
  heading.textContent = 'Mi árbol de información';
  preview.append(heading);
  const grid = document.createElement('div');
  grid.className = 'profile-tree';
  for (const title of ['Datos personales', 'Experiencias', 'Habilidades', 'Estudios', 'Cursos realizados', 'Proyectos', 'Referencias', 'Datos pendientes de documentar']) {
    const card = document.createElement('div');
    card.className = 'profile-node';
    card.textContent = title;
    card.style.padding = '20px';
    grid.append(card);
  }
  preview.append(grid);
  unavailable.before(preview);
  function availability() {
    const missing = panel.hidden;
    preview.hidden = !missing;
    unavailable.hidden = !missing;
    retry.hidden = !missing || opening;
    unavailable.textContent = opening ? 'Cargando tus datos…' : 'Tu banco se carga aquí al conectar tu cuenta.';
    content.setAttribute('aria-busy', String(opening));
  }
  function ensureProfile() {
    if (opening || !panel.hidden) return;
    const epoch = generation;
    opening = true;
    connectionError.hidden = true;
    availability();
    let task;
    try {
      if (!window.cvDataPanel?.open) throw new Error('La aplicación se está preparando. Pulsa Cargar mis datos para reintentar.');
      task = window.cvDataPanel.open();
    } catch (error) { task = Promise.reject(error); }
    Promise.resolve(task).catch(error => {
      if (epoch !== generation) return;
      connectionError.textContent = error.message || 'No se pudieron cargar tus datos. Reintenta la conexión.';
      connectionError.hidden = false;
    }).finally(() => {
      if (epoch !== generation) return;
      opening = false;
      availability();
    });
  }
  retry.addEventListener('click', ensureProfile);
  window.addEventListener('cv-session-state', event => {
    generation++;
    opening = false;
    signedIn = Boolean(event.detail?.signedIn);
    connectionError.textContent = ''; connectionError.hidden = true;
    availability();
    if (signedIn && dialog.open) ensureProfile();
  });
  window.addEventListener('cv-app-error', event => {
    connectionError.textContent = event.detail?.message || '';
    connectionError.hidden = !connectionError.textContent;
  });
  new MutationObserver(availability).observe(panel, {attributes: true, attributeFilter: ['hidden']});
  availability();
  syncButton.addEventListener('click', () => {
    // Call the action directly: the original button is hidden and can be inert
    // while Datos is modal. Preserve Safari's real user activation for OAuth.
    if (window.cvSynchronizeBank) window.cvSynchronizeBank();
    else originalSync.click();
  });
  const syncAvailability = () => { syncButton.disabled = originalSync.disabled; };
  new MutationObserver(syncAvailability).observe(originalSync, {attributes: true, attributeFilter: ['disabled']});
  syncAvailability();
  let updateBanner;
  const measureBanner = () => {
    document.documentElement.style.setProperty('--cv-update-height', `${updateBanner?.getBoundingClientRect().height || 0}px`);
  };
  const bannerResize = window.ResizeObserver ? new ResizeObserver(measureBanner) : null;
  function observeBanner() {
    const next = document.querySelector('.update-banner');
    if (next === updateBanner) return;
    if (updateBanner) bannerResize?.unobserve(updateBanner);
    updateBanner = next;
    if (updateBanner) bannerResize?.observe(updateBanner);
    measureBanner();
  }
  new MutationObserver(observeBanner).observe(document.body, {childList: true});
  window.addEventListener('resize', measureBanner);
  observeBanner();
})();
