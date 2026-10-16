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
 await new Promise(resolve=>server.listen(0,'127.0.0.1',resolve));
 try{
  const url=`http://127.0.0.1:${server.address().port}`;
  assert.equal((await fetch(url+'/status',{headers:{Origin:'https://other.invalid'}})).status,403);
  assert.equal((await fetch(url+'/status',{method:'POST'})).status,405);
  assert.equal(calls,0);
  const page=await fetch(url);assert.equal(page.status,200);
  assert.ok(page.headers.get('content-security-policy').includes("frame-ancestors 'none'"));
 }finally{await new Promise(resolve=>server.close(resolve));}
});
