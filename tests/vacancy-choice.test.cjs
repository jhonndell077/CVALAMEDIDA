const assert = require('node:assert/strict');
const test = require('node:test');
const fs = require('node:fs');
const vm = require('node:vm');
const source = fs.readFileSync('static/app.js', 'utf8');
function setup() {
  const elements = new Map();
  function element() { return {hidden:true, children:[], listeners:{}, replaceChildren(){this.children=[];}, querySelectorAll(){return this.children;}, scrollIntoView(){}, addEventListener(type, fn){this.listeners[type]=fn;}}; }
  const $ = key => { if(!elements.has(key)) elements.set(key, element()); return elements.get(key); };
  const context = vm.createContext({window:{addEventListener(){},cvBackground:{enabled:()=>false}}, $, state:{}, jobPanel:element(), analysisPanel:element(), cvPanel:element(), setBusy(){}, clearError(){}, showError(message){context.error=message;}, renderAnalysis(analysis){context.rendered=analysis;}, setActiveStep(){}, addText(parent,tag,text){const child=element();child.textContent=text;parent.children.push(child);return child;}, requestJson:async(url,payload)=>{context.payload=payload;return {analysis:{vacancy:{position:payload.selected_position}},model:'test'};}});
  vm.runInContext(source.slice(source.indexOf('function handleVacancyResponse'),source.indexOf('function setActiveStep')),context);
  vm.runInContext(source.slice(source.indexOf('async function analyzeVacancyRequest'),source.indexOf('jobTextInput.addEventListener')),context);
  return {context,$};
}
test('web waits for an explicit choice and analyzes only that role with the same attachment', async()=>{
  const {context,$} = setup();
  const payload = {text:'Varias oportunidades',file_name:'anuncio.png',file_data:'original-image',model:'test'};
  context.handleVacancyResponse({selection_required:true,positions:['Analista contable','Community manager']},payload);
  assert.equal(context.rendered,undefined);
  assert.equal(context.state.analysis,null);
  assert.equal($('#vacancy-choice').hidden,false);
  assert.equal($('#vacancy-choice-options').children.length,2);
  await $('#vacancy-choice-options').children[1].listeners.click();
  assert.equal(context.payload.selected_position,'Community manager');
  assert.equal(context.payload.file_data,'original-image');
  assert.equal(context.rendered.vacancy.position,'Community manager');
  assert.equal($('#vacancy-choice').hidden,true);
});
test('failed analysis keeps role choices available for retry', async()=>{
  const {context,$} = setup();
  context.requestJson=async()=>{throw new Error('Error temporal');};
  context.handleVacancyResponse({selection_required:true,positions:['A','B']},{text:'Anuncio'});
  const button=$('#vacancy-choice-options').children[0];
  await button.listeners.click();
  assert.equal(context.error,'Error temporal');
  assert.equal(button.disabled,false);
  assert.equal($('#vacancy-choice').hidden,false);
});
test('editing the announcement discards stale selection responses',()=>{
  const {context,$} = setup();
  context.state.vacancyRevision=1;
  context.handleVacancyResponse({selection_required:true,positions:['A','B']},{text:'Anuncio anterior'},0);
  assert.equal($('#vacancy-choice').hidden,true);
  assert.equal(context.rendered,undefined);
});

test('saved contact overrides model guesses before creating and sending the CV',()=>{
 const {context}=setup();
 context.jobTextInput={value:'Vacante con contacto'};
 context.state.employmentContact={text:'Vacante con contacto',email:'recruiter@example.invalid',whatsapp:'+18095550123'};
 context.handleVacancyResponse({analysis:{vacancy:{position:'Cajero',application_emails:['wrong@example.invalid'],application_whatsapp:[]}},model:'test'},{text:'Vacante con contacto'});
 assert.equal(context.state.analysis.vacancy.application_emails[0],'recruiter@example.invalid');
 assert.equal(context.state.analysis.vacancy.application_whatsapp[0],'+18095550123');
 assert.equal(context.rendered.vacancy.application_emails[0],'recruiter@example.invalid');
});

test('a contact from another announcement never overrides its recipients',()=>{
 const {context}=setup();context.jobTextInput={value:'Otra vacante'};
 context.state.employmentContact={text:'Vacante anterior',email:'old@example.invalid',whatsapp:'+18095550123'};
 context.handleVacancyResponse({analysis:{vacancy:{position:'Chef',application_emails:['chef@example.invalid']}},model:'test'},{text:'Otra vacante'});
 assert.equal(context.state.analysis.vacancy.application_emails[0],'chef@example.invalid');
 assert.equal(context.state.analysis.vacancy.application_whatsapp,undefined);
});
