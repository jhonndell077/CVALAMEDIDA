/* Initial verification is stored by the server per account; tokens remain in memory. */
window.cvRequiredSync = (() => {
  const $ = selector => document.querySelector(selector);
  let required = true, user = null, epoch = 0, gmail = false, drive = false, busy = false;
  let verified = false, loaded = false;
  let verifySession, completed, synchronize, persist;
  function ready() {
    return !required || Boolean(user && loaded && verified);
  }
  function render() {
    const locked = !ready();
    for (const selector of ['#job-panel', '#profile-panel', '#open-onboarding', '#onboarding-form']) {
      const element = $(selector);
      if (element) { element.inert = locked; element.setAttribute('aria-disabled', String(locked)); }
    }
    $('#required-sync').hidden = !required || !user || !loaded || verified;
    const dialog = $('#required-sync');
    const notice = document.querySelector('.subscription-notice');
    if (!dialog.hidden && notice && !dialog.contains(notice)) dialog.prepend(notice);
    if (!dialog.hidden && !dialog.open) dialog.showModal?.();
    if (dialog.hidden && dialog.open) dialog.close?.();
    if (dialog.hidden && notice && dialog.contains(notice)) document.body.append(notice);
    $('#verify-session-gmail').disabled = busy || !user || !loaded;
    $('#verify-session-gmail').hidden = gmail;
    $('#verify-session-status').hidden = gmail;
    $('#verify-drive').disabled = busy || !gmail || !user || !loaded;
    if (locked && $('#onboarding-dialog')?.open) $('#onboarding-dialog').close();
  }
  function session(account) {
    if ((account?.uid || null) !== (user?.uid || null)) {
      epoch++; gmail = false; drive = false; busy = false; verified = false; loaded = false;
      $('#verify-session-status').textContent = 'Pendiente';
      $('#verify-drive-status').textContent = 'Pendiente: completa el paso 2.';
    }
    user = account; render();
  }
  function account(status) {
    if (!user) return;
    loaded = true; verified = verified || status.initial_sync_completed === true;
    render();
  }
  function configure(settings) {
    required = settings.required; verifySession = settings.verifySession; completed = settings.completed;
    synchronize = settings.synchronize; persist = settings.persist; render();
  }
  async function run(step) {
    if (busy || !user || !loaded || verified || (step === 3 && !gmail)) return;
    const started = epoch;
    busy = true;
    drive = false;
    if (step === 2) gmail = false;
    const status = $(step === 2 ? '#verify-session-status' : '#verify-drive-status');
    status.textContent = 'Verificando…'; render();
    try {
      if (step === 2) {
        await window.cvGmail.connect();
        if (started !== epoch) return;
        await verifySession(user);
        if (!window.cvGmail.isConnected()) throw new Error('Falta autorizar Gmail. Reintenta el paso 2.');
      } else {
        await window.cvDrive.connect({requireGmail: true});
        if (started !== epoch) return;
        await window.cvDrive.verify();
        if (started !== epoch) return;
        const synchronized = await synchronize();
        if (started !== epoch) return;
        if (!window.cvGmail.isConnected() || !window.cvDrive.isConnected()) throw new Error('La autorización venció. Repite las verificaciones.');
        const saved = synchronized?.completed === true ? synchronized : await persist();
        if (saved?.completed !== true) throw new Error('No se pudo guardar la verificación. Reintenta el paso 3.');
      }
      if (started !== epoch) return;
      if (step === 2) {
        gmail = true;
        $('#verify-drive-status').textContent = 'Pendiente: pulsa el paso 3.';
      } else { drive = true; verified = true; }
      status.textContent = 'Completado';
    } catch (error) {
      if (started === epoch) status.textContent = `Error: ${error.message} Puedes reintentar.`;
    } finally {
      if (started === epoch) { busy = false; render(); }
    }
    if (started === epoch && ready()) {
      try { await completed?.(); }
      catch (error) { $('#verify-drive-status').textContent = `Conexión verificada. ${error.message}`; }
    }
  }
  $('#verify-session-gmail').addEventListener('click', () => run(2));
  $('#verify-drive').addEventListener('click', () => run(3));
  $('#sync-telegram-optional').addEventListener('click', () => {
    window.cvTelegram?.link?.();
  });
  $('#required-sync').addEventListener('cancel', event => event.preventDefault());
  document.addEventListener('click', event => {
    if (!ready() && event.target.closest?.('#job-panel, #profile-panel, #open-onboarding, #onboarding-form')) {
      event.preventDefault(); event.stopImmediatePropagation(); $('#auth-panel').scrollIntoView?.({block: 'center'});
    }
  }, true);
  document.addEventListener('submit', event => {
    if (!ready() && event.target.matches?.('#onboarding-form, #new-information-form')) {
      event.preventDefault(); event.stopImmediatePropagation();
    }
  }, true);
  window.setInterval(() => {
    if (verified) return;
    if ((gmail && !window.cvGmail.isConnected()) || (drive && !window.cvDrive.isConnected())) {
      gmail = false; drive = false;
      $('#verify-session-status').textContent = 'La autorización venció. Repite el paso 2.';
      $('#verify-drive-status').textContent = 'Pendiente'; render();
    }
  }, 1000);
  render();
  return {configure, session, account, ready};
})();
