// Read-only loopback monitor. No credentials, external packages or production writes.
const http = require('node:http');
const fs = require('node:fs');
const path = require('node:path');
const PAGE = path.join(__dirname, 'connection-monitor.html');
const TARGETS = Object.freeze({hosting:'https://cvalamedida.web.app/',api:'https://cvalamedida.web.app/api/health'});
async function probe(id, fetcher = fetch) {
  const started = Date.now();
  try {
    const response = await fetcher(TARGETS[id], {signal:AbortSignal.timeout(12000),redirect:'error'});
    let valid = response.ok;
    if (id === 'api' && valid) {
      const body = await response.json();
      valid = body.ok === true && body.auth_required === true;
    } else if (valid) {
      valid = (response.headers.get('content-type') || '').includes('text/html');
      await response.body?.cancel();
    }
    return {id,state:valid?'ok':'error',detail:valid?'Respuesta HTTP válida; alcance limitado a este recurso.':`Respuesta HTTP ${response.status} o contrato inesperado.`,checkedAt:new Date().toISOString(),ms:Date.now()-started};
  } catch (_) {
    return {id,state:'unknown',detail:'No se pudo comprobar desde este equipo: conexión, TLS o tiempo de espera. No demuestra una caída global.',checkedAt:new Date().toISOString(),ms:Date.now()-started};
  }
}
function createMonitor(fetcher = fetch) {
  let cached, pending;
  return async () => {
    if (cached && Date.now()-cached.time < 60000) return cached.value;
    if (!pending) pending = Promise.all(Object.keys(TARGETS).map(id=>probe(id,fetcher))).then(checks=>{
      const value={at:new Date().toISOString(),intervalSeconds:60,checks};
      cached={time:Date.now(),value}; return value;
    }).finally(()=>{pending=undefined;});
    return pending;
  };
}
function createServer(fetcher = fetch) {
  const snapshot = createMonitor(fetcher);
  return http.createServer(async (req,res)=>{
    const expected=`127.0.0.1:${req.socket.localPort}`;
    if(req.headers.host!==expected || (req.headers.origin && req.headers.origin!==`http://${expected}`) || req.headers['sec-fetch-site']==='cross-site') {
      res.writeHead(403);res.end();return;
    }
    res.setHeader('Cache-Control','no-store');res.setHeader('X-Content-Type-Options','nosniff');
    res.setHeader('Content-Security-Policy',"default-src 'none'; script-src 'unsafe-inline'; style-src 'unsafe-inline'; connect-src 'self'; base-uri 'none'; frame-ancestors 'none'");
    if(req.method!=='GET'){res.writeHead(405);res.end();return;}
    if(req.url==='/status'){
      res.setHeader('Content-Type','application/json; charset=utf-8');res.end(JSON.stringify(await snapshot()));
    }else if(req.url==='/'){
      res.setHeader('Content-Type','text/html; charset=utf-8');res.end(fs.readFileSync(PAGE));
    }else{res.writeHead(404);res.end();}
  });
}
if(require.main===module) createServer().listen(8765,'127.0.0.1',()=>console.log('Diagrama: http://127.0.0.1:8765 — lectura solamente; cierre el proceso para detenerlo.'));
module.exports={probe,createMonitor,createServer};
