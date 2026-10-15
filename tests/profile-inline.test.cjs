const {test}=require('node:test');
const assert=require('node:assert/strict');
const fs=require('node:fs'),vm=require('node:vm');
const {parseHTML}=require('linkedom');
function setup(){
 const {document,window}=parseHTML('<div id="profile-tree"></div><div id="profile-status"></div><div id="profile-error"></div><button id="save-profile"></button><button id="discard-profile"></button>');
 const sections=['experiences','skills','education','courses','projects','references','not_documented'];
 const profile=Object.fromEntries(sections.map(s=>[s,[]]));profile.candidate={};
 const state={profile,profileDraft:structuredClone(profile),profileEditable:true};
 const source=fs.readFileSync('static/app.js','utf8');
 const ctx=vm.createContext({document,window,state,structuredClone,crypto:require('node:crypto').webcrypto,
  $:s=>document.querySelector(s),addText(parent,tag,text,cls){const el=document.createElement(tag);el.textContent=text??'';el.className=cls||'';parent.append(el);return el;}});
 window.confirm=()=>true;
 vm.runInContext(source.slice(source.indexOf('const profileLabels'),source.indexOf('async function saveProfileChanges()')),ctx);
 return {document,window,state,ctx};
}
for(const section of ['experiences','skills','education','courses','projects','references','not_documented'])test(`add opens editable ${section} draft and delete removes it locally`,()=>{
 const {document,state,ctx}=setup();ctx.renderProfileTree();
 const index=['experiences','skills','education','courses','projects','references','not_documented'].indexOf(section)+1;
 document.querySelectorAll('#profile-tree > details')[index].querySelector('.profile-add').click();
 const panel=document.querySelectorAll('#profile-tree > details')[index];
 assert.equal(panel.hasAttribute('open'),true);
 const entry=panel.querySelector('.profile-entry');
 if(entry.tagName==='DETAILS')assert.equal(entry.hasAttribute('open'),true);
 assert.ok(panel.querySelector('input'));
 assert.doesNotMatch(entry.querySelector('summary')?.textContent||'', /(?:experiencia|habilidad|estudio|curso|proyecto)-/);
 const remove=panel.querySelector('.profile-remove');assert.ok(remove);remove.click();
 assert.equal(state.profileDraft[section].length,0);
 assert.equal(state.profile[section].length,0);
});

test('all eight category cards open a searchable dialog and restore original controls',()=>{
 const {document,window,state,ctx}=setup();
 const html=parseHTML(fs.readFileSync('static/index.html','utf8')).document;
 const dialog=html.querySelector('#profile-category-dialog');document.append(dialog);
 dialog.showModal=()=>dialog.setAttribute('open','');
 dialog.close=()=>{dialog.removeAttribute('open');dialog.dispatchEvent(new window.Event('close'))};
 vm.runInContext(fs.readFileSync('static/profile-dialog.js','utf8'),ctx);
 state.profileDraft.experiences=[{id:'a',title:'Cocinero',employer:'Café Central'},{id:'b',title:'Camarero',employer:'Hotel Norte'}];
 state.profileDraft.candidate={name:'Persona de prueba'};
 ctx.renderProfileTree();
 const keys=['candidate','experiences','skills','education','courses','projects','references','not_documented'];
 for(const key of keys){
  const card=[...document.querySelectorAll('#profile-tree > details')].find(node=>node.dataset.category===key);
  card.querySelector('summary').click();assert.equal(dialog.hasAttribute('open'),true);
  assert.equal(card.children.length,1);
  assert.equal(document.querySelector('#save-profile').parentNode.id,'profile-category-actions');
  if(key==='experiences'){
   const search=document.querySelector('#profile-category-search');search.value='CAFE central';search.dispatchEvent(new window.Event('input'));
   const rows=[...dialog.querySelectorAll('#profile-category-content > .profile-node-body > .profile-entry')];
   assert.equal(rows[0].hidden,false);assert.equal(rows[1].hidden,true);
   search.value='inexistente';search.dispatchEvent(new window.Event('input'));
   assert.equal(document.querySelector('#profile-category-empty').hidden,false);
   dialog.querySelector('.profile-add').click();
   assert.equal(search.value,'');assert.equal(dialog.querySelectorAll('#profile-category-content > .profile-node-body > .profile-entry').length,3);
   const added=[...dialog.querySelectorAll('#profile-category-content > .profile-node-body > .profile-entry')].at(-1);
   assert.equal(added.hasAttribute('open'),true);added.querySelector('.profile-remove').click();
   assert.equal(dialog.querySelectorAll('#profile-category-content > .profile-node-body > .profile-entry').length,2);
  }
  dialog.close();assert.notEqual(document.querySelector('#save-profile').parentNode.id,'profile-category-actions');
  assert.ok(document.querySelector(`[data-category="${key}"]`).children.length>1);
 }
});

