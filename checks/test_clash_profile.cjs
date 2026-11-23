"use strict";
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");

const file = path.join(__dirname, "../claude-native/network/clash-verge.js");
const source = fs.readFileSync(file, "utf8");
const node = "Fixed VPS";
const base = {
  proxies: [{name: node, type: "socks5", server: "127.0.0.1", port: 10080}],
  mode: "rule", tun: {enable: true, "auto-route": true},
  listeners: [{name: "local", type: "http", listen: "127.0.0.1", port: 17080}],
  rules: ["DOMAIN,local.test,DIRECT", "MATCH,DIRECT"],
  dns: {enable: true, nameserver: ["127.0.0.1"], "nameserver-policy": {"+.office.test": "system"}}
};

function apply(config, coverOthers = false) {
  let script = source.replace('"CLAUDE_FIXED_NODE"', JSON.stringify(node));
  if (coverOthers) script = script.replace("coverOtherClients = false", "coverOtherClients = true");
  return JSON.parse(JSON.stringify(vm.runInNewContext(script + "\nmain(config)", {config})));
}
const copy = object => JSON.parse(JSON.stringify(object));
const listener = {name: "claude-private", type: "http", listen: "127.0.0.1", port: 17897, proxy: node};
const only = apply(copy(base));
assert.deepEqual(only, {...base, listeners: [...base.listeners, listener]});
assert.deepEqual(apply(copy(only)), only);

const covered = apply(copy(base), true);
const domains = ["anthropic.com", "claude.ai", "claude.com", "claudeusercontent.com"];
assert.deepEqual(covered.rules, [...domains.map(domain => "DOMAIN-SUFFIX," + domain + "," + node), ...base.rules]);
assert.deepEqual(covered.dns.nameserver, base.dns.nameserver);
assert.equal(covered.dns["nameserver-policy"]["+.office.test"], "system");
for (const domain of domains) {
  assert.deepEqual(covered.dns["nameserver-policy"]["+." + domain],
    ["https://1.1.1.1/dns-query#Fixed%20VPS&ecs=0.0.0.0/0&ecs-override=true"]);
}
assert.deepEqual(covered.tun, base.tun);
assert.equal(covered.mode, base.mode);
assert.deepEqual(apply(copy(covered), true), covered);

for (const conflict of [{...listener, name: "someone-else"}, {...listener, port: 17081}, {...listener, proxy: "DIRECT"}]) {
  assert.throws(() => apply({...copy(base), listeners: [conflict]}), /already assigned/);
}
assert.throws(() => apply({...copy(base), proxies: []}), /concrete Claude node/);
console.log("Clash extension passed listener, optional rules, DNS preservation, repeat application and conflict checks.");
