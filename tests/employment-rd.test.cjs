const {test}=require('node:test');
const assert=require('node:assert/strict');
const fs=require('node:fs'),vm=require('node:vm');
const {parseHTML}=require('linkedom');
const source=fs.readFileSync('static/employment.js','utf8');

function setup(response,fail=false,handler=null){
 const {window,document}=parseHTML(fs.readFileSync('static/index.html','utf8'));
 const dialog=document.querySelector('#employment-results-dialog');
 dialog.showModal=()=>{dialog.open=true;dialog.setAttribute('open','');};
 dialog.close=()=>{dialog.open=false;dialog.removeAttribute('open');};
 const contactDialog=document.querySelector('#employment-contact-dialog');
 contactDialog.showModal=()=>{contactDialog.open=true;};contactDialog.close=()=>{contactDialog.open=false;};
 document.querySelector('#employment-contact-form').reportValidity=()=>true;
 const calls=[],messages=[],adapted=[];
 const context=vm.createContext({URL,root:{document},$:s=>document.querySelector(s),status:text=>messages.push(text),
 request:async(path,method,payload)=>{calls.push({path,method,payload});if(fail)throw Error('Fuente no disponible');return handler ? handler(path,method,payload) : response;},
 useGenerator:(offer,contact)=>{adapted.push({...offer,contact});dialog.close();},renderApplications:async()=>{}});
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

test('unified cards display their own source, filtered calendar and undated offers',async()=>{
 const official={...offer,id:'official',source_key:'rdtrabaja',source:'RD Trabaja',url:'https://rdtrabaja.mt.gob.do/',published_at:'2026-10-14T13:00:00Z',source_link_home:true};
 const brief={...offer,id:'brief',source_key:'tuvacanterd',source:'TuVacanteRD',url:'https://tuvacanterd.com/empleo/cajero',published_at:null,description_verified:false};
 const qa=setup({national:true,offers:[{...offer,source_key:'chiripas',source:'Chiripas'},official,brief],sources:[
  {key:'chiripas',name:'Chiripas',status:'ok',count:1,url:'https://chiripas.com/'},
  {key:'aldaba',name:'Aldaba',status:'external',count:0,url:'https://www.aldaba.com/buscar.php?q=Cajero',message:'Consulta directa'},
  {key:'tuempleord',name:'TuEmpleoRD',status:'unavailable',count:0,url:'https://tuempleord.do/'}],partial:true});
 await qa.context.searchJobs(true);
 assert.equal(qa.document.querySelectorAll('#employment-sources .employment-source-row').length,3);
 assert.match(qa.document.querySelector('#employment-results-status').textContent,/Algunas fuentes no respondieron/);
 assert.match(qa.document.querySelectorAll('#employment-results .employment-source')[1].textContent,/Ver este anuncio y añadir contacto/);
 const select=qa.document.querySelector('#employment-source-filter');
 Object.defineProperty(select,'value',{value:'rdtrabaja',writable:true,configurable:true});
 select.dispatchEvent(new qa.window.Event('change'));
 assert.equal(qa.document.querySelectorAll('#employment-results article').length,1);
 assert.equal(qa.document.querySelector('#employment-calendar-undated').hidden,true);
 const days=[...qa.document.querySelectorAll('#employment-calendar-days button')];
 assert.equal(days.find(day=>day.textContent==='14 · 1').getAttribute('aria-pressed'),'false');
 select.value='';select.dispatchEvent(new qa.window.Event('change'));
 qa.document.querySelector('#employment-calendar-undated').click();
 assert.equal(qa.document.querySelectorAll('#employment-results article').length,1);
 assert.match(qa.document.querySelector('#employment-results button').textContent,/Añadir requisitos/);
 assert.equal(qa.calls.length,1);
});

test('all failed sources show consultation failure instead of no-vacancy success',async()=>{
 const qa=setup({national:true,offers:[],sources:[{key:'chiripas',name:'Chiripas',status:'unavailable',count:0,url:'https://chiripas.com/'}],partial:true});
 await qa.context.searchJobs(true);
 assert.match(qa.document.querySelector('#employment-results').textContent,/No se pudieron consultar/);
});

test('untrusted destinations cannot become portal or offer links',async()=>{
 const qa=setup({national:true,offers:[{...offer,url:'javascript:alert(1)'}],sources:[{key:'fixture',name:'Texto <script>',status:'external',url:'https://evil.invalid'}]});
 await qa.context.searchJobs(true);
 assert.equal(qa.document.querySelector('#employment-sources a'),null);
 assert.equal(qa.document.querySelector('#employment-results .employment-source').hasAttribute('href'),false);
 assert.equal(qa.document.querySelector('#employment-sources script'),null);
});

test('brief listings require pasted requirements before the CV generator is invoked',async()=>{
 const brief={...offer,source_key:'tuvacanterd',source:'TuVacanteRD',url:'https://tuvacanterd.com/empleo/cajero',description_verified:false};
 const qa=setup({national:true,offers:[brief]});await qa.context.searchJobs(true);
 const form=qa.document.querySelector('#employment-external-form');
 const fields=Object.fromEntries(['source','url','title','description'].map(name=>[name,{value:'old',focus(){}}]));
 form.elements={namedItem:name=>fields[name]};form.scrollIntoView=()=>{};
 vm.runInContext(source.slice(source.indexOf('  async function useGenerator(offer'),source.indexOf('  async function request(')),qa.context);
 qa.document.querySelector('#employment-results button').click();
 await new Promise(setImmediate);
 assert.equal(fields.source.value,'tuvacanterd');assert.equal(fields.description.value,'');
 assert.equal(fields.url.value,brief.url);assert.equal(fields.title.value,brief.title);
 assert.equal(qa.document.querySelector('#employment-external-tools').open,true);
 assert.equal(qa.document.querySelector('#employment-external-original').getAttribute('href'),brief.url);
 assert.equal(qa.document.querySelector('#employment-results-dialog').open,false);
 assert.equal(qa.adapted.length,0);
});

test('original ad opens normally and contact popup loads and saves the selected vacancy',async()=>{
 const response={national:true,offers:[offer]};
 const qa=setup(response,false,(path,method,payload)=>path==='search' ? response : {contact:method==='PUT' ? payload : {email:'jobs@example.invalid',whatsapp:'+18095550123'}});
 await qa.context.searchJobs(true);
 const link=qa.document.querySelector('#employment-results .employment-source');
 const click=new qa.window.Event('click',{cancelable:true});link.dispatchEvent(click);
 await new Promise(setImmediate);
 assert.equal(click.defaultPrevented,false);assert.equal(link.getAttribute('href'),offer.url);assert.equal(link.target,'_blank');
 assert.equal(qa.document.querySelector('#employment-contact-dialog').open,true);
 assert.equal(qa.document.querySelector('#employment-results-dialog').open,false);
 assert.equal(qa.document.querySelector('#employment-contact-email').value,'jobs@example.invalid');
 qa.document.querySelector('#employment-contact-email').value='updated@example.invalid';
 qa.document.querySelector('#employment-contact-form').dispatchEvent(new qa.window.Event('submit',{cancelable:true}));
 await new Promise(setImmediate);
 assert.equal(qa.calls.at(-1).method,'PUT');assert.equal(qa.calls.at(-1).path,'offers/fixture/contact');
 assert.equal(qa.calls.at(-1).payload.email,'updated@example.invalid');
 assert.match(qa.document.querySelector('#employment-contact-status').textContent,/Contacto guardado/);
});

test('RD Trabaja opens the exact selected announcement in the popup, not a generic page',async()=>{
 const selected={...offer,source_key:'rdtrabaja',source:'RD Trabaja',source_job_id:'81060',url:'https://rdtrabaja.mt.gob.do/#/empleo/buscar-empleo?titulo=Cajero'};
 const qa=setup({national:true,offers:[selected]});await qa.context.searchJobs(true);
 const click=new qa.window.Event('click',{cancelable:true});qa.document.querySelector('#employment-results .employment-source').dispatchEvent(click);
 await new Promise(setImmediate);
 assert.equal(click.defaultPrevented,true);
 assert.match(qa.document.querySelector('#employment-contact-source').textContent,/81060/);
 assert.equal(qa.document.querySelector('#employment-contact-description').textContent,offer.description);
 assert.equal(qa.document.querySelector('#employment-contact-original').getAttribute('href'),selected.url);
});

test('late contact replies cannot repopulate a dismissed popup',async()=>{
 let resolveContact;
 const qa=setup({national:true,offers:[offer]},false,(path)=>path==='search' ? {national:true,offers:[offer]} : new Promise(resolve=>{resolveContact=resolve;}));
 await qa.context.searchJobs(true);
 const pending=qa.context.openOfferContact(offer);
 qa.document.querySelector('#employment-contact-close').click();
 resolveContact({contact:{email:'private@example.invalid',whatsapp:''}});await pending;
 assert.equal(qa.document.querySelector('#employment-contact-email').value,'');
 assert.equal(qa.document.querySelector('#employment-contact-dialog').open,false);
 assert.equal(qa.document.querySelector('#employment-contact-save').disabled,true);
});

test('closing contact restores the same search and date without another query',async()=>{
 const qa=setup({national:true,offers:[offer]});await qa.context.searchJobs(true);
 const day=[...qa.document.querySelectorAll('#employment-calendar-days button')].find(button=>button.textContent==='13 · 1');day.click();
 await qa.context.openOfferContact(offer);
 qa.document.querySelector('#employment-contact-close').click();
 assert.equal(qa.document.querySelector('#employment-results-dialog').open,true);
 assert.equal(qa.document.querySelector('#employment-contact-dialog').open,false);
 assert.equal(qa.document.querySelector('[aria-pressed="true"]').textContent,'13 · 1');
 assert.equal(qa.calls.filter(call=>call.path==='search').length,1);
});

test('adapt from contact saves before generation and passes normalized contact for the selected job',async()=>{
 const qa=setup({national:true,offers:[offer]},false,(path,method)=>path==='search' ? {national:true,offers:[offer]} : {contact:method==='PUT' ? {email:'recruiter@example.invalid',whatsapp:'+18095550123'} : {email:'',whatsapp:''}});
 await qa.context.searchJobs(true);await qa.context.openOfferContact(offer);
 qa.document.querySelector('#employment-contact-email').value='recruiter@example.invalid';
 qa.document.querySelector('#employment-contact-whatsapp').value='8095550123';
 qa.document.querySelector('#employment-contact-adapt').click();await new Promise(setImmediate);
 assert.equal(qa.calls.at(-1).method,'PUT');assert.equal(qa.calls.at(-1).path,'offers/fixture/contact');
 assert.equal(qa.adapted.length,1);assert.equal(qa.adapted[0].id,offer.id);
 assert.equal(qa.adapted[0].contact.whatsapp,'+18095550123');
 assert.equal(qa.document.querySelector('#employment-results-dialog').open,false);
 assert.equal(qa.document.querySelector('#employment-contact-dialog').open,false);
});

test('save failure preserves contact input and blocks generation',async()=>{
 const qa=setup({national:true,offers:[offer]},false,(path,method)=>{if(method==='PUT')throw Error('No se pudo guardar');return path==='search' ? {national:true,offers:[offer]} : {contact:{email:'',whatsapp:''}};});
 await qa.context.searchJobs(true);await qa.context.openOfferContact(offer);
 qa.document.querySelector('#employment-contact-email').value='recruiter@example.invalid';
 qa.document.querySelector('#employment-contact-adapt').click();await new Promise(setImmediate);
 assert.equal(qa.adapted.length,0);assert.equal(qa.document.querySelector('#employment-contact-dialog').open,true);
 assert.equal(qa.document.querySelector('#employment-contact-email').value,'recruiter@example.invalid');
 assert.equal(qa.document.querySelector('#employment-contact-adapt').disabled,false);
});

test('adaptation from a result retrieves saved contact and includes it in the analysis text',async()=>{
 const contact={email:'recruiter@example.invalid',whatsapp:'+18095550123'};
 const qa=setup({national:true,offers:[offer]},false,path=>path==='search' ? {national:true,offers:[offer]} : {contact});
 let detail;
 qa.context.root.CustomEvent=qa.window.CustomEvent;qa.context.root.dispatchEvent=event=>{detail=event.detail;return false;};
 vm.runInContext(source.slice(source.indexOf('  async function useGenerator(offer'),source.indexOf('  async function request(')),qa.context);
 await qa.context.searchJobs();
 await qa.context.useGenerator(offer);
 assert.equal(qa.calls.at(-1).path,'offers/fixture/contact');
 assert.equal(detail.contact.email,contact.email);assert.match(detail.text,/Correo de postulación: recruiter@example.invalid/);
 assert.match(detail.text,/WhatsApp de postulación: \+18095550123/);
});
