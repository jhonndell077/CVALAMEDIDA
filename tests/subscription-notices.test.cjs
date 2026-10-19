const {test}=require('node:test'),assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm');
const {parseHTML}=require('linkedom');
const fixture={plan:{name:'pro'},assignmentVersion:'v1',planCatalog:[{id:'pro',label:'Profesional',daily:20,monthly:100,priceMinor:null,benefits:['Más operaciones']}],payment:{collection:'manual',status:'unverified'}};
function setup(fetcher=async()=>new Response(JSON.stringify(fixture)),blocked=false){const {window}=parseHTML('<html><body></body></html>');const data=new Map();vm.runInNewContext(fs.readFileSync('static/subscription-notices.js','utf8'),{window,document:window.document,fetch:fetcher,localStorage:{getItem(k){if(blocked)throw Error();return data.get(k)},setItem(k,v){if(blocked)throw Error();data.set(k,v)}},Set});return {api:window.cvSubscription,d:window.document,data,user:(uid='u1')=>({uid,displayName:'Persona',getIdToken:async()=>uid})};}
test('manual assigned plan welcome makes no paid purchase claim and deduplicates',async()=>{const ui=setup();await ui.api.initialize(ui.user());assert.match(ui.d.body.textContent,/tienes asignado el plan Profesional/);assert.doesNotMatch(ui.d.body.textContent,/adquiriste|pagaste|compraste/);ui.d.querySelector('button').click();await ui.api.initialize(ui.user());assert.equal(ui.d.querySelector('aside'),null);assert.ok([...ui.data.keys()].every(k=>!k.includes('Persona')))});
test('only period quota exhaustion opens quota notice; plans use safe text and nullable price',async()=>{const ui=setup(async()=>new Response(JSON.stringify({...fixture,plan:{id:'basic'}})));await ui.api.initialize(ui.user());ui.d.querySelector('.subscription-dismiss').click();await ui.api.observe({status:429},{code:'concurrency_limit'});assert.equal(ui.d.querySelector('aside'),null);await ui.api.observe({status:429},{code:'period_quota_exceeded',period:'daily'});assert.match(ui.d.body.textContent,/límite diario/);ui.d.querySelector('aside button').click();assert.match(ui.d.querySelector('dialog').textContent,/Precio por confirmar/);assert.match(ui.d.querySelector('dialog').textContent,/Más operaciones para adaptar tus postulaciones/);ui.d.querySelectorAll('dialog button')[0].click();assert.equal(ui.d.querySelector('dialog'),null)});
test('logout during token await cancels request and removes views',async()=>{let finish,calls=0;const ui=setup(async()=>{calls++;return new Response(JSON.stringify(fixture))});const pending=ui.api.initialize({uid:'a',getIdToken:()=>new Promise(r=>finish=r)});await ui.api.initialize(null);finish('oldtoken');await pending;assert.equal(calls,0);assert.equal(ui.d.body.children.length,0)});
test('stale response cannot restore previous account plan',async()=>{let finish;const ui=setup(()=>new Promise(r=>finish=r));const pending=ui.api.initialize(ui.user());await new Promise(r=>setImmediate(r));await ui.api.initialize(null);finish(new Response(JSON.stringify(fixture)));await pending;assert.equal(ui.d.body.children.length,0)});
test('blocked storage retains in-memory dismiss dedup without breaking app',async()=>{const ui=setup(undefined,true);await ui.api.initialize(ui.user());ui.d.querySelector('button').click();await ui.api.initialize(ui.user());assert.equal(ui.d.querySelector('aside'),null)});
test('catalog labels and benefits cannot inject HTML',async()=>{const ui=setup(async()=>new Response(JSON.stringify({...fixture,planCatalog:[{id:'pro',label:'<img src=x>',benefits:['<script>bad()</script>']}]})));await ui.api.initialize(ui.user());ui.api.openPlans();assert.equal(ui.d.querySelector('img'),null);assert.equal(ui.d.querySelector('script'),null);assert.match(ui.d.body.textContent,/<img src=x>/)});

test('quota refresh failure remains nonblocking and uses basic label',async()=>{const ui=setup(async()=>{throw Error('offline')});await ui.api.initialize(ui.user());await ui.api.observe({status:429},{code:'period_quota_exceeded',period:'monthly'});assert.match(ui.d.body.textContent,/límite mensual de tu plan Básico/)});
test('quota from previous account cannot display after account switch',async()=>{let finish,calls=0;const ui=setup(async()=>{calls++;if(calls===2)return new Promise(r=>finish=r);return new Response(JSON.stringify({...fixture,plan:null,assignmentVersion:null}))});await ui.api.initialize(ui.user());const pending=ui.api.observe({status:429},{code:'period_quota_exceeded',period:'daily'});await new Promise(r=>setImmediate(r));await ui.api.initialize(ui.user('other'));finish(new Response(JSON.stringify(fixture)));await pending;assert.equal(ui.d.querySelector('aside'),null)});

test('backend month period uses monthly text and deduplicates by usage month',async()=>{const ui=setup(async()=>new Response(JSON.stringify({...fixture,plan:null,assignmentVersion:null,usage:{day:'2026-10-17',month:'2026-10'}})));await ui.api.initialize(ui.user());await ui.api.observe({status:429},{code:'period_quota_exceeded',period:'month'});assert.match(ui.d.body.textContent,/límite mensual/);assert.ok([...ui.data.keys()].some(k=>k.endsWith(':monthly:2026-10')));ui.d.querySelector('aside .subscription-dismiss').click();await ui.api.observe({status:429},{code:'period_quota_exceeded',period:'monthly'});assert.equal(ui.d.querySelector('aside'),null)});
test('backend day period uses daily text',async()=>{const ui=setup(async()=>new Response(JSON.stringify({...fixture,plan:null,assignmentVersion:null})));await ui.api.initialize(ui.user());await ui.api.observe({status:429},{code:'period_quota_exceeded',period:'day'});assert.match(ui.d.body.textContent,/límite diario/)});

test('welcome includes safe configured benefits and quota invites more operations',async()=>{const ui=setup(async()=>new Response(JSON.stringify({...fixture,benefits:['<b>Más operaciones</b>']})));await ui.api.initialize(ui.user());assert.match(ui.d.body.textContent,/Disfruta de: <b>Más operaciones<.b>/);assert.equal(ui.d.querySelector('b'),null);await ui.api.observe({status:429},{code:'period_quota_exceeded',period:'month'});assert.match(ui.d.body.textContent,/Consulta los planes para ampliar tus operaciones/)});
test('welcome always includes confirmed CV limits',async()=>{const ui=setup(async()=>new Response(JSON.stringify({...fixture,benefits:[],limits:{daily:25,monthly:250}})));await ui.api.initialize(ui.user());assert.match(ui.d.body.textContent,/25 CV al día y 250 al mes/)});
test('basic welcome shows remaining CVs and updates after a plan change',async()=>{
 let data={plan:null,assignmentVersion:null,limits:{daily:3,monthly:30},usage:{dailyRemaining:3,monthlyRemaining:30}};
 const ui=setup(async()=>new Response(JSON.stringify(data)));
 await ui.api.initialize(ui.user());
 assert.match(ui.d.body.textContent,/3 CV al día y 30 al mes/);
 assert.match(ui.d.body.textContent,/Disponibles: 3 hoy y 30 este mes/);
 ui.d.querySelector('.subscription-dismiss').click();
 data={...data,plan:{name:'pro'},assignmentVersion:'new',limits:{daily:20,monthly:200}};
 await ui.api.refresh();
 assert.match(ui.d.body.textContent,/20 CV al día y 200 al mes/);
});
test('return to an already acknowledged basic plan still notifies the user',async()=>{
 let data={plan:null,assignmentVersion:null,limits:{daily:3,monthly:30}};
 const ui=setup(async()=>new Response(JSON.stringify(data)));
 await ui.api.initialize(ui.user());ui.d.querySelector('.subscription-dismiss').click();
 data={plan:{name:'pro'},assignmentVersion:'pro-v1',limits:{daily:20,monthly:200}};
 await ui.api.refresh();ui.d.querySelector('.subscription-dismiss').click();
 data={plan:null,assignmentVersion:null,limits:{daily:3,monthly:30}};
 await ui.api.refresh();assert.match(ui.d.querySelector('aside').textContent,/3 CV al día y 30 al mes/);
 ui.d.querySelector('.subscription-dismiss').click();
 await ui.api.refresh();assert.equal(ui.d.querySelector('aside'),null);
});
test('token renewal preserves an unread notice and does not acknowledge it',async()=>{
 const ui=setup();await ui.api.initialize(ui.user());
 const notice=ui.d.querySelector('aside');
 await ui.api.initialize(ui.user());
 assert.equal(ui.d.querySelector('aside'),notice);
 assert.equal(ui.data.size,0);
});
