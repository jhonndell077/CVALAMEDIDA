(() => {
  const panel = document.getElementById('profile-panel');
  const dialog = document.getElementById('data-dialog');
  const button = document.getElementById('open-data');
  const close = document.getElementById('close-data');
  if (!panel || !dialog || !button || !close) return;
  let previousOverflow = '';
  const sync = () => {
    button.hidden = panel.hidden;
    if (panel.hidden && dialog.open) dialog.close();
  };
  button.addEventListener('click', () => {
    if (panel.hidden || dialog.open) return;
    previousOverflow = document.documentElement.style.overflow;
    dialog.showModal();
    document.documentElement.style.overflow = 'hidden';
    button.setAttribute('aria-expanded', 'true');
  });
  close.addEventListener('click', () => dialog.close());
  dialog.addEventListener('click', event => {
    const bounds = dialog.getBoundingClientRect();
    if (event.target === dialog && (event.clientX < bounds.left || event.clientX > bounds.right || event.clientY < bounds.top || event.clientY > bounds.bottom)) dialog.close();
  });
  dialog.addEventListener('close', () => {
    document.documentElement.style.overflow = previousOverflow;
    button.setAttribute('aria-expanded', 'false');
    if (!button.hidden) button.focus({ preventScroll: true });
  });
  new MutationObserver(sync).observe(panel, { attributes: true, attributeFilter: ['hidden'] });
  sync();
})();
