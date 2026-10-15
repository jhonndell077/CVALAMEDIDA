(() => {
  'use strict';
  let closedBeforePrint = [];
  window.addEventListener('beforeprint', () => {
    closedBeforePrint = Array.from(document.querySelectorAll('details:not([open])'));
    closedBeforePrint.forEach(item => { item.open = true; });
  });
  window.addEventListener('afterprint', () => {
    closedBeforePrint.forEach(item => { item.open = false; });
    closedBeforePrint = [];
  });
})();
