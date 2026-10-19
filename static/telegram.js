window.cvTelegram = (() => {
  let user = null, authHeaders, client, loading = false, generation = 0;
  let pairLink = '', pairExpires = 0, driveConnected = false, authorization = null, authorizationOperation = '', multiAccount = false;
  const panel = () => document.querySelector("#telegram-panel");
  const button = () => document.querySelector("#telegram-authorize-drive");
  const status = () => document.querySelector("#telegram-status");
  const error = () => document.querySelector("#telegram-error");
  function fail(message) { error().textContent = message; error().hidden = false; }
  function operationId() {
    return typeof crypto !== 'undefined' && crypto.randomUUID ? crypto.randomUUID() : Array.from({length:32},()=>Math.floor(Math.random()*16).toString(16)).join('');
  }
  function reportAuthorization(code, pending = authorization) {
    if (!pending || pending.generation !== generation || !user) return;
    const allowed = ['access_denied','popup_closed','popup_failed_to_open','origin_mismatch','redirect_uri_mismatch','authorization_pending','authorization_timeout'];
    const safe = allowed.includes(code) ? code : 'oauth_error';
    if (pending.reported === safe) return;
    pending.reported = safe;
    const identity = user, started = generation;
    identity.getIdToken().then(token => {
      if (started !== generation || identity.uid !== user?.uid) return;
      return fetch('/api/diagnostics/client', {method:'POST',cache:'no-store',
        headers:{Authorization:'Bearer '+token,'Content-Type':'application/json','X-CV-Operation-ID':pending.operationId},
        body:JSON.stringify({component:'telegram',service:'drive-api',stage:'oauth-authorization',
          result:safe === 'authorization_pending' ? 'pending' : 'error',code:safe})});
    }).catch(()=>{});
  }
  function settleAuthorization(pending) {
    if (pending?.timer && typeof clearTimeout === 'function') clearTimeout(pending.timer);
    if (authorization === pending) authorization = null;
  }
  async function json(path, payload) {
    const started=generation, currentUser=user;
    if (!currentUser) throw new Error('Inicia sesión para configurar Telegram.');
    const token = await currentUser.getIdToken();
    if (started!==generation) throw new Error('La cuenta cambió.');
    const response = await fetch(path, { method: payload ? "POST" : "GET", cache: "no-store",
      headers: { ...authHeaders(), Authorization: `Bearer ${token}`, "Content-Type": "application/json", "X-Requested-With": "XmlHttpRequest", ...(authorization ? {"X-CV-Operation-ID":authorization.operationId} : {}) },
      body: payload ? JSON.stringify(payload) : undefined });
    const data = await response.json();
    if (started!==generation) throw new Error('La cuenta cambió.');
    if (!response.ok) throw Object.assign(new Error(data.error || "No se pudo configurar Telegram."), {status: response.status});
    return data;
  }
  async function authorized(response, sessionGeneration) {
    if (sessionGeneration !== generation || !user) return;
    if (!response.code) { reportAuthorization(response.error || 'oauth_error'); throw new Error('Google no concedi\u00f3 el permiso de Drive.'); }
    loading = true; button().disabled = true;
    const finish = window.cvLoading.start("Conectando Drive con tu bot privado");
    error().hidden = true;
    try {
      const data = await json("/api/telegram/drive/authorize", {code: response.code});
      await window.cvDrive.acceptCredential(data.access_token, data);
      if (sessionGeneration!==generation) return;
      await json("/api/telegram/drive/confirm", {});
      status().textContent = "Drive autorizado para el guardado automático. Envía una vacante a tu bot privado.";
      await refresh(sessionGeneration);
      if (sessionGeneration === generation) authorizationOperation = '';
    } catch (problem) { if (sessionGeneration===generation) fail(problem.message); throw problem; }
    finally { if (sessionGeneration===generation) { loading = false; button().disabled = !client || !user; } finish(); }
  }
  async function refresh(sessionGeneration) {
    const data = await json("/api/telegram/status");
    if (sessionGeneration !== generation || !user) return;
    driveConnected = Boolean(data.drive_connected);
    multiAccount = Boolean(data.multi_account);
    button().hidden = Boolean(data.multi_account || driveConnected);
    const link = document.querySelector("#telegram-open-bot");
    const activeLink=data.bot_url || (Date.now()<pairExpires ? pairLink : '');
    link.hidden = !data.linked || !driveConnected || !activeLink;
    if (activeLink) link.href = activeLink; else link.removeAttribute('href');
    document.querySelector('#telegram-link').hidden=!data.multi_account || Boolean(data.linked && driveConnected);
    document.querySelector('#telegram-disconnect').hidden=!data.multi_account || !data.linked;
    document.querySelector('#telegram-check-link').hidden=true;
    document.querySelector('#telegram-confirm-link').hidden=true;
    status().textContent = data.drive_connected ? "Drive conectado para trabajar desde Telegram. " + data.message : data.message;
    if (data.pending) status().textContent=`Telegram pendiente: ${data.pending.telegram_name || 'Sin nombre'} ${data.pending.telegram_username ? '@'+data.pending.telegram_username : ''} (ID ${data.pending.telegram_id}). Confirma únicamente si es tu cuenta.`;
    button().textContent = data.drive_connected ? "Volver a autorizar Drive para Telegram" : "Autorizar Drive para Telegram";
    if (!data.client_id) return;
    if (!window.google?.accounts?.oauth2) {
      await new Promise((resolve, reject) => {
        const script = document.createElement("script"); script.src = "https://accounts.google.com/gsi/client";
        script.onload = resolve; script.onerror = () => reject(new Error("No se pudo cargar la autorización de Google.")); document.head.append(script);
      });
    }
    if (sessionGeneration !== generation || !user) return;
    client = pending => google.accounts.oauth2.initCodeClient({client_id: data.client_id,
      scope: "openid email https://www.googleapis.com/auth/drive.file https://www.googleapis.com/auth/drive.readonly https://www.googleapis.com/auth/gmail.send", ux_mode: "popup", hint: user.email,
      callback: response => {
        if (sessionGeneration !== generation || authorization !== pending || pending?.generation !== generation) return;
        if (pending.timer && typeof clearTimeout === 'function') clearTimeout(pending.timer);
        pending.waitingForGoogle = false;
        authorized(response, sessionGeneration).then(() => pending?.resolve(), problem => pending?.reject(problem))
          .finally(() => settleAuthorization(pending));
      },
      error_callback: response => {
        if (sessionGeneration !== generation || authorization !== pending || pending?.generation !== generation) return;
        const problem = new Error('La autorizaci\u00f3n se cerr\u00f3. Pulsa Autorizar Drive para Telegram para intentarlo de nuevo.');
        if (sessionGeneration===generation) fail(problem.message);
        reportAuthorization(response?.type || 'popup_closed', pending);
        pending?.reject(problem); settleAuthorization(pending);
      }});
    button().disabled = false;
  }
  async function initialize(currentUser, headers) {
    if (user?.uid && user.uid === currentUser?.uid) { user = currentUser; authHeaders = headers; return; }
    const sessionGeneration = ++generation;
    authorization?.reject(new Error('La cuenta cambió.')); settleAuthorization(authorization);
    pairLink=''; pairExpires=0; loading=false; driveConnected=false; authorizationOperation='';
    document.querySelector('#telegram-open-bot').hidden=true;
    document.querySelector('#telegram-open-bot').removeAttribute('href');
    for (const id of ['telegram-link','telegram-check-link','telegram-confirm-link','telegram-disconnect']) {
      document.querySelector('#'+id).hidden=true;
      document.querySelector('#'+id).disabled=false;
    }
    status().textContent='';
    user = currentUser; authHeaders = headers; client = null;
    panel().hidden = !user; button().disabled = true; error().hidden = true;
    if (!user) return;
    try { await refresh(sessionGeneration); } catch (problem) { if (sessionGeneration===generation) fail(problem.message); }
  }
  for (const [id,path] of [['telegram-link','/api/telegram/link'],['telegram-confirm-link','/api/telegram/link/confirm'],['telegram-disconnect','/api/telegram/disconnect']]) {
    document.querySelector('#'+id).addEventListener('click',async()=>{
      const started=generation, control=document.querySelector('#'+id);
      if (control.disabled || !user) return;
      // Google needs the user activation for its popup. After OAuth, navigate
      // this tab to Telegram instead of attempting a second blocked popup.
      const botWindow = id === 'telegram-link' && driveConnected ? window.open('', '_blank') : null;
      if (botWindow) botWindow.opener = null;
      control.disabled=true; error().hidden=true;
      try {
        if (id !== 'telegram-disconnect' && !driveConnected) {
          await synchronize();
          if (started !== generation) { botWindow?.close(); return; }
        }
        if (id === 'telegram-link') {
          const account = await json('/api/telegram/status');
          if (account.linked) {
            if (botWindow && account.bot_url) botWindow.location.replace(account.bot_url);
            else botWindow?.close();
            await refresh(started); return;
          }
        }
        const data=await json(path,{});
        if (data.bot_url) {
          pairLink=data.bot_url; pairExpires=Date.now()+data.expires_in*1000;
          if (botWindow) botWindow.location.replace(data.bot_url);
          else window.location.assign(data.bot_url);
        }
        else { pairLink=''; pairExpires=0; }
        await refresh(started);
        if (started===generation && data.bot_url) status().textContent='Pulsa Iniciar en Telegram para completar la vinculación. No necesitas volver aquí. El enlace vence en 10 minutos.';
      } catch (problem) { botWindow?.close(); if (started===generation) fail(problem.message); }
      finally { if (started===generation) control.disabled=false; }
    });
  }
  document.querySelector('#telegram-check-link').addEventListener('click',()=>{
    const started=generation;
    refresh(started).catch(problem=>{ if (started===generation) fail(problem.message); });
  });
  async function restore() {
    if (!user || !driveConnected) return null;
    try { return await json('/api/telegram/drive/session', {}); }
    catch (problem) {
      if (problem.status === 409) {
        driveConnected = false;
        button().hidden = multiAccount;
        document.querySelector('#telegram-link').hidden = !multiAccount;
        button().disabled = !client || !user;
        button().textContent = 'Autorizar Drive para Telegram';
        status().textContent = 'Google necesita renovar los permisos. Pulsa Autorizar Drive para Telegram.';
        return null;
      }
      throw problem;
    }
  }
  function synchronize() {
    if (!user) return window.cvDrive.connect({requireGmail: true});
    if (authorization) return authorization.promise;
    if (driveConnected && window.cvDrive.isConnected() && window.cvGmail.isConnected()) return refresh(generation);
    if (driveConnected) return restore().then(async credential => {
      if (!credential) throw new Error('Google necesita renovar los permisos. Pulsa Autorizar Drive para Telegram para autorizarlos.');
      await window.cvDrive.acceptCredential(credential.access_token, credential);
      await refresh(generation);
    });
    if (!client) return Promise.reject(new Error('La conexión de Telegram aún no está lista. Espera unos segundos y pulsa Autorizar Drive para Telegram.'));
    const pending = {operationId:authorizationOperation || operationId(),generation,waitingForGoogle:true};
    authorizationOperation = pending.operationId;
    pending.promise = new Promise((resolve, reject) => { pending.resolve = resolve; pending.reject = reject; });
    authorization = pending;
    error().hidden = true;
    reportAuthorization('authorization_pending', pending);
    if (typeof setTimeout === 'function') {
      pending.timer=setTimeout(()=>{
        if (authorization !== pending || pending.generation !== generation || !pending.waitingForGoogle) return;
        reportAuthorization('authorization_timeout', pending);
        const problem=new Error('Google no confirmó la autorización. Si la ventana muestra origin_mismatch, su origen no coincide con el cliente OAuth configurado.');
        fail(problem.message); pending.reject(problem); settleAuthorization(pending);
      },120000);
      pending.timer?.unref?.();
    }
    try { client(pending).requestCode(); }
    catch (problem) { reportAuthorization('popup_failed_to_open', pending); settleAuthorization(pending); pending.reject(problem); }
    return pending.promise;
  }
  button().addEventListener('click', () => synchronize().catch(problem => fail(problem.message)));
  window.addEventListener?.('focus', () => { if (user) refresh(generation).catch(() => {}); });
  return {initialize, synchronize, restore, link: () => document.querySelector('#telegram-link').click()};
})();
