const {test}=require('node:test');
const assert=require('node:assert/strict'), fs=require('node:fs'), vm=require('node:vm');
const source=fs.readFileSync('static/app.js','utf8');
const code=source.slice(source.indexOf('async function processFetch('),source.indexOf('function authenticatedHeaders('));
test('background export preserves reviewed PDF identity and digest in reconstructed response',async()=>{
  const result={download_url:'/api/background/jobs/example/file',fileName:'CV.pdf',driveUrl:'https://drive.google.com/file/d/test/view',artifactId:'a'.repeat(32),pdfSha256:'b'.repeat(64)};
  const context={state:{user:{uid:'alice',getIdToken:async()=> 'fixture'},authEpoch:1},Response,
    authenticatedHeaders:()=>({}),window:{cvBackground:{enabled:()=>true,handles:()=>true,run:async()=>result}},
    fetch:async()=>new Response('pdf-bytes',{headers:{'Content-Type':'application/pdf'}})};
  vm.runInNewContext(code,context);
  const response=await context.processFetch('/api/export/pdf',{method:'POST',body:'{}',headers:{}});
  assert.equal(response.headers.get('X-CV-Artifact-ID'),result.artifactId);
  assert.equal(response.headers.get('X-CV-PDF-SHA256'),result.pdfSha256);
  assert.equal(await response.text(),'pdf-bytes');
});
test('background Gmail failure retains safe PDF result and HTTP failure instead of success',async()=>{
  const entry={status:'failed',cv_url:'https://drive.google.com/file/d/test/view'};
  const context={state:{user:{uid:'alice'},authEpoch:1},Response,
    window:{cvBackground:{enabled:()=>true,handles:()=>true,run:async()=>{throw Object.assign(new Error('Tu CV está disponible.'),{applicationEntry:entry,httpStatus:403});}}}};
  vm.runInNewContext(code,context);
  const response=await context.processFetch('/api/gmail/send',{method:'POST',body:'{}',headers:{}});
  assert.equal(response.status,403);
  assert.equal((await response.json()).entry.cv_url,entry.cv_url);
});
