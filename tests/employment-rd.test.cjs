const {test}=require('node:test');
const assert=require('node:assert/strict');
const fs=require('node:fs'),vm=require('node:vm');
const {parseHTML}=require('linkedom');
const source=fs.readFileSync('static/employment.js','utf8');

function setup(response,fail=false){
 const {window,document}=parseHTML(fs.readFileSync('static/index.html','utf8'));
 const dialog=document.querySelector('#employment-results-dialog');
 dialog.showModal=()=>{dialog.open=true;dialog.setAttribute('open','');};
 dialog.close=()=>{dialog.open=false;dialog.removeAttribute('open');};
 const calls=[],messages=[],adapted=[];
 const context=vm.createContext({root:{document},$:s=>document.querySelector(s),status:text=>messages.push(text),
 request:async(path,method,payload)=>{calls.push({path,payload});if(fail)throw Error('Fuente no disponible');return response;},
 useGenerator:offer=>adapted.push(offer),renderApplications:async()=>{}});
 vm.runInContext(source.slice(source.indexOf('  let latestPublications = null'),source.indexOf("  $('#employment-revoke').addEventListener")),context);
 return {context,window,document,calls,messages,adapted};
}
const offer={id:'fixture',title:'Cajero',company:'Empresa',url:'https://chiripas.com/empleo/cajero/1',description:'Funciones <script>texto</script>',published_at:'2026-10-13T13:00:00+00:00'};

test('one job title produces RD results without GPS and can adapt the CV',async()=>{
 const qa=setup({national:true,offers:[offer]});qa.document.querySelector('#employment-query').value='Cajero';
 await qa.context.searchJobs();assert.equal(qa.calls.length,1);assert.equal(qa.calls[0].payload.source,'rd');assert.equal(qa.calls[0].payload.query,'Cajero');
 assert.equal(qa.document.querySelectorAll('#employment-results article').length,1);
 assert.equal(qa.document.querySelector('#employment-results script'),null);
 qa.document.querySelector('#employment-results button').click();assert.equal(qa.adapted[0].id,offer.id);
 assert.equal(qa.document.querySelector('#employment-search-button').disabled,false);
});
test('latest published ignores the title and returns every available entry',async()=>{
 const qa=setup({national:true,offers:[offer,{...offer,id:'second',title:'Chef'}]});qa.document.querySelector('#employment-query').value='Cajero';
 await qa.context.searchJobs(true);assert.equal(qa.calls[0].payload.query,'');assert.equal(qa.calls[0].payload.latest,true);
 assert.equal(qa.document.querySelectorAll('#employment-results article').length,2);
});
test('source failures and empty results release both search buttons',async()=>{
 for(const fail of [false,true]){
  const qa=setup({national:true,offers:[]},fail);await qa.context.searchJobs(true);
  assert.equal(qa.document.querySelector('#employment-latest').disabled,false);
  assert.match(fail?qa.messages.at(-1):qa.document.querySelector('#employment-results').textContent,fail?/Fuente no disponible/:/No hay vacantes/);
 }
});
test('search is above optional location and international providers are absent',()=>{
 const qa=setup({national:true,offers:[]});
 const html=fs.readFileSync('static/index.html','utf8');
 assert.ok(html.indexOf('id="employment-search-form"')<html.indexOf('id="employment-location-options"'));
 assert.equal(qa.document.querySelector('#employment-location-options').hasAttribute('open'),false);
 assert.equal(qa.document.querySelector('#employment-source'),null);
 assert.doesNotMatch(qa.document.querySelector('#employment-panel').textContent,/Himalayas|HiringCafe/);
});


test('calendar filters the selected RD date without querying the source again',async()=>{
 const qa=setup({national:true,offers:[offer,{...offer,id:'previous',title:'Chef',published_at:'2026-10-13T02:00:00+00:00'},{...offer,id:'undated',published_at:null}]});
 await qa.context.searchJobs(true);
 assert.equal(qa.document.querySelector('#employment-calendar').hidden,false);
 assert.equal(qa.document.querySelector('#employment-calendar-month').textContent,'octubre de 2026');
 const days=[...qa.document.querySelectorAll('#employment-calendar-days button')];
 days.find(day=>day.textContent.startsWith('12 ·')).click();
 assert.equal(qa.document.querySelectorAll('#employment-results article').length,1);
 assert.equal(qa.document.querySelector('#employment-results h3').textContent,'Chef');
 assert.equal(qa.calls.length,1);
 assert.equal(days.find(day=>day.textContent.startsWith('13 ·')).textContent,'13 · 1');
 qa.document.querySelector('#employment-calendar-all').click();
 assert.equal(qa.document.querySelectorAll('#employment-results article').length,3);
});

test('calendar supports month navigation and empty days',async()=>{
 const qa=setup({national:true,offers:[offer]});await qa.context.searchJobs(true);
 qa.document.querySelector('#employment-calendar-prev').click();
 assert.match(qa.document.querySelector('#employment-calendar-month').textContent,/septiembre/);
 qa.document.querySelector('#employment-calendar-days button').click();
 assert.match(qa.document.querySelector('#employment-results').textContent,/No hay publicaciones disponibles/);
 qa.document.querySelector('#employment-calendar-next').click();
 assert.match(qa.document.querySelector('#employment-calendar-month').textContent,/octubre/);
 assert.equal(qa.calls.length,1);
});

test('publication dates use Santo Domingo even near UTC midnight',()=>{
 const qa=setup({national:true,offers:[]});
 assert.equal(qa.context.publicationDate('2026-10-14T02:00:00Z'),'2026-10-13');
 assert.equal(qa.context.publicationDate(null),'');
 assert.equal(qa.context.publicationDate('invalid'),'');
});

test('offers and calendar stay in a dismissible dialog and reopen without another request',async()=>{
 const qa=setup({national:true,offers:[offer]});
 const dialog=qa.document.querySelector('#employment-results-dialog');
 assert.equal(dialog.hasAttribute('open'),false);
 await qa.context.searchJobs(true);
 assert.equal(dialog.open,true);
 assert.equal(dialog.querySelectorAll('#employment-results article').length,1);
 assert.ok(dialog.querySelector('#employment-calendar'));
 qa.document.querySelector('#employment-results-close').click();
 assert.equal(dialog.open,false);
 qa.document.querySelector('#employment-results-open').click();
 assert.equal(dialog.open,true);assert.equal(qa.calls.length,1);
 qa.document.querySelector('#employment-results button').click();
 assert.equal(dialog.open,false);assert.equal(qa.adapted.length,1);
});
test('closing while loading does not reopen the dialog when results arrive',async()=>{
 const qa=setup({national:true,offers:[offer]});
 const pending=qa.context.searchJobs(true);
 qa.document.querySelector('#employment-results-close').click();
 await pending;
 assert.equal(qa.document.querySelector('#employment-results-dialog').open,false);
 assert.equal(qa.document.querySelectorAll('#employment-results article').length,1);
});
