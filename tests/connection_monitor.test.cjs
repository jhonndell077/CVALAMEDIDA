const {test}=require('node:test');
const assert=require('node:assert/strict');
const {probe,createMonitor,createServer}=require('../scripts/connection_monitor.cjs');
test('API configuration cannot pass without enforced authentication',async()=>{
 const result=await probe('api',async()=>new Response(JSON.stringify({ok:true,auth_required:false})));
 assert.equal(result.state,'error');
});
test('HTTP denial is visible while network uncertainty is not a global outage',async()=>{
 assert.equal((await probe('api',async()=>new Response('',{status:503}))).state,'error');
 const result=await probe('api',async()=>{throw new Error('private token must never appear');});
 assert.equal(result.state,'unknown');assert.ok(!JSON.stringify(result).includes('private token'));
});
test('concurrent viewers share one cached read per resource',async()=>{
 let calls=0;const monitor=createMonitor(async(url)=>{calls++;return url.endsWith('/health')?new Response(JSON.stringify({ok:true,auth_required:true})):new Response('html',{headers:{'content-type':'text/html'}});});
 const results=await Promise.all([monitor(),monitor(),monitor()]);await monitor();
 assert.equal(calls,2);assert.ok(results.every(r=>r.checks.every(c=>c.state==='ok')));
});
test('loopback server rejects hostile origins and methods without probing',async()=>{
 let calls=0;const server=createServer(async()=>{calls++;throw new Error();});
 const handler=server.listeners('request')[0];
 async function request(url,method='GET',extra={}){
  const headers=new Map();
  const res={status:200,setHeader(k,v){headers.set(k.toLowerCase(),v);},writeHead(status){this.status=status;},end(){},headers};
  await handler({url,method,headers:{host:'127.0.0.1:8765',...extra},socket:{localPort:8765}},res);
  return res;
 }
  assert.equal((await request('/status','GET',{origin:'https://other.invalid'})).status,403);
  assert.equal((await request('/status','POST')).status,405);
  assert.equal(calls,0);
  const page=await request('/');assert.equal(page.status,200);
  assert.ok(page.headers.get('content-security-policy').includes("frame-ancestors 'none'"));
});
