const {test} = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
test('creating the CV renders it and automatically dispatches Gmail once', async () => {
  const calls = [], elements = new Map(); let handler;
  const $ = selector => {
    if (!elements.has(selector)) elements.set(selector, {addEventListener: (_, callback) => {handler = callback;}});
    return elements.get(selector);
  };
  const context = vm.createContext({$, window: {}, state: {analysis: {}}, clearError() {}, setBusy() {},
    requestJson: async () => ({draft: {position: 'Chef'}}), renderDraft: async () => calls.push('preview'),
    analysisPanel: {}, cvPanel: {}, setActiveStep() {}, sendApplicationGmail: async () => calls.push('gmail')});
  const source = fs.readFileSync('static/app.js', 'utf8');
  vm.runInContext(source.slice(source.indexOf('$("#create-button").addEventListener'), source.indexOf('function addPreviewSection')), context);
  $('#gmail-automatic').checked = true;
  await handler({currentTarget: {}});
  assert.deepEqual(calls, ['preview', 'gmail']);
  assert.equal(context.window.cvDraftAnalyses.get(context.state.draft), context.state.analysis);
  assert.equal(context.cvPanel.hidden, false);
  assert.ok(fs.readFileSync('static/index.html', 'utf8').includes('id="send-gmail"'));
});
