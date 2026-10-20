/* Release fixtures must never connect to production, DNS or localhost. */
'use strict';
const deny = () => { throw Object.assign(new Error('RELEASE_TEST_NETWORK_DISABLED'), {code:'RELEASE_TEST_NETWORK_DISABLED'}); };
const net = require('node:net'), tls = require('node:tls'), dgram = require('node:dgram');
net.connect = net.createConnection = net.Socket.prototype.connect = deny;
tls.connect = deny;
dgram.createSocket = deny;
const dns = require('node:dns');
for (const target of [dns, dns.Resolver.prototype]) {
  for (const name of Object.getOwnPropertyNames(target)) if (/^(lookup|resolve)/.test(name) && typeof target[name] === 'function') target[name] = deny;
}
for (const name of Object.keys(dns.promises)) if (/^(lookup|resolve)/.test(name)) dns.promises[name] = async () => deny();
for (const name of Object.getOwnPropertyNames(dns.promises.Resolver.prototype)) if (/^(lookup|resolve)/.test(name)) dns.promises.Resolver.prototype[name] = async () => deny();
for (const name of ['node:http','node:https','node:http2']) {
  const module = require(name);
  for (const method of ['request','get','connect']) if (typeof module[method] === 'function') module[method] = deny;
}
globalThis.fetch = async () => deny();
