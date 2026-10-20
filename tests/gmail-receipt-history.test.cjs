const {test}=require('node:test'),assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm');
const {parseHTML}=require('linkedom');
const source=fs.readFileSync('static/app.js','utf8');
test('Gmail acceptance shows sender and exact RFC message search without claiming delivery',()=>{
 const {document}=parseHTML('<div id="application-history"></div>');
 const id='12345678-1234-1234-1234-123456789012';
 const context={URLSearchParams,state:{applications:[{application_id:id,status:'gmail_accepted',channel:'gmail',sender:'sender@example.com',recipient:'recipient@example.com',date:'2026-10-20',position:'Job'}]},$:s=>document.querySelector(s),addText(parent,tag,text,cls){const e=document.createElement(tag);e.textContent=text;if(cls)e.className=cls;parent.append(e);return e;}};
 vm.runInNewContext(source.slice(source.indexOf('function renderApplications('),source.indexOf('async function refreshApplications(')),context);
 context.renderApplications();
 const text=document.body?.textContent||document.querySelector('#application-history').textContent;
 assert.match(text,/entrega al destinatario no verificada/);assert.match(text,/sender@example.com/);
 const link=document.querySelector('a');const url=new URL(link.getAttribute("href"));
 assert.equal(url.origin,'https://mail.google.com');assert.equal(url.searchParams.get('authuser'),'sender@example.com');
 assert.equal(url.searchParams.get('q'),`in:anywhere rfc822msgid:${id}@cvalamedida.web.app`);
});
test('legacy Gmail history remains readable without a sender or RFC search identifier',()=>{
 const {document}=parseHTML('<div id="application-history"></div>');
 const context={URLSearchParams,state:{applications:[{status:'gmail_accepted',channel:'gmail',date:'2026-10-20'}]},$:s=>document.querySelector(s),addText(p,t,v){const e=document.createElement(t);e.textContent=v;p.append(e);return e;}};
 vm.runInNewContext(source.slice(source.indexOf('function renderApplications('),source.indexOf('async function refreshApplications(')),context);context.renderApplications();
 assert.equal(document.querySelector('a'),null);assert.match(document.querySelector('#application-history').textContent,/cuenta de Google usada/);
});

