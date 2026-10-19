(() => {
  const menu = document.getElementById('workspace-menu');
  const sidebar = document.getElementById('workspace-sidebar');
  const vacancy = document.getElementById('vacancy-window');
  const history = document.getElementById('history-window');
  if (!menu || !sidebar || !vacancy || !history) return;
  const openers = new WeakMap();
  const dialogs = [sidebar, vacancy, history];
  let currentStep = 1;
  for (const id of ['telegram-panel', 'bank-panel']) {
    const panel = document.getElementById(id);
    if (panel) document.getElementById('workspace-services').append(panel);
  }
  vacancy.querySelector('.workspace-window-content').append(document.getElementById('job-panel'));
  history.querySelector('.workspace-window-content').append(document.getElementById('application-history-panel'));
  function close(dialog, restore = true) {
    if (!dialog.open) return;
    dialog.dataset.restoreFocus = String(restore);
    dialog.close();
  }
  function open(dialog, opener) {
    if (dialog.open) return;
    close(sidebar, false);
    if (dialog === vacancy && window.cvRequiredSync && !window.cvRequiredSync.ready()) {
      document.getElementById('auth-panel')?.scrollIntoView({block: 'center', behavior: 'smooth'});
      menu.focus({preventScroll: true});
      return;
    }
    openers.set(dialog, opener || document.activeElement);
    dialog.showModal();
    if (dialog === sidebar) menu.setAttribute('aria-expanded', 'true');
    if (dialog === history) document.getElementById('application-history-details').open = true;
    const focus = dialog === vacancy ? document.getElementById('job-text') : dialog.querySelector('[data-workspace-close]');
    focus?.focus({preventScroll: true});
  }
  function dismiss(dialog) {
    if (!dialog.open || dialog.dataset.closing) return;
    if (!dialog.animate || window.matchMedia?.('(prefers-reduced-motion: reduce)').matches) { close(dialog); return; }
    dialog.dataset.closing = 'true';
    const animation = dialog.animate([{opacity: 1, transform: 'none'}, {opacity: 0, transform: dialog === sidebar ? 'translateX(-40px)' : 'translateY(12px)'}], {duration: 160, easing: 'ease-in', fill: 'forwards'});
    animation.finished.catch(() => {}).then(() => { close(dialog); animation.cancel(); delete dialog.dataset.closing; });
  }
  menu.addEventListener('click', () => open(sidebar, menu));
  document.getElementById('open-vacancy').addEventListener('click', () => open(vacancy, menu));
  document.getElementById('open-history').addEventListener('click', () => open(history, menu));
  // Close before existing handlers run, preserving their user activation for OAuth and popups.
  document.getElementById('workspace-services').addEventListener('click', event => {
    if (event.target.closest('button:not(:disabled), a[href]')) close(sidebar, false);
  }, true);
  for (const dialog of dialogs) {
    dialog.querySelector('[data-workspace-close]').addEventListener('click', () => dismiss(dialog));
    dialog.addEventListener('cancel', event => {event.preventDefault(); dismiss(dialog);});
    dialog.addEventListener('click', event => {
      if (event.target !== dialog) return;
      const bounds = dialog.getBoundingClientRect();
      if (event.clientX < bounds.left || event.clientX > bounds.right || event.clientY < bounds.top || event.clientY > bounds.bottom) dismiss(dialog);
    });
    dialog.addEventListener('close', () => {
      if (dialog === sidebar) menu.setAttribute('aria-expanded', 'false');
      if (dialog.dataset.restoreFocus !== 'false' && !document.querySelector('dialog[open]')) openers.get(dialog)?.focus({preventScroll: true});
      delete dialog.dataset.restoreFocus;
    });
  }
  window.cvWorkspace = {
    showStep(step) {
      if (step === 1 && (currentStep !== 1 || document.getElementById('job-text').value?.trim())) open(vacancy, menu);
      else close(vacancy, false);
      currentStep = step;
    },
  };
  window.addEventListener('cv-app-error', event => {
    if (event.detail?.message && !document.querySelector('dialog[open]')) open(vacancy, menu);
  });
})();
