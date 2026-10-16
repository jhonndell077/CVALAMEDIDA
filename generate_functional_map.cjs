/* Static discovery only: parse HTML/JS without executing application scripts. */
const fs=require('node:fs'),path=require('node:path'),crypto=require('node:crypto');
const root=__dirname;
const {parseHTML}=require(path.join(root,'tests/node_modules/linkedom'));
function parser(){
 const locations=[path.join(root,'tests'),...require('node:module').globalPaths];
 if(process.env.APPDATA)locations.push(path.join(process.env.APPDATA,'npm/node_modules/firebase-tools'));
 for(const dir of (process.env.PATH||'').split(path.delimiter))locations.push(path.join(dir,'node_modules/firebase-tools'));
 try{return require(require.resolve('acorn',{paths:locations}));}catch(_){throw new Error('El analizador Acorn de Firebase CLI no está disponible. No se publicará un mapa incompleto.');}
}
const digest=value=>crypto.createHash('sha256').update(value).digest('hex');
function files(dir){return fs.existsSync(dir)?fs.readdirSync(dir,{withFileTypes:true}).flatMap(entry=>entry.isDirectory()?(['node_modules','__pycache__'].includes(entry.name)?[]:files(path.join(dir,entry.name))):[path.join(dir,entry.name)]):[];}
function relative(file){return path.relative(root,file).replaceAll('\\','/');}
function sourceHash(){
 const sources=[...files(path.join(root,'static')).filter(f=>/\.(html|js|css)$/.test(f)),
  ...fs.readdirSync(root).filter(f=>f.endsWith('.py')||f==='generate_functional_map.cjs').map(f=>path.join(root,f)),
  ...files(path.join(root,'tests')).filter(f=>/\.(py|js|cjs|json)$/.test(f)),
  ...files(path.join(root,'scripts')).filter(f=>/\.(py|js|cjs)$/.test(f)),path.join(root,'firebase.json')];
 return digest(sources.sort().map(file=>relative(file)+'\0'+fs.readFileSync(file,'utf8').replace(/<meta name="cv-build" content="[^"]*">/g,'<meta name="cv-build">')).join('\0'));
}
function walk(node,visit){if(!node||typeof node!=='object')return;if(node.type)visit(node);for(const [key,value] of Object.entries(node)){if(['loc','start','end','raw'].includes(key))continue;if(Array.isArray(value))value.forEach(child=>walk(child,visit));else if(value&&typeof value==='object')walk(value,visit);}}
function name(node){return node?.type==='Identifier'?node.name:node?.type==='MemberExpression'?name(node.object)+'.'+(node.property.name||node.property.value||'?'):'';}
function text(node){if(node?.type==='Literal'&&typeof node.value==='string')return node.value;if(node?.type==='TemplateLiteral')return node.quasis.map(q=>q.value.cooked).join(':param');return null;}
function safeTarget(value){if(!value)return null;try{if(/^https?:/.test(value))return new URL(value).origin;return value.split(/[?#]/)[0].slice(0,220);}catch(_){return null;}}
function semantic(node){return digest(JSON.stringify(node,(key,value)=>['loc','start','end','raw'].includes(key)?undefined:value));}
function keyOf(element){
 if(element.id)return '#'+element.id;
 const parts=[];let item=element;
 while(item?.tagName){if(item.id){parts.unshift('#'+item.id);break;}const siblings=[...(item.parentElement?.children||[])].filter(x=>x.tagName===item.tagName);parts.unshift(item.tagName.toLowerCase()+':nth-of-type('+(siblings.indexOf(item)+1)+')');item=item.parentElement;}
 return parts.join('>');
}
function diff(previous,current){
 const before=new Map((previous?.controls||[]).map(item=>[item.key,item])),after=new Map(current.controls.map(item=>[item.key,item]));
 const brief=item=>({key:item.key,label:item.label,page:item.page,group:item.group,fingerprint:item.fingerprint});
 return {added:[...after.values()].filter(item=>!before.has(item.key)).map(brief),removed:[...before.values()].filter(item=>!after.has(item.key)).map(brief),changed:[...after.values()].filter(item=>before.has(item.key)&&before.get(item.key).fingerprint!==item.fingerprint).map(brief)};
}
function discover(){
 const acorn=parser(),scripts=new Map(),warnings=[];
 const testSources=files(path.join(root,'tests')).filter(f=>/\.test\.(js|cjs)$|test_.*\.py$/.test(f)).map(file=>fs.readFileSync(file,'utf8'));
 function script(file){
  if(scripts.has(file))return scripts.get(file);
  const source=fs.readFileSync(file,'utf8');let ast;
  try{ast=acorn.parse(source,{ecmaVersion:'latest',sourceType:'script',locations:true});}catch(_){ast=acorn.parse(source,{ecmaVersion:'latest',sourceType:'module',locations:true});}
  const aliases=new Map(),functions=new Map(),bindings=[],guards=[];
  function selector(node,depth=0){
   if(depth>6)return null;if(node?.type==='Identifier')return selector(aliases.get(node.name),depth+1);
   if(node?.type!=='CallExpression')return null;const method=name(node.callee),arg=text(node.arguments[0]);
   if(!arg)return null;if(method.endsWith('.getElementById'))return '#'+arg;
   if(method==='\u0024'||method==='\u0024\u0024'||method.endsWith('.querySelector')||method.endsWith('.querySelectorAll'))return arg;
   return null;
  }
  function register(id,node){if(!id)return;const list=functions.get(id)||[];list.push(node);functions.set(id,list);}
  walk(ast,node=>{
   if(node.type==='VariableDeclarator'&&node.id.type==='Identifier'){aliases.set(node.id.name,node.init);if(/FunctionExpression|ArrowFunctionExpression/.test(node.init?.type||''))register(node.id.name,node.init);}
   if(node.type==='FunctionDeclaration')register(node.id?.name,node);
   if(node.type==='Property'&&/FunctionExpression|ArrowFunctionExpression/.test(node.value?.type||''))register(node.key.name||node.key.value,node.value);
  });
  walk(ast,node=>{
   if(node.type==='CallExpression'&&name(node.callee).endsWith('.addEventListener')){
    const event=text(node.arguments[0]),target=selector(node.callee.object),handler=node.arguments[1];
    if(event&&handler)bindings.push({event,target,handler,line:node.loc.start.line,source:relative(file),confidence:target?'selector estático':'destino dinámico/global'});
   }
   if(node.type==='AssignmentExpression'&&node.left.type==='MemberExpression'&&['disabled','hidden','inert'].includes(node.left.property.name))guards.push({selector:selector(node.left.object),property:node.left.property.name,line:node.loc.start.line,source:relative(file)});
  });
  const result={source,functions,bindings,guards};scripts.set(file,result);return result;
 }
 const controls=[],pages=[],loadingEvents=new Set();
 for(const file of files(path.join(root,'static')).filter(f=>f.endsWith('.html')&&!path.basename(f).startsWith('admin-')&&!relative(f).includes('/vendor/'))){
  const page=relative(file).slice(7),url=page==='index.html'?'/':'/'+page;
  const {document}=parseHTML(fs.readFileSync(file,'utf8'));
  const used=[...document.querySelectorAll('script[src]')].map(el=>el.getAttribute('src')).filter(src=>src.startsWith('/')&&!src.startsWith('/__/')).map(src=>path.join(root,'static',src.slice(1))).filter(f=>fs.existsSync(f)&&f.endsWith('.js')&&!f.includes(path.sep+'vendor'+path.sep));
  const modules=used.map(script),elements=[...document.querySelectorAll('button,a,input,select,textarea,summary')];
  const ids=new Set();
  function action(binding){
   const endpoints=new Set(),destinations=new Set(),loading=new Set(),visited=new Set(),dependencies=new Set();let unresolved=0;
   function scan(node,depth=0){
    if(!node||depth>6||visited.has(node))return;visited.add(node);dependencies.add(semantic(node));
    if(node.type==='Identifier'){
     const candidates=modules.flatMap(m=>m.functions.get(node.name)||[]);
     if(candidates.length===1)scan(candidates[0],depth+1);else unresolved++;return;
    }
    walk(node,child=>{
     if(child.type==='CallExpression'){
      const method=name(child.callee),arg=text(child.arguments[0]);
      if(arg?.startsWith('/api/'))endpoints.add(safeTarget(arg));
      if(['window.open','location.assign','location.replace','window.location.assign','window.location.replace'].includes(method)){const target=safeTarget(arg);if(target)destinations.add(target);}
      if(method==='emit'&&arg?.startsWith('cv-loading-'))loadingEvents.add(arg);
      if(method.includes('cvLoading')||method.toLowerCase().includes('loading'))loading.add(method);
      const called=child.callee.type==='Identifier'?child.callee.name:child.callee.property?.name;
      const candidates=modules.flatMap(m=>m.functions.get(called)||[]);
      if(candidates.length===1)scan(candidates[0],depth+1);
     }
     if(child.type==='AssignmentExpression'&&name(child.left).includes('location')){const target=safeTarget(text(child.right));if(target)destinations.add(target);}
    });
   }
   scan(binding.handler);
   return {event:binding.event,source:binding.source,line:binding.line,confidence:binding.confidence,
    fingerprint:digest([...dependencies].sort().join('|')),endpoints:[...endpoints].filter(Boolean).sort(),destinations:[...destinations].sort(),loading:[...loading].sort(),unresolved};
  }
  for(const element of elements){
   const selector=keyOf(element),key=url+'::'+selector;
   if(ids.has(selector))warnings.push('Selector duplicado: '+key);ids.add(selector);
   const handlers=[];
   for(const module of modules)for(const binding of module.bindings){
    if(!binding.target)continue;let matches=[];try{matches=[...document.querySelectorAll(binding.target)];}catch(_){continue;}
    if(matches.some(match=>match===element||(binding.event==='submit'&&match.contains(element)&&element.getAttribute('type')==='submit'))){handlers.push(action(binding));}
   }
   const container=element.closest('dialog,section,form,header,nav,footer,main');
   const label=(element.getAttribute('aria-label')||element.getAttribute('title')||(element.tagName==='INPUT'?element.getAttribute('type'):element.textContent)||element.id||element.tagName).replace(/\s+/g,' ').trim().slice(0,90);
   const item={key,page:url,selector,id:element.id||null,tag:element.tagName.toLowerCase(),label,
    group:container?.id||container?.tagName?.toLowerCase()||'general',
    initialDisabled:element.hasAttribute('disabled'),initialHidden:!!element.closest('[hidden]'),
    href:safeTarget(element.getAttribute('href')),handlers,
    guards:modules.flatMap(m=>m.guards).filter(g=>g.selector===selector),
    relatedTestCount:element.id?testSources.filter(source=>source.includes(element.id)).length:0};
   item.fingerprint=digest(JSON.stringify({...item,key:undefined,handlers:handlers.map(({line,...rest})=>rest),guards:item.guards.map(({line,...rest})=>rest)}));controls.push(item);
  }
  pages.push({path:url,label:document.querySelector('title')?.textContent?.trim()||url,controls:elements.length,scripts:used.map(relative)});
 }
 const dynamicHandlers=[...scripts.values()].flatMap(m=>m.bindings).filter(b=>!b.target).map(({handler,...rest})=>rest);
 return {sourceHash:sourceHash(),pages,controls,loadingEvents:[...loadingEvents].sort(),dynamicHandlers,warnings,parser:'acorn '+acorn.version};
}
function compact(snapshot){return {buildId:snapshot.buildId||null,sourceHash:snapshot.sourceHash,controls:snapshot.controls.map(({key,label,page,group,fingerprint})=>({key,label,page,group,fingerprint}))};}
function build(previous=null,evidence=null,buildId=null){
 const current={...discover(),buildId};const same=previous?.current?.sourceHash===current.sourceHash;
 const baseline=previous?.baseline||compact(current);
 const prior=same?(previous.previous||compact(current)):(previous?.current?compact(previous.current):compact(current));
 return {schema:1,generatedAt:new Date().toISOString(),baseline,previous:prior,current,
  changesSincePrevious:diff(prior,current),changesSinceBaseline:diff(baseline,current),
  tests:evidence?.sourceHash===current.sourceHash?evidence:{passed:null,reason:'No hay resultados de pruebas vinculados a este código.'}};
}
module.exports={discover,build,diff,sourceHash,keyOf,safeTarget};
if(require.main===module){
 try{
  const args=process.argv.slice(2);
  if(args[0]==='--hash'){console.log(sourceHash());}
  else if(args[0]==='--build'){
   const input=JSON.parse(fs.readFileSync(args[1],'utf8'));
   fs.writeFileSync(args[2],JSON.stringify(build(input.previous,input.evidence,input.buildId),null,2)+'\n');
  }else console.log(JSON.stringify(discover()));
 }catch(_){console.error('No se pudo generar el mapa funcional. Revisa sintaxis, dependencias locales y datos de versión.');process.exitCode=1;}
}
