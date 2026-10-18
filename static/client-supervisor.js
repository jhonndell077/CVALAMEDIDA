/* Bounded, memory-only browser signals. Never claim provider confirmation. */
(() => {
  'use strict';
  let user = null, epoch = 0, running = false;
  const queue = [], seen = new Set();
  const oauth = new Set(['access_denied','popup_closed','popup_failed_to_open','oauth_error','origin_mismatch','redirect_uri_mismatch','authorization_pending','authorization_timeout']);
  const routes = {'/api/bank/sync':'bank','/api/profile':'bank','/api/profile/information':'bank','/api/account/setup':'bank','/api/drive/check':'drive','/api/google/grant':'google','/api/analyze':'pdf','/api/draft':'pdf','/api/export/pdf':'pdf','/api/export/docx':'pdf','/api/background/jobs':'pdf'};
  const operation = value => /^(?:[a-f0-9]{32}|[a-f0-9]{8}(?:-[a-f0-9]{4}){3}-[a-f0-9]{12})$/i.test(value || '') ? value.toLowerCase() : crypto.randomUUID();
  async function flush() {
    if (running || !user || !queue.length) return;
    running = true;
    const expected = epoch, owner = user;
    const current = () => epoch === expected && user?.uid === owner.uid;
    try {
      const token = await owner.getIdToken();
      if (!current()) return;
      while (queue.length && current()) {
        const item = queue[0];
        if (Date.now() - item.at > 300000) { queue.shift(); continue; }
        const response = await fetch('/api/diagnostics/client', {method:'POST',cache:'no-store',signal:AbortSignal.timeout(10000),headers:{Authorization:`Bearer ${token}`,'Content-Type':'application/json','X-CV-Operation-ID':item.operationId},body:JSON.stringify(item.payload)});
        if (!current()) return;
        if (!response.ok && ![400,401,403,413,429].includes(response.status)) break;
        const index = queue.indexOf(item);
        if (index >= 0) queue.splice(index, 1);
      }
    } catch (_) { /* Retain at most twelve safe signals until online or next action. */ }
    finally { running = false; if (epoch !== expected && user && queue.length) void flush(); }
  }
  function report(detail) {
    if (!user || !detail) return;
    let payload;
    if (detail.service === 'drive-api' && detail.stage === 'oauth-authorization' && oauth.has(detail.code)) {
      payload = {component:detail.component === 'telegram' ? 'telegram':'google',service:'drive-api',stage:'oauth-authorization',result:detail.code === 'authorization_pending' ? 'pending':'error',code:detail.code};
    } else if (detail.service === 'api' && detail.stage === 'browser-request' && ['network_error','request_timeout'].includes(detail.code) && ['bank','google','pdf','telegram','drive'].includes(detail.component)) {
      payload = {component:detail.component,service:'api',stage:'browser-request',result:'error',code:detail.code};
    } else return;
    const operationId = operation(detail.operationId), key = operationId + ':' + payload.code;
    if (seen.has(key)) return;
    if (seen.size >= 128) seen.delete(seen.values().next().value);
    seen.add(key); if (queue.length >= 12) queue.shift();
    queue.push({operationId,payload,at:Date.now()}); void flush();
  }
  function network(url, error, id) {
    const component = routes[String(url).split('?')[0]];
    if (!component) return;
    report({component,service:'api',stage:'browser-request',code:['TimeoutError','AbortError'].includes(error?.name)?'request_timeout':'network_error',operationId:id});
  }
  function initialize(next) {
    if (user?.uid === next?.uid) { user = next; void flush(); return; }
    epoch++; user = next; queue.length = 0; seen.clear();
  }
  window.addEventListener('online', () => { void flush(); });
  window.cvClientSupervisor = {initialize,report,network};
})();
