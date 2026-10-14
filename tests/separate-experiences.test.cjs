const {test}=require('node:test');
const assert=require('node:assert/strict');
const fs=require('node:fs'),vm=require('node:vm');

test('preview renders a distinct block for each job with the same title',()=>{
  const source=fs.readFileSync('static/app.js','utf8');
  const right={children:[]};
  const draft={experiences:[
    {title:'Camarero',employer:'Forno Bravo',selected_responsibilities:['Preparación de bebidas.']},
    {title:'Camarero',employer:'Farah',selected_responsibilities:['Recepción de comensales.']},
  ]};
  const addText=(parent,tag,text,css)=>{const node={tag,text,css,children:[]};parent.children.push(node);return node};
  const context=vm.createContext({draft,right,addText,addPreviewSection:(parent,title)=>addText(parent,'section',title)});
  vm.runInContext(source.slice(source.indexOf('  const work = draft.experiences.length'),source.indexOf('  if (!draft.project_focus) renderProjects();')),context);
  const jobs=right.children[0].children;
  assert.equal(jobs.length,2);
  assert.equal(jobs[0].children[0].text,'Camarero: Forno Bravo');
  assert.equal(jobs[1].children[0].text,'Camarero: Farah');
  assert.equal(jobs[0].children[1].text,'•  Preparación de bebidas.');
  assert.equal(jobs[1].children[1].text,'•  Recepción de comensales.');
});
