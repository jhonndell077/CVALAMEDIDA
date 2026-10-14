(() => {
  'use strict';
  const dialog = document.querySelector('#data-dialog');
  const button = document.querySelector('#data-toggle');
  const panel = document.querySelector('#profile-panel');
  const closeButton = document.querySelector('#data-close');
  const actions = document.querySelector('#data-actions');
  const actionsHome = actions.parentNode;
  const syncButton = document.querySelector('#data-sync');
  const originalSync = document.querySelector('#sync-bank');
  const unavailable = document.querySelector('#data-unavailable');
  // Move the original nodes: all listeners, counters and profile state stay intact.
  document.querySelector('#data-content').append(panel);
  let closing = false;
  let scrollY = 0;
  let bodyStyle;
  let opener;
  const reduced = matchMedia('(prefers-reduced-motion: reduce)');
  function motion(opening) {
    if (reduced.matches || !dialog.animate) return Promise.resolve();
    const frames = [{opacity: 0, transform: 'translateY(24px)'}, {opacity: 1, transform: 'translateY(0)'}];
    return dialog.animate(opening ? frames : frames.slice().reverse(), {duration: 180, easing: 'ease-out'}).finished.catch(() => {});
  }
  function unlock() {
    actionsHome.append(actions);
    if (!bodyStyle) return;
    Object.assign(document.body.style, bodyStyle);
    bodyStyle = null;
    window.scrollTo({top: scrollY, behavior: 'instant'});
    button.setAttribute('aria-expanded', 'false');
    if (opener?.isConnected && !opener.hidden) opener.focus({preventScroll: true});
  }
  async function close() {
    if (!dialog.open || closing) return;
    closing = true;
    await motion(false);
    dialog.close();
    closing = false;
  }
  button.addEventListener('click', () => {
    if (closing) return;
    if (dialog.open) { close(); return; }
    opener = document.activeElement;
    scrollY = window.scrollY;
    bodyStyle = Object.fromEntries(['position', 'top', 'width', 'overflow', 'paddingRight'].map(key => [key, document.body.style[key]]));
    const gutter = window.innerWidth - document.documentElement.clientWidth;
    Object.assign(document.body.style, {position: 'fixed', top: `-${scrollY}px`, width: '100%', overflow: 'hidden', paddingRight: `${gutter}px`});
    dialog.append(actions); // Keep both controls in the modal's top layer too.
    dialog.showModal(); // Native modal supplies focus containment and inert background.
    button.setAttribute('aria-expanded', 'true');
    closeButton.focus({preventScroll: true});
    motion(true);
  });
  closeButton.addEventListener('click', close);
  dialog.addEventListener('keydown', event => {
    if (event.key !== 'Tab' || event.defaultPrevented) return;
    const focusable = [...dialog.querySelectorAll('button, a[href], input, select, textarea, summary, [tabindex]')]
      .filter(element => !element.disabled && element.tabIndex >= 0 && element.getClientRects().length);
    const first = focusable[0];
    const last = focusable[focusable.length - 1];
    if (event.shiftKey && document.activeElement === first) {
      event.preventDefault(); last?.focus();
    } else if (!event.shiftKey && document.activeElement === last) {
      event.preventDefault(); first?.focus();
    }
  });
  dialog.addEventListener('cancel', event => {event.preventDefault(); close();});
  dialog.addEventListener('close', unlock);
  let outside = false;
  function isOutside(event) {
    const rect = dialog.getBoundingClientRect();
    return event.clientX < rect.left || event.clientX > rect.right || event.clientY < rect.top || event.clientY > rect.bottom;
  }
  dialog.addEventListener('pointerdown', event => {outside = event.target === dialog && isOutside(event);});
  dialog.addEventListener('click', event => {
    if (outside && event.target === dialog && isOutside(event)) close();
    outside = false;
  });
  function availability() {
    unavailable.hidden = !panel.hidden;
  }
  new MutationObserver(availability).observe(panel, {attributes: true, attributeFilter: ['hidden']});
  availability();
  syncButton.addEventListener('click', () => originalSync.click());
  const syncAvailability = () => { syncButton.disabled = originalSync.disabled; };
  new MutationObserver(syncAvailability).observe(originalSync, {attributes: true, attributeFilter: ['disabled']});
  syncAvailability();
  let updateBanner;
  const measureBanner = () => {
    document.documentElement.style.setProperty('--cv-update-height', `${updateBanner?.getBoundingClientRect().height || 0}px`);
  };
  const bannerResize = window.ResizeObserver ? new ResizeObserver(measureBanner) : null;
  function observeBanner() {
    const next = document.querySelector('.update-banner');
    if (next === updateBanner) return;
    if (updateBanner) bannerResize?.unobserve(updateBanner);
    updateBanner = next;
    if (updateBanner) bannerResize?.observe(updateBanner);
    measureBanner();
  }
  new MutationObserver(observeBanner).observe(document.body, {childList: true});
  window.addEventListener('resize', measureBanner);
  observeBanner();
})();
