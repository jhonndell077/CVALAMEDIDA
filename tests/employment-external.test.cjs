const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const {parseHTML} = require('linkedom');
const {sources, vacancy} = require('../static/employment-external.js');

test('seis portales externos; rechaza destinos ajenos y credenciales', () => {
  assert.equal(Object.keys(sources).length, 6);
  for (const [id, [, url]] of Object.entries(sources)) assert.equal(vacancy(id, url, 'Cargo', 'Datos').url, url);
  for (const url of ['https://chiripas.com.evil.invalid/', 'javascript:alert(1)', 'https://user:pass@chiripas.com/', 'http://chiripas.com/']) {
    assert.throws(() => vacancy('chiripas', url, 'Cargo', 'Datos'));
  }
  assert.throws(() => vacancy('unknown', 'https://chiripas.com/', 'Cargo', 'Datos'));
  assert.throws(() => vacancy('chiripas', 'https://chiripas.com/', '', 'Datos'));
});

test('removed manual portal form is absent and its retired module safely ignores the page', () => {
  const {window}=parseHTML(fs.readFileSync('static/index.html','utf8'));
  assert.equal(window.document.querySelector('#employment-external-tools'),null);
  assert.equal(window.document.querySelector('#employment-external-form'),null);
  assert.equal(window.document.querySelector('#employment-applications'),null);
  vm.runInNewContext(fs.readFileSync('static/employment-external.js','utf8'),{window,URL,Object,Error});
});