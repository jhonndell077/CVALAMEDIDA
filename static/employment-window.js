(() => {
  'use strict';
  const dialog = document.querySelector('#employment-window');
  const panel = document.querySelector('#employment-panel');
  const link = document.querySelector('.employment-nav');
  let opener;
  dialog.querySelector('.employment-window-content').append(panel);
  link.setAttribute('aria-haspopup', 'dialog');
  link.setAttribute('aria-controls', 'employment-window');
  function close() { if (dialog.open) dialog.close(); }
  function open() {
    if (link.hidden) return;
    opener = document.activeElement;
    panel.hidden = false;
    if (!dialog.open) dialog.showModal();
    document.querySelector('#employment-query').focus();
    window.dispatchEvent(new Event('resize'));
  }
  link.addEventListener('click', event => {event.preventDefault(); open();});
  document.querySelector('#employment-window-close').addEventListener('click', close);
  document.querySelector('.employment-login-link')?.addEventListener('click', close);
  dialog.addEventListener('close', () => { if (opener?.isConnected) opener.focus(); });
  window.cvEmploymentWindow = {open, close};
})();
