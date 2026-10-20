const {test}=require('node:test'),assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm');
const source=fs.readFileSync('static/admin-architecture.js','utf8');
const context={};vm.runInNewContext(source.slice(source.indexOf('function connectionRoute('),source.indexOf('function draw(kind)')),context);
const pointNumbers=path=>path.match(/-?\d+(?:\.\d+)?/g).map(Number);
test('connections attach to actual vertical card boundaries including wrapped labels',()=>{
 for(const height of [65,104,148]){const p=pointNumbers(context.connectionRoute({x:40,y:30,width:230,height},{x:310,y:220,width:230,height:84}));assert.deepEqual(p.slice(0,2),[155,30+height]);assert.deepEqual(p.slice(-2),[425,220]);}
});
test('same row uses facing sides rather than cutting through cards',()=>{
 const a={x:40,y:30,width:230,height:104},b={x:310,y:30,width:230,height:104};
 assert.deepEqual(pointNumbers(context.connectionRoute(a,b)).slice(0,2),[270,82]);assert.deepEqual(pointNumbers(context.connectionRoute(a,b)).slice(-2),[310,82]);
 assert.deepEqual(pointNumbers(context.connectionRoute(b,a)).slice(-2),[270,82]);
});
test('upstream connections attach to top of source and bottom of target',()=>{
 const p=pointNumbers(context.connectionRoute({x:40,y:220,width:230,height:65},{x:310,y:30,width:230,height:84}));assert.deepEqual(p.slice(0,2),[155,220]);assert.deepEqual(p.slice(-2),[425,114]);
});
