(() => {
  'use strict';
  let user = null, epoch = 0, snapshot = null, loading = null, notice = null, dialog = null;
  const seen = new Set();
  const node = (tag, text, cls) => { const element = document.createElement(tag); if (text !== undefined) element.textContent = text; if (cls) element.className = cls; return element; };
  function remember(key) { seen.add(key); try { localStorage.setItem(key, '1'); } catch (_) {} }
  function known(key) { if (seen.has(key)) return true; try { return localStorage.getItem(key) === '1'; } catch (_) { return false; } }
  function clear() { notice?.remove(); notice = null; dialog?.remove(); dialog = null; }
  const label = plan => plan?.label || plan?.name || plan?.id || 'Básico';
  const planId = plan => plan?.id || plan?.name || 'basic';
  const version = () => JSON.stringify([snapshot?.changeVersion || snapshot?.assignmentVersion || 'basic', snapshot?.plan?.name || snapshot?.plan?.id || 'basic', snapshot?.limits]);
  function showNotice(text, key, plans, changed = false) {
    if (known(key) && !changed) return;
    if (notice && !plans && !changed) return;
    notice?.remove();
    notice = node('aside', undefined, 'subscription-notice'); notice.setAttribute('role', 'status'); notice.setAttribute('aria-live', 'polite');
    notice.append(node('p', text));
    if (plans) { const button = node('button', 'Ver planes'); button.type = 'button'; button.addEventListener('click', openPlans); notice.append(button); }
    const close = node('button', 'Cerrar aviso', 'subscription-dismiss'); close.type = 'button'; close.setAttribute('aria-label', 'Cerrar aviso de plan');
    close.addEventListener('click', () => { remember(key); notice?.remove(); notice = null; }); notice.append(close);
    const setup = document.querySelector('#required-sync');
    if (setup && !setup.hidden) setup.prepend(notice); else document.body.append(notice);
    if (plans) remember(key); // Welcome is acknowledged only when it is dismissed.
  }
  function welcome(changed = false) {
    const plan = snapshot?.plan;
    if (!user || !snapshot || (!snapshot.limits && !plan)) return;
    const catalog = snapshot.planCatalog || [];
    const assigned = catalog.find(item => item.id === planId(plan)) || plan || {};
    const benefits = (snapshot.benefits || assigned.benefits || []).map(String);
    const limits = snapshot.limits || assigned;
    const usage = snapshot.usage;
    const details = ` Puedes generar ${limits.daily ?? 'por confirmar'} CV al día y ${limits.monthly ?? 'por confirmar'} al mes.` +
      (usage ? ` Disponibles: ${usage.dailyRemaining} hoy y ${usage.monthlyRemaining} este mes.` : '') +
      (benefits.length ? ` Disfruta de: ${benefits.join(' · ')}.` : '');
    showNotice(`Bienvenid@ ${user.displayName || ''}, tienes asignado el plan ${snapshot.planLabel || label(assigned)}.${details}`, `cv-plan:welcome:${user.uid}:${version()}`, false, changed);
  }
  async function refresh() {
    if (!user) return null;
    if (loading) return loading;
    const owner = user, expected = epoch;
    const current = () => epoch === expected && user?.uid === owner.uid;
    const promise = (async () => {
      const token = await owner.getIdToken();
      if (!current()) return null;
      const response = await fetch('/api/subscription', {headers: {Authorization: `Bearer ${token}`}});
      const data = await response.json();
      if (!current() || !response.ok) return null;
      const previous = snapshot ? version() : null;
      snapshot = data; welcome(previous !== null && previous !== version()); return data;
    })().catch(() => null).finally(() => { if (current()) loading = null; });
    loading = promise; return promise;
  }
  async function initialize(next) {
    if (next && user?.uid === next.uid) { user = next; return refresh(); }
    epoch++; clear(); user = next; snapshot = null; loading = null; if (next) await refresh();
  }
  async function observe(response, data) {
    if (!user || response?.status !== 429 || data?.code !== 'period_quota_exceeded') return;
    const owner = user.uid, expected = epoch;
    await refresh();
    if (!user || user.uid !== owner || epoch !== expected) return;
    const quotaPeriod = ['month', 'monthly'].includes(data.period) ? 'monthly' : ['day', 'daily'].includes(data.period) ? 'daily' : 'period';
    const period = quotaPeriod === 'monthly' ? 'mensual' : quotaPeriod === 'daily' ? 'diario' : 'del período';
    const plan = snapshot?.plan;
    const assigned = (snapshot?.planCatalog || []).find(item => item.id === planId(plan)) || plan;
    showNotice(`Consumiste el límite ${period} de tu plan ${snapshot?.planLabel || label(assigned)}. Consulta los planes para ampliar tus operaciones.`, `cv-plan:quota:${owner}:${version()}:${quotaPeriod}:${data.resetsAt || data.resetAt || (quotaPeriod === 'monthly' ? snapshot?.usage?.month : snapshot?.usage?.day) || ''}`, true);
  }
  function openPlans() {
    if (!user || !snapshot) return;
    dialog?.remove(); dialog = node('dialog', undefined, 'subscription-plans'); dialog.setAttribute('aria-labelledby', 'subscription-plans-title');
    const heading = node('h2', 'Planes disponibles'); heading.id = 'subscription-plans-title'; dialog.append(heading);
    dialog.append(node('p', 'Más operaciones para adaptar tus postulaciones.'));
    const list = node('div', undefined, 'subscription-plan-list');
    for (const plan of snapshot.planCatalog || []) {
      const card = node('article'); card.append(node('h3', label(plan)));
      card.append(node('p', plan.priceMinor === null || plan.priceMinor === undefined ? 'Precio por confirmar' : `${(Number(plan.priceMinor) / 100).toFixed(2)} ${plan.currency || 'DOP'}`));
      card.append(node('p', `Operaciones: ${plan.daily ?? 'por confirmar'} al día · ${plan.monthly ?? 'por confirmar'} al mes`));
      const benefits = node('ul'); for (const benefit of plan.benefits || snapshot.benefits || []) benefits.append(node('li', String(benefit))); card.append(benefits); list.append(card);
    }
    dialog.append(list); dialog.append(node('p', 'Cobro manual. El estado de pago requiere verificación.'));
    const close = node('button', 'Cerrar planes'); close.type = 'button'; close.addEventListener('click', () => { dialog?.close?.(); dialog?.remove(); dialog = null; }); dialog.append(close);
    document.body.append(dialog); if (dialog.showModal) dialog.showModal(); else dialog.setAttribute('open', '');
  }
  window.addEventListener?.('focus', () => { refresh(); });
  const refreshTimer = window.setInterval?.(() => { if (user && !document.hidden) refresh(); }, 60000);
  refreshTimer?.unref?.();
  window.cvSubscription = {initialize, observe, openPlans, refresh};
})();
