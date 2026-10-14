(() => {
  let pendingStep = 0;
  const panels = ['job-panel', 'analysis-panel', 'cv-panel'];
  function revealStep() {
    if (!pendingStep || document.body.classList.contains('is-loading')) return;
    const panel = document.getElementById(panels[pendingStep - 1]);
    pendingStep = 0;
    if (!panel || panel.hidden || document.querySelector('dialog[open]')) return;
    const heading = panel.querySelector('h2') || panel;
    heading.tabIndex = -1;
    heading.focus({preventScroll: true});
    panel.scrollIntoView({block: 'start', behavior: matchMedia('(prefers-reduced-motion: reduce)').matches ? 'instant' : 'smooth'});
  }
  window.cvUI = {showStep(step) {pendingStep = step; requestAnimationFrame(revealStep);}};
  new MutationObserver(revealStep).observe(document.body, {attributes: true, attributeFilter: ['class']});
})();
