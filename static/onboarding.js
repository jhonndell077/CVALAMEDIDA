/* Optional collection; no personal data or photo is saved in browser storage. */
window.cvOnboarding = (() => {
  const dialog = document.querySelector('#onboarding-dialog');
  const cvDialog = document.querySelector('#onboarding-cv-dialog');
  const cvPreview = document.querySelector('#onboarding-cv-preview');
  const form = document.querySelector('#onboarding-form');
  const status = document.querySelector('#onboarding-status');
  const error = document.querySelector('#onboarding-error');
  const openButton = document.querySelector('#open-onboarding');
  let user = null, options = null, generation = 0, busy = false, preview = null, draftStarted = false, closedByUser = false;
  function clearPreview() {
    if (preview) URL.revokeObjectURL(preview);
    preview = null;
    const image = document.querySelector('#onboarding-photo-preview');
    image.hidden = true; image.removeAttribute('src');
  }
  function reset() {
    generation++; draftStarted = false; closedByUser = false; user = null; options = null; busy = false;
    if (cvDialog.open) cvDialog.close();
    cvPreview.replaceChildren();
    if (dialog.open) dialog.close();
    form.reset(); window.cvRepeaters.reset(form); clearPreview(); error.hidden = true; status.textContent = '';
    openButton.hidden = true;
    document.querySelector('.bank-save-confirmation')?.remove();
    form.querySelectorAll('input,textarea,button').forEach(element => { element.disabled = false; });
  }
  function current(started) { return started === generation && Boolean(user); }
  async function request(path, init = {}) {
    const started = generation;
    await options.refreshToken();
    if (!current(started)) throw new Error('La cuenta cambi\u00f3.');
    const requestHeaders = options.headers(init.headers || {});
    const response = await fetch(path, {...init, headers: requestHeaders});
    const data = await response.json().catch(() => ({}));
    if (!current(started)) throw new Error('La cuenta cambi\u00f3.');
    if (!response.ok) {
      window.cvDrive?.invalidateAuthorization?.(data.code, requestHeaders);
      if (window.cvErrors) throw window.cvErrors.fromResponse(response,data,{stage:'drive-upload'});
      throw Object.assign(new Error(data.error || 'No se pudo completar el formulario.'), {status: response.status, code: data.code});
    }
    return data;
  }
  function show() {
    if (window.cvRequiredSync && !window.cvRequiredSync.ready()) return;
    if (!user || busy || dialog.open) return;
    if (!draftStarted) {
    const candidate = options.profile()?.candidate || {};
    form.elements.namedItem('name').value = candidate.name || user.displayName || '';
    form.elements.namedItem('email').value = candidate.email || user.email || '';
    form.elements.namedItem('address').value = candidate.address || '';
    form.elements.namedItem('national_id').value = candidate.national_id || '';
    window.cvRepeaters.mount(form.querySelector('[data-repeater="phones"]')).set(candidate.phones || []);
    draftStarted = true;
    }
    error.hidden = true; status.textContent = '';
    dialog.showModal();
  }
  async function check() {
    if (!user || busy || dialog.open || closedByUser) return;
    const started = generation;
    const data = await request('/api/account/onboarding');
    if (current(started) && data.needed) show();
  }
  async function initialize(account, settings) {
    if (user && account && user.uid === account.uid) { user = account; options = settings; return; }
    reset(); user = account; options = settings;
    openButton.hidden = !user;
    if (user) await check();
  }
  function setBusy(value) {
    busy = value;
    form.querySelectorAll('input,textarea,button').forEach(element => { element.disabled = value; });
  }
  function fieldsNow() {
    return {...Object.fromEntries([...form.querySelectorAll('[name]')].map(element => [element.name, element.value.trim()])), ...window.cvRepeaters.collect(form)};
  }
  function renderPreview() {
    const fields = fieldsNow();
    cvPreview.replaceChildren();
    function text(parent, tag, value, className = '') {
      const node = document.createElement(tag); node.textContent = value; node.className = className; parent.append(node); return node;
    }
    function section(parent, title) { const node = text(parent, 'section', '', 'draft-section'); text(node, 'h4', title); return node; }
    const left = text(cvPreview, 'aside', '', 'kitchen-sidebar');
    if (preview) { const photo = document.createElement('img'); photo.src = preview; photo.alt = 'Tu foto de perfil'; photo.className = 'kitchen-photo'; left.append(photo); }
    text(left, 'h3', fields.name || 'Tu nombre', 'kitchen-name');
    [fields.address, fields.national_id && `C\u00e9dula: ${fields.national_id}`, ...(fields.phones || []), fields.email].filter(Boolean).forEach(value => text(left, 'p', value, 'kitchen-contact'));
    if (fields.skills.length) { const skills = section(left, 'Habilidades'); fields.skills.forEach(value => text(skills, 'p', `\u2022 ${value}`)); }
    const right = text(cvPreview, 'div', '', 'kitchen-content');
    for (const [key, title] of [['education', 'Formaci\u00f3n acad\u00e9mica'], ['courses', 'Cursos realizados'], ['experiences', 'Experiencia laboral'], ['projects', 'Proyectos y experiencia pr\u00e1ctica'], ['references', 'Referencias personales']]) {
      if (!fields[key]?.length) continue;
      const group = section(right, title);
      fields[key].forEach(item => {
        const entry = text(group, 'div', '', 'experience-preview');
        text(entry, 'h5', item.title || item.name || 'Por completar');
        [item.institution, item.employer, item.category, item.date, [item.start_date, item.end_date].filter(Boolean).join(' \u2014 '), item.description, item.url, item.role, item.phone].filter(Boolean).forEach(value => text(entry, 'p', value));
        (item.responsibilities || []).forEach(value => text(entry, 'p', `\u2022 ${value}`));
        if (item.technologies?.length) text(entry, 'p', item.technologies.join(', '));
      });
    }
    if (!right.children.length) text(right, 'p', 'Tus estudios, cursos, experiencias, proyectos y referencias aparecer\u00e1n aqu\u00ed a medida que los completes.', 'preview-empty');
  }
  function closePreview() { cvDialog.close(); document.querySelector('#onboarding-preview-open').focus(); }
  document.querySelector('#onboarding-preview-open').addEventListener('click', () => {
    if (!user || busy) return;
    renderPreview(); cvDialog.showModal();
  });
  document.querySelector('#onboarding-preview-close').addEventListener('click', closePreview);
  document.querySelector('#onboarding-preview-back').addEventListener('click', closePreview);
  cvDialog.addEventListener('cancel', event => { event.preventDefault(); closePreview(); });
  form.addEventListener('input', () => { if (cvDialog.open) renderPreview(); });
  form.addEventListener('submit', async event => {
    event.preventDefault(); if (!user || busy) return;
    const started = generation;
    const fields = {...Object.fromEntries([...form.querySelectorAll('[name]')].map(element => [element.name, element.value])), ...window.cvRepeaters.collect(form)};
    const file = document.querySelector('#onboarding-photo').files[0];
    if (file && file.size > 8*1024*1024) { error.textContent = 'La foto debe pesar como m\u00e1ximo 8 MB.'; error.hidden = false; return; }
    const reference = document.querySelector('#onboarding-reference-cv').files[0];
    if (reference && (reference.size > 10*1024*1024 || !/\.(pdf|docx)$/i.test(reference.name))) {
      error.textContent = 'La hoja de vida debe ser PDF o Word (.docx) y pesar como maximo 10 MB.'; error.hidden = false; return;
    }
    const body = new FormData(); body.append('data',JSON.stringify(fields));
    if (file) body.append('photo',file);
    // The editable fields are authoritative; do not re-import the original after editing.
    setBusy(true); error.hidden = true; status.textContent = 'Conectando tu Drive para guardar los datos...';
    try {
      await window.cvDrive.connect();
      if (!current(started)) return;
      status.textContent = 'Guardando los archivos en las carpetas de tu Banco de Datos...';
      const result = await request('/api/account/onboarding',{method:'POST',body});
      if (!current(started)) return;
      dialog.close(); form.reset(); window.cvRepeaters.reset(form); clearPreview(); draftStarted = false;
      const confirmation = document.createElement('p');
      confirmation.className = 'bank-save-confirmation'; confirmation.setAttribute('role', 'status');
      confirmation.textContent = 'Tu banco se guardó correctamente.';
      document.querySelector('.bank-save-confirmation')?.remove();
      openButton.after(confirmation);
      let consolidated = !result.sync_required;
      if (result.sync_required) {
        confirmation.textContent = 'Tu banco se guardó correctamente. Consolidando tu perfil…';
        try { await options.consolidate(); consolidated = true; confirmation.textContent = 'Tu banco se guardó y consolidó correctamente.'; }
        catch (failure) { confirmation.textContent = `Datos guardados. La consolidación está pendiente: ${failure.message} Pulsa Sincronizar para reintentar.`; }
      }
      if (!current(started)) return;
      options.completed(result.saved, {consolidated});
    } catch (failure) {
      if (current(started)) { error.textContent = failure.message; error.hidden = false; status.textContent = 'Puedes revisar el banco o reintentar. Los campos del formulario se conservan.'; }
    } finally { if (current(started)) setBusy(false); }
  });
  document.querySelector('#onboarding-reference-cv').addEventListener('change', async event => {
    if (!user || busy) return;
    const file = event.target.files[0]; if (!file) return;
    const started = generation;
    if (file.size > 10*1024*1024 || !/\.(pdf|docx)$/i.test(file.name)) {
      error.textContent = 'Selecciona un PDF o Word (.docx) de hasta 10 MB.'; error.hidden = false; return;
    }
    const body = new FormData(); body.append('reference_cv', file);
    setBusy(true); error.hidden = true; status.textContent = 'Leyendo tu CV para completar los campos...';
    try {
      const result = await request('/api/account/onboarding/import', {method:'POST', body});
      if (!current(started)) return;
      const fields = result.fields;
      for (const key of ['name','email','address','national_id']) {
        if (fields[key]) form.elements.namedItem(key).value = fields[key];
      }
      for (const key of ['phones','skills','education','courses','experiences','projects','references']) {
        if (fields[key]?.length) window.cvRepeaters.mount(form.querySelector(`[data-repeater="${key}"]`)).set(fields[key]);
      }
      draftStarted = true;
      status.textContent = 'Datos importados. Revisa y modifica los campos antes de guardar.' +
        (result.notes?.length ? ' Avisos: ' + result.notes.join(' ') : '');
    } catch (failure) {
      if (current(started)) { error.textContent = failure.message; error.hidden = false; status.textContent = 'Tus campos se conservan. Puedes elegir otro CV o continuar manualmente.'; }
    } finally { if (current(started)) setBusy(false); }
  });
  document.querySelector('#onboarding-reference-remove').addEventListener('click', () => {
    if (busy) return;
    document.querySelector('#onboarding-reference-cv').value = '';
    error.hidden = true; error.textContent = '';
    status.textContent = 'Archivo de referencia quitado. Tus datos se conservan. Pulsa Guardar y consolidar mi banco para continuar.';
  });
  document.querySelector('#onboarding-photo').addEventListener('change',event => {
    clearPreview(); const file = event.target.files[0]; if (!file) return;
    preview = URL.createObjectURL(file);
    const image = document.querySelector('#onboarding-photo-preview'); image.src = preview; image.hidden = false;
  });
  document.querySelector('#onboarding-close').addEventListener('click', () => {
    if (!busy) { closedByUser = true; dialog.close(); }
  });
  dialog.addEventListener('cancel',event => { event.preventDefault(); if (!busy) { closedByUser = true; dialog.close(); } });
  openButton.addEventListener('click',show);
  return {initialize,check,reset};
})();
