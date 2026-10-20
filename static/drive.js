/* OAuth tokens remain in memory, never in localStorage. */
// One public decoder for application errors; never display untrusted response text.
window.cvErrors = (() => {
  const messages = {
    account_write_busy:'Otra sesión está guardando cambios. Tus datos se conservan. Reintenta en unos segundos.',
    account_write_lease_lost:'La reserva de escritura cambió. Tus datos se conservan. Sincroniza antes de reintentar.',
    account_write_outcome_unknown:'No se confirmó la escritura. Revisa su resultado antes de repetirla.',
    job_account_maintenance:'La cuenta requiere revisión administrativa antes de continuar.',
    admin_delete_failed:'La acción administrativa falló. El administrador debe revisar su resultado.',
    google_authorization_expired:'La autorización de Google venció o fue revocada. Vuelve a conectar tu cuenta.',
    job_authorization_expired:'La autorización del proceso venció. Vuelve a conectar tu cuenta.',
    google_permissions_missing:'Faltan permisos de Google. Autoriza los permisos solicitados con la misma cuenta.',
    drive_folder_permission:'Esta cuenta no tiene permiso sobre la carpeta. Selecciona una carpeta propia.',
    drive_access_undetermined:'Drive rechazó el acceso. Comprueba los permisos y la disponibilidad de la carpeta.',
    google_identity_check_failed:'Google no confirmó la identidad de esta conexión. Comprueba la cuenta autorizada.',
    drive_storage_full:'El almacenamiento de Google Drive está lleno. Libera espacio antes de reintentar.',
    google_api_disabled:'La API de Google no está habilitada. El administrador debe revisar la configuración.',
    google_rate_limit:'Google limitó temporalmente las solicitudes. Espera antes de reintentar.',
    google_daily_limit:'Se alcanzó un límite de la API de Google. El administrador debe revisar la cuota.',
    google_request_failed:'No se confirmó la operación de Google. Revisa su resultado antes de repetirla.',
    bank_review_required:'El banco necesita revisión. Consulta los documentos pendientes o bloqueados.',
    bank_sync_pending:'Hay documentos pendientes. Sincroniza el banco antes de continuar.',
    job_dispatch_unavailable:'La solicitud está guardada. Reintenta la misma acción para recuperar su despacho.',
    job_service_unavailable:'El servicio temporal no está disponible. Espera antes de reintentar.',
    external_outcome_unknown:'No se confirmó el resultado externo. Revisa Drive o Enviados antes de repetirlo.',
  };
  const validId = value => typeof value === 'string' && /^(?:[a-f0-9]{32}|[a-f0-9]{64}|[a-f0-9]{8}(?:-[a-f0-9]{4}){3}-[a-f0-9]{12})$/.test(value);
  function fromResponse(response, value, options = {}) {
    const data = value && typeof value === 'object' && !Array.isArray(value) ? value : {};
    const code = Object.hasOwn(messages,data.code) ? data.code : [502,504].includes(response.status) ? 'http_gateway_error' : 'http_request_failed';
    const stages = ['request','drive-access-check','drive-prepare','drive-upload','bank-sync','authorization','admission','worker','administration','delivery'];
    const stage = stages.includes(data.stage) ? data.stage : options.stage || 'request';
    const correlation = validId(data.correlationId) ? data.correlationId : response.headers?.get?.('X-Correlation-ID');
    const fallback = stage === 'drive-prepare' ? 'El servidor no pudo confirmar la preparación de tus carpetas.'
      : stage === 'drive-access-check' ? 'El servidor no pudo confirmar la comprobación de acceso.' : 'No se pudo completar la solicitud.';
    const message = messages[code] || `${fallback} (HTTP ${response.status}). Conserva tus datos y revisa el estado antes de repetirla.`;
    const retryable = code === 'account_write_busy' || data.retryable === true && ['google_rate_limit','bank_sync_pending','job_dispatch_unavailable','job_service_unavailable'].includes(code);
    return Object.assign(new Error(message), {status:response.status,code,stage,
      ...(validId(correlation) ? {correlationId:correlation} : {}),
      ...(validId(data.operationId) ? {operationId:data.operationId} : {}),
      retryable, safeNextAction:code==='account_write_busy'?'retry': ['reauthorize','select_folders','free_storage','contact_admin','retry','retry_same_operation','synchronize','review_bank','review_outcome','check_access','wait_period','review_error'].includes(data.safeNextAction) ? data.safeNextAction : 'review_outcome',
      externalOutcome:['unknown','not_started','rejected'].includes(data.externalOutcome)?data.externalOutcome:'unknown',
      ...(typeof data.buildId==='string'&&/^(?:unknown|\d{8}T\d{6}Z-[a-f0-9]{8})$/.test(data.buildId)?{buildId:data.buildId}:{}),
      ...(typeof data.job_id==='string'&&/^web-[a-f0-9-]{36}$/.test(data.job_id)?{job_id:data.job_id}:{})});
  }
  return {fromResponse};
})();
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
  function invalidateAuthorization(code, requestHeaders) {
    if (code !== 'google_authorization_expired' || !token) return false;
    const sentToken = typeof requestHeaders?.get === 'function'
      ? requestHeaders.get('X-Drive-Access-Token')
      : Object.entries(requestHeaders || {}).find(([name]) => name.toLowerCase() === 'x-drive-access-token')?.[1];
    // A delayed response from an older credential must not revoke a newer one.
    if (!sentToken || sentToken !== token) return false;
    token = ''; expiresAt = 0; connectedReady = false;
    if (status()) status().textContent = 'El permiso de Drive caducó. Vuelve a pulsar la acción para autorizarlo sin perder tus datos.';
    if (button()) button().textContent = 'Reconectar Drive';
    return true;
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
  async function check(selection = {}, retry = 0, mode = config.multi_account ? 'prepare' : 'access') {
    const started = generation;
    const preparing = mode === 'prepare';
    const path = preparing ? '/api/account/setup' : '/api/drive/check';
    const stage = preparing ? 'drive-prepare' : 'drive-access-check';
    if (status()) status().textContent = preparing ? 'Preparando tus carpetas de Drive…' : 'Comprobando acceso a Drive…';
    const requestHeaders = { 'Content-Type':'application/json', ...authHeaders(), "X-Drive-Access-Token": token, ...(activeOperationId ? {'X-CV-Operation-ID':activeOperationId}: {}) };
    let response;
    try { response = await fetch(path, {
      method: "POST", headers: requestHeaders,
      ...(preparing ? {body: JSON.stringify(selection)} : {}),
    }); } catch (error) {
      if (started === generation) window.cvClientSupervisor?.network(path, error, activeOperationId);
      throw error;
    }
    const raw = await response.json().catch(() => ({}));
    const data = raw && typeof raw === 'object' && !Array.isArray(raw) ? raw : {};
    if (started !== generation) throw new Error('La sesión cambió. Conecta el Drive de la cuenta actual.');
    if (response.status === 409 && data.code === 'account_setup_in_progress' && retry < 8) {
      status().textContent = 'Otra sesión está preparando tu banco. Esperando para reutilizar sus carpetas…';
      await new Promise(resolve => setTimeout(resolve, 1000));
      if (started !== generation) throw new Error('La sesión cambió. Conecta el Drive de la cuenta actual.');
      return check(selection, retry + 1, mode);
    }
    if (!response.ok) {
      invalidateAuthorization(data.code, requestHeaders);
      throw window.cvErrors.fromResponse(response,data,{stage});
    }
    if (preparing) {
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
  return { initialize, headers, headersIfConnected, reset, connect, isConnected, acceptCredential, setAuthorizationHandler, chooseFolders, setAccount, invalidateAuthorization, verify: check,
    checkAccess: () => check({},0,'access'), prepareFolders: selection => check(selection,0,'prepare') };
})();
