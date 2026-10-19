/* OAuth tokens remain in memory, never in localStorage. */
window.cvDrive = (() => {
  let config, authHeaders, token = "", expiresAt = 0;
  let connection = null;
  let generation = 0, connectedReady = false;
  let authorizationHandler = null;
  let cancelPopup = null;
  let activeOperationId = null;
  function setAuthorizationHandler(handler) { authorizationHandler = handler; }
  const status = () => document.querySelector("#drive-status");
  const button = () => document.querySelector("#connect-drive");
  function reset() {
    generation++; connectedReady = false; connection = null;
    cancelPopup?.(); cancelPopup = null;
    activeOperationId = null;
    token = ""; expiresAt = 0;
    if (status()) status().textContent = "Conecta Drive para guardar los CV en CV GENERADOS.";
  }
  function script(src) {
    return new Promise((resolve, reject) => {
      const element = document.createElement("script");
      element.src = src; element.onload = resolve;
      element.onerror = () => reject(new Error("No se pudo cargar Google Drive. Comprueba tu conexión."));
      document.head.append(element);
    });
  }
  let pickerReady = null;
  async function picker(kind = 'CV Generados') {
    if (!config.picker_api_key || !config.app_id) throw new Error('No se pudo abrir el selector. Usa Sincronizar todo para preparar tus carpetas automáticamente.');
    if (!pickerReady) pickerReady = (async () => {
      await script('https://apis.google.com/js/api.js');
      await new Promise((resolve, reject) => gapi.load('picker', {callback: resolve, onerror: reject, timeout: 15000, ontimeout: reject}));
    })().catch(error => { pickerReady = null; throw error; });
    await pickerReady;
    return new Promise((resolve, reject) => {
      const view = new google.picker.DocsView(google.picker.ViewId.FOLDERS)
        .setIncludeFolders(true).setSelectFolderEnabled(true)
        .setMimeTypes("application/vnd.google-apps.folder");
      const dialog = new google.picker.PickerBuilder().addView(view)
        .setOAuthToken(token).setDeveloperKey(config.picker_api_key)
        .setAppId(config.app_id).setOrigin(location.origin)
        .setTitle(`Selecciona ${kind} en tu Drive`)
        .setCallback((data) => {
          if (data.action === google.picker.Action.CANCEL) {
            dialog.setVisible(false);
            reject(new Error(`Selección cancelada. No se cambiaron tus carpetas. Selecciona ${kind} para continuar.`));
          }
          if (data.action === google.picker.Action.PICKED) {
            dialog.setVisible(false);
            if (!config.multi_account && data.docs?.[0]?.id !== config.folder_id) reject(new Error("Selecciona la carpeta CV GENERADOS del enlace de destino."));
            else resolve(data.docs?.[0]?.id);
          }
        }).build();
      dialog.setVisible(true);
    });
  }
  async function check(selection = {}, retry = 0) {
    const started = generation;
    const path = config.multi_account ? '/api/account/setup' : '/api/drive/check';
    let response;
    try { response = await fetch(path, {
      method: "POST", headers: { 'Content-Type':'application/json', ...authHeaders(), "X-Drive-Access-Token": token, ...(activeOperationId ? {'X-CV-Operation-ID':activeOperationId}: {}) },
      ...(config.multi_account ? {body: JSON.stringify(selection)} : {}),
    }); } catch (error) {
      if (started === generation) window.cvClientSupervisor?.network(path, error, activeOperationId);
      throw error;
    }
    const data = await response.json().catch(() => ({}));
    if (started !== generation) throw new Error('La sesión cambió. Conecta el Drive de la cuenta actual.');
    if (response.status === 409 && data.code === 'account_setup_in_progress' && retry < 8) {
      status().textContent = 'Otra sesión está preparando tu banco. Esperando para reutilizar sus carpetas…';
      await new Promise(resolve => setTimeout(resolve, 1000));
      if (started !== generation) throw new Error('La sesión cambió. Conecta el Drive de la cuenta actual.');
      return check(selection, retry + 1);
    }
    if (!response.ok) throw Object.assign(new Error(data.error || "No se pudo comprobar la carpeta de Drive."), { status: response.status });
    if (config.multi_account) {
      config.folder_id = data.archive_id;
      document.querySelector('#bank-folder').href = `https://drive.google.com/drive/folders/${data.bank_id}`;
      document.querySelector('#drive-folder').href = `https://drive.google.com/drive/folders/${data.archive_id}`;
      window.dispatchEvent(new CustomEvent('cv-account-ready', {detail: data}));
    }
    connectedReady = true;
    return data;
  }
  const connectionLoading = (message, options = {}) => options.inline ? () => {} : window.cvLoading.start(message);
  async function connected(result, started = generation, options = {}) {
    if (started !== generation) throw new Error('La cuenta cambió durante la autorización.');
    const finish = connectionLoading("Conectando Google Drive", options);
    try {
      if (result.error) throw new Error("Google no autorizó Drive. Usa la cuenta permitida e inténtalo de nuevo.");
      token = result.access_token;
      expiresAt = Date.now() + Number(result.expires_in || 3600) * 1000 - 60000;
      connectedReady = false;
      try { await check(); }
      catch (error) {
        if (config.multi_account || error.status !== 403) throw error;
        await picker(); await check();
      }
      if (started !== generation) throw new Error('La sesión cambió.');
      status().textContent = "Drive conectado. Cada PDF o Word se guardará en CV GENERADOS.";
      button().textContent = "Reconectar Drive";
      window.cvGmail?.acceptCredential(result.access_token, result.expires_in || 3600, result.scope);
      window.dispatchEvent(new Event("cv-drive-connected"));
    } catch (error) { if (started === generation) { if (!config.multi_account) reset(); status().textContent = error.message; } throw error; }
    finally { if (started === generation) button().disabled = false; finish(); }
  }
  async function initialize(settings, getAuthHeaders) {
    config = settings; authHeaders = getAuthHeaders;
    if (config?.provider !== "drive") return;
    document.querySelector("#drive-panel").hidden = false;
    document.querySelector("#drive-folder").href = `https://drive.google.com/drive/folders/${config.folder_id}`;
    try {
      button().disabled = false;
      button().addEventListener("click", () => connect().catch(() => {}));
    } catch (error) { status().textContent = error?.message || "No se pudo iniciar Drive. Recarga la página."; }
  }
  function isConnected() {
    return config?.provider !== "drive" || Boolean(connectedReady && token && Date.now() < expiresAt);
  }
  function connect(options = {}) {
    if (isConnected() && (!options.requireGmail || window.cvGmail?.isConnected())) return Promise.resolve();
    if (connection) return connection;
    if (authorizationHandler) {
      const started = generation;
      const operationId = options.operationId || (typeof crypto !== 'undefined' ? crypto.randomUUID() : undefined);
      activeOperationId = operationId;
      const report = code => { if (started === generation && typeof CustomEvent !== 'undefined') window.dispatchEvent(new CustomEvent('cv-client-diagnostic', {detail:{service:'drive-api',stage:'oauth-authorization',code,operationId}})); };
      report('authorization_pending');
      const timer = window.setTimeout?.(() => report('authorization_timeout'), 90000);
      // Open Google before showing a modal can change the active top layer.
      let authorization;
      try { authorization = authorizationHandler({operationId}); }
      catch (error) { window.clearTimeout?.(timer); report('oauth_error'); return Promise.reject(error); }
      const finish = connectionLoading("Conectando Gmail y Drive con tu cuenta", options);
      button().disabled = true;
      const operation = connection = Promise.resolve(authorization).then(result => {
        if (started !== generation) throw new Error('La cuenta cambió durante la autorización.');
        return connected(result, started, options);
      }).catch(error => {
        if (started === generation) {
          const known = {'auth/popup-closed-by-user': 'popup_closed', 'auth/popup-blocked': 'popup_failed_to_open', 'auth/cancelled-popup-request': 'popup_closed', 'auth/user-cancelled': 'access_denied'};
          // Only SDK authorization failures qualify; backend/check errors have their own evidence.
          if (typeof error.code === 'string' && error.code.startsWith('auth/')) {
            window.dispatchEvent(new CustomEvent('cv-client-diagnostic', {detail: {
              service: 'drive-api', stage: 'oauth-authorization', code: known[error.code] || 'oauth_error',
              operationId,
            }}));
          }
          status().textContent = error.message || "No se pudo conectar tu cuenta de Google.";
        }
        throw error;
      }).finally(() => {
        window.clearTimeout?.(timer);
        if (connection === operation) connection = null;
        if (started === generation) button().disabled = false; finish();
      });
      return connection;
    }
    // Open synchronously from the click, before any awaited network requests.
    const nonce = crypto.randomUUID();
    const authOrigin = "https://cv-a-la-medida-jhonn.firebaseapp.com";
    const popup = window.open(`${authOrigin}/drive-auth.html?mode=combined&origin=${encodeURIComponent(location.origin)}&nonce=${nonce}`, "cv-drive-auth", "width=520,height=650");
    if (!popup) {
      const error = new Error("Permite ventanas emergentes para autorizar el guardado en Drive.");
      status().textContent = error.message;
      return Promise.reject(error);
    }
    const finish = connectionLoading("Conectando Google Drive", options);
    const started = generation;
    button().disabled = true;
    status().textContent = "Autoriza Drive y selecciona CV GENERADOS…";
    const operation = connection = new Promise((resolve, reject) => {
      let timer;
      const cleanup = () => { clearInterval(timer); window.removeEventListener("message", receive); if (cancelPopup === cancel) cancelPopup = null; };
      const cancel = () => {
        cleanup(); popup.close?.(); reject(new Error('La cuenta cambió durante la autorización.'));
      };
      cancelPopup = cancel;
      const receive = (event) => {
        if (started !== generation) return;
        if (event.origin !== authOrigin || event.source !== popup || event.data?.nonce !== nonce) return;
        if (event.data.diagnostic) {
          const code = event.data.diagnostic.code;
          if (['access_denied', 'popup_closed', 'popup_failed_to_open', 'oauth_error'].includes(code)) {
            window.dispatchEvent(new CustomEvent('cv-client-diagnostic', {detail: {
              service: 'drive-api', stage: 'oauth-authorization', code, operationId: nonce,
            }}));
          }
          return;
        }
        cleanup();
        connected(event.data.result, started, options).then(resolve, reject);
      };
      window.addEventListener("message", receive);
      timer = setInterval(() => {
        if (!popup.closed) return;
        cleanup(); if (started !== generation) return;
        button().disabled = false;
        const error = new Error("La autorización se cerró. Sincroniza el banco para volver a conectar Drive.");
        status().textContent = error.message;
        reject(error);
      }, 500);
    }).finally(() => { if (connection === operation) connection = null; finish(); });
    return connection;
  }
  async function acceptCredential(accessToken, options = {}) {
    if (config?.provider !== "drive") return;
    if (!accessToken) throw new Error("Google no entregó el permiso de Drive. Sincroniza el banco para conectarlo.");
    await connected({ access_token: accessToken, expires_in: 3600, ...options }, generation, options);
  }
  function headers() {
    if (config?.provider !== "drive") return {};
    if (!token || Date.now() >= expiresAt) {
      reset(); throw new Error("Conecta Google Drive antes de guardar y descargar tu CV.");
    }
    return { "X-Drive-Access-Token": token };
  }
  function headersIfConnected() {
    return token && Date.now() < expiresAt ? {'X-Drive-Access-Token': token} : {};
  }
  async function chooseFolders() {
    const started = generation;
    if (!token || Date.now() >= expiresAt) {
      if (!authorizationHandler) throw new Error('Inicia sesión para seleccionar tus carpetas.');
      const result = await authorizationHandler();
      if (started !== generation) throw new Error('La cuenta cambió durante la autorización.');
      token = result.access_token; expiresAt = Date.now() + Number(result.expires_in || 3600) * 1000 - 60000;
      window.cvGmail?.acceptCredential(token, result.expires_in || 3600, result.scope);
    }
    const bank_id = await picker('Banco de Datos');
    if (started !== generation) throw new Error('La sesión cambió. Selecciona las carpetas de la cuenta actual.');
    const archive_id = await picker('CV Generados');
    if (started !== generation) throw new Error('La sesión cambió. Selecciona las carpetas de la cuenta actual.');
    await check({bank_id, archive_id});
    status().textContent = 'Tus carpetas están conectadas.';
    window.dispatchEvent(new Event('cv-drive-connected'));
  }
  function setAccount(account) {
    if (config) { config.folder_id = account.archive_id; config.allowed_email = account.email || ''; }
    if (account.bank_id) document.querySelector('#bank-folder').href = `https://drive.google.com/drive/folders/${account.bank_id}`;
    if (account.archive_id) document.querySelector('#drive-folder').href = `https://drive.google.com/drive/folders/${account.archive_id}`;
  }
  return { initialize, headers, headersIfConnected, reset, connect, isConnected, acceptCredential, setAuthorizationHandler, chooseFolders, setAccount, verify: check };
})();
