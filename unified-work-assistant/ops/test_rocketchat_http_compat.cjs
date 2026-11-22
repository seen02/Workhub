const fs = require('node:fs');
const vm = require('node:vm');
const assert = require('node:assert/strict');
const { randomFillSync } = require('node:crypto');
const source = fs.readFileSync(process.argv[2], 'utf8');
function run(crypto, protocol='http:', hostname='rocketchat.workhub.test') {
  vm.runInNewContext(source, {crypto, location:{protocol, hostname}, Uint8Array});
  return crypto;
}
const c = run({getRandomValues: a => randomFillSync(a)});
const ids = new Set();
for (let i=0; i<10000; i++) {
  const id = c.randomUUID();
  assert.match(id, /^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/);
  assert(!ids.has(id)); ids.add(id);
}
const native = () => 'native';
assert.equal(run({randomUUID:native}).randomUUID, native);
assert.equal(run({}, 'https:').randomUUID, undefined);
assert.equal(run({}, 'http:', 'other.test').randomUUID, undefined);
assert.equal(run({}).randomUUID, undefined);
console.log('PASS: 10000 UUID v4 values, native preservation, host/TLS scope, no weak fallback');
