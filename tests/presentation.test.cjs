const {test} = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs'), vm = require('node:vm');
const {parseHTML} = require('linkedom');
function setup() {
  const {document, window} = parseHTML(fs.readFileSync('static/index.html', 'utf8'));
  vm.runInNewContext(fs.readFileSync('static/presentation.js', 'utf8'), {document});
  return {document, window};
}
test('public CTAs use the existing vacancy opener without submitting an analysis', () => {
  const {document} = setup(); let opens = 0, submits = 0;
  document.getElementById('open-vacancy').addEventListener('click', () => opens++);
  document.getElementById('analyze-button').addEventListener('click', () => submits++);
  const buttons = [...document.querySelectorAll('[data-presentation-start]')];
  buttons.forEach(button => button.click());
  assert.equal(opens, 2); assert.equal(submits, 0);
});
test('illustrative preview switches by click and keyboard with matching ARIA state', () => {
  const {document, window} = setup();
  const job = document.getElementById('sample-job-tab'), cv = document.getElementById('sample-cv-tab');
  cv.click();
  assert.equal(cv.getAttribute('aria-selected'), 'true'); assert.equal(document.getElementById('sample-job').hidden, true);
  assert.equal(document.getElementById('sample-cv').hidden, false);
  const event = new window.Event('keydown', {cancelable: true}); event.key = 'ArrowRight'; cv.dispatchEvent(event);
  assert.equal(job.getAttribute('aria-selected'), 'true'); assert.equal(document.getElementById('sample-cv').hidden, true);
});
test('presentation preserves operational IDs and has navigable public anchors', () => {
  const {document} = setup();
  assert.equal(document.querySelectorAll('h1').length, 1);
  for (const id of ['telegram-link','open-onboarding','analyze-button','workspace-menu','job-panel','auth-panel','application-history-panel']) assert.equal(document.querySelectorAll('#' + id).length, 1);
  for (const a of document.querySelectorAll('.presentation-nav a')) assert.ok(document.querySelector(a.getAttribute('href')));
});
