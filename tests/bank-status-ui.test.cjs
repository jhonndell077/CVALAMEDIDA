const {test}=require('node:test');
const assert=require('node:assert/strict');
const fs=require('node:fs'),vm=require('node:vm');
const {parseHTML}=require('linkedom');
const source=fs.readFileSync('static/app.js','utf8');
function setup(){
 const {document}=parseHTML(fs.readFileSync('static/index.html','utf8'));
 const context=vm.createContext({document,state:{},$:selector=>document.querySelector(selector),
  addText(parent,tag,text){const element=document.createElement(tag);element.textContent=text;parent.append(element);}});
 vm.runInContext(source.slice(source.indexOf('function bankSyncBlocked('),source.indexOf('async function startBankSynchronization(')),context);
 vm.runInContext(source.slice(source.indexOf('function renderBankStatus('),source.indexOf('async function synchronizeBank(')),context);
 return {document,render:context.renderBankStatus};
}
test('a rejected document opens review and never presents the bank as synchronized',()=>{
 const q=setup();q.render({pending:0,sync:{state:'blocked',blockingCount:1},warnings:[{name:'Certificado',message:'Revisar titular',severity:'blocking'}],documents:[]});
 assert.equal(q.document.querySelector('#bank-review').open,true);
 assert.match(q.document.querySelector('#bank-status').textContent,/requieren revisión/);
 assert.match(q.document.querySelector('#bank-warnings').textContent,/Certificado: Revisar titular/);
});
test('informative notes preserve successful synchronization without hiding their content',()=>{
 const q=setup();q.render({pending:0,sync:{state:'ready',noticeCount:1},warnings:[{name:'Curso',message:'Fecha conservada',severity:'notice'}],documents:[]});
 assert.match(q.document.querySelector('#bank-status').textContent,/Banco sincronizado/);
 assert.match(q.document.querySelector('#bank-warnings').textContent,/Observación · Curso: Fecha conservada/);
});
test('document labels and notes remain text instead of executable markup',()=>{
 const q=setup();q.render({pending:0,warnings:[{name:'<img src=x>',message:'<script>bad()</script>'}],documents:[]});
 assert.equal(q.document.querySelector('#bank-warnings img'),null);
 assert.equal(q.document.querySelector('#bank-warnings script'),null);
});
