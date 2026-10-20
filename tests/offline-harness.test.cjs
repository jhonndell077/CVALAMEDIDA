const {test}=require('node:test'),assert=require('node:assert/strict');
test('release harness denies transports before any socket or provider connection',async()=>{
 require('../scripts/offline_node.cjs');
 for(const [name,method,args] of [['node:http','get',['http://example.invalid']],['node:https','request',['https://example.invalid']],['node:net','connect',[443]],['node:tls','connect',[443]],['node:dgram','createSocket',['udp4']],['node:http2','connect',['https://example.invalid']]]) {
  assert.throws(()=>require(name)[method](...args),{code:'RELEASE_TEST_NETWORK_DISABLED'});
 }
 await assert.rejects(globalThis.fetch('https://example.invalid'),{code:'RELEASE_TEST_NETWORK_DISABLED'});
 assert.throws(()=>require('node:dns').lookup('example.invalid',()=>{}),{code:'RELEASE_TEST_NETWORK_DISABLED'});
 await assert.rejects(require('node:dns').promises.resolve4('example.invalid'),{code:'RELEASE_TEST_NETWORK_DISABLED'});
});
