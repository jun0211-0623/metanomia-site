'use strict';

const test = require('node:test');
const assert = require('node:assert/strict');
const crypto = require('node:crypto');
const fs = require('node:fs');
const vm = require('node:vm');
const {publishCloudPlan, REPOSITORY} = require('../scripts/cloud-news-connector.js');
const digest = text => crypto.createHash('sha1').update(text).digest('hex');
const BASE = digest('base');
const BASE_TREE = digest('base tree');
const NEXT_TREE = digest('candidate tree');
const NEXT = digest('candidate commit');
const ADVANCED = digest('another commit');
const H = 'a'.repeat(64);
const SLUG = '2026-09-09-crypto-news-1234567890';
const SWISS = '2026-09-08-crypto-news-8c5a7fe969';
const KO_PATH = 'data/crypto-news.json';
const copy = data => JSON.parse(JSON.stringify(data));

function blob(path, content, mode = '100644') {
  const bytes = Buffer.from(content);
  return {path, mode, type: 'blob',
    sha: crypto.createHash('sha1').update(`blob ${bytes.length}\0`).update(bytes).digest('hex'),
    sha256: crypto.createHash('sha256').update(bytes).digest('hex'),
    size: bytes.length, content: bytes.toString('base64')};
}
function rawTree(sha, files) {
  const directories = new Set();
  for (const file of files) {
    const parts = file.path.split('/');
    for (let i = 1; i < parts.length; i++) directories.add(parts.slice(0, i).join('/'));
  }
  return {sha, truncated: false, tree: [
    ...[...directories].map(path => ({path, mode: '040000', type: 'tree', sha: digest(path)})),
    ...files.map(({path, mode, type, sha, size}) => ({path, mode, type, sha, size}))]};
}
function fixture() {
  const korean = {schema_version: '1.0', items: [{slug: SLUG}]};
  const before = [blob(KO_PATH, JSON.stringify(korean)), blob('data/crypto-news.en.json', 'old english'),
    blob('.newsroom/translation-state.json', 'old state'), blob('sitemap.xml', 'old sitemap'),
    blob('README.md', 'keep unrelated bytes'), blob('assets/logo.bin', '\0binary'),
    blob('scripts/check.sh', '#!/bin/sh\n', '100755')];
  const updates = [blob('data/crypto-news.en.json', 'new english'),
    blob('.newsroom/translation-state.json', 'new state'), blob('sitemap.xml', 'new sitemap'),
    blob(`crypto-news-${SLUG}.html`, '<h1>English</h1>'),
    blob(`ko/crypto-news-${SLUG}.html`, '<a>English</a>')];
  const after = new Map(before.map(entry => [entry.path, entry]));
  for (const entry of updates) after.set(entry.path, entry);
  const plan = {schema_version: '1.0', kind: 'metanomia-cloud-news-publish-plan',
    repository: REPOSITORY, branch: 'main', base_sha: BASE, base_tree_sha: BASE_TREE,
    ko_blob_sha: before[0].sha, baseline_hash: H, candidate_tree_sha: NEXT_TREE,
    validation: {snapshot_hashes: {source_snapshot_hash: H, english_snapshot_hash: H, state_snapshot_hash: H},
      validated_repository_hash: H, commands: [
        ['scripts/build-news-pages.py'], ['scripts/codex-news-translation.py', 'verify'],
        ['scripts/publish_crypto_news.py', 'verify-static-pages', '--repository', '.'],
        ['scripts/audit-site.py']].map(command => ({command, stdout_sha256: H}))},
    files: copy(updates), plan_hash: H};
  const f = {plan, korean, before, updates, calls: [], main: BASE,
    baseTree: rawTree(BASE_TREE, before), nextTree: rawTree(NEXT_TREE, [...after.values()]), mainReads: 0};
  const record = (name, args) => f.calls.push({name, args: copy(args)});
  f.api = {
    async getMain() { record('getMain', []); f.mainReads++; return {object: {sha: f.main}}; },
    async getCommit(sha) { record('getCommit', [sha]); return {sha,
      tree: {sha: sha === BASE ? BASE_TREE : NEXT_TREE}, parents: [{sha: sha === BASE ? ADVANCED : BASE}]}; },
    async getTree(sha) { record('getTree', [sha]); return copy(sha === BASE_TREE ? f.baseTree : f.nextTree); },
    async getJson(path, ref) { record('getJson', [path, ref]); assert.equal(path, KO_PATH); assert.equal(ref, BASE); return copy(f.korean); },
    async createBlob(content) { record('createBlob', [content]); const b = Buffer.from(content, 'base64');
      return {sha: crypto.createHash('sha1').update(`blob ${b.length}\0`).update(b).digest('hex')}; },
    async createTree(base, elements) { record('createTree', [base, elements]); return {sha: NEXT_TREE}; },
    async createCommit(tree, parent, message) { record('createCommit', [tree, parent, message]);
      return {sha: NEXT, tree: {sha: tree}, parents: [{sha: parent}]}; },
    async updateRef(sha, force) { record('updateRef', [sha, force]); assert.equal(force, false);
      if (f.main !== BASE) throw new Error('422: not a fast forward'); f.main = sha; return {object: {sha}}; },
    async compare(base, head) { record('compare', [base, head]); return {status: 'ahead', base_commit: {sha: base}, merge_base_commit: {sha: base}}; }
  };
  f.writes = () => f.calls.filter(c => /^(create|update)/.test(c.name));
  return f;
}
async function blocked(f, code) {
  await assert.rejects(publishCloudPlan(f.plan, f.api), err => err.code === code,
    `Expected ${code}`);
  assert.equal(f.calls.filter(c => c.name === 'updateRef').length, 0, 'no ref update after validation failure');
}

test('publishes exact verified additions/modifications atomically and preserves every other leaf', async () => {
  const f = fixture();
  const result = await publishCloudPlan(f.plan, f.api);
  assert.equal(result.status, 'published'); assert.equal(result.head_sha, NEXT);
  assert.equal(result.recovered_response, false);
  assert.equal(f.calls.filter(c => c.name === 'updateRef').length, 1);
  const t = f.calls.find(c => c.name === 'createTree');
  assert.equal(t.args[0], BASE_TREE);
  assert.deepEqual(t.args[1], f.updates.map(({path, mode, type, sha}) => ({path, mode, type, sha})));
  const c = f.calls.find(c => c.name === 'createCommit');
  assert.deepEqual(c.args.slice(0, 2), [NEXT_TREE, BASE]);
  assert.deepEqual(f.calls.find(c => c.name === 'updateRef').args, [NEXT, false]);
});
test('no-op verifies base but performs zero external writes', async () => {
  const f = fixture(); f.plan.files = []; f.plan.candidate_tree_sha = BASE_TREE;
  assert.equal((await publishCloudPlan(f.plan, f.api)).status, 'noop');
  assert.equal(f.writes().length, 0);
});
test('no-op cannot conceal a different candidate tree', async () => {
  const f = fixture(); f.plan.files = []; await blocked(f, 'INVALID_NOOP'); assert.equal(f.calls.length, 0);
});
test('pure JS global export works without Node globals, crypto, network, or filesystem', async () => {
  const context = vm.createContext({});
  vm.runInContext(fs.readFileSync(require.resolve('../scripts/cloud-news-connector.js'), 'utf8'), context);
  assert.equal(typeof context.MetanomiaCloudPublisher.publishCloudPlan, 'function');
  const f = fixture(); f.plan.files = []; f.plan.candidate_tree_sha = BASE_TREE;
  assert.equal((await context.MetanomiaCloudPublisher.publishCloudPlan(f.plan, f.api)).status, 'noop');
});
for (const [field, value] of [['repository', 'another/repo'], ['branch', 'production']]) {
  test(`rejects target change: ${field}`, async () => { const f = fixture(); f.plan[field] = value; await blocked(f, 'WRONG_TARGET'); assert.equal(f.writes().length, 0); });
}
test('rejects stale main before reading or writing Git objects', async () => {
  const f = fixture(); f.main = ADVANCED; await blocked(f, 'STALE_BASE'); assert.equal(f.writes().length, 0);
});
test('rejects ambiguous main response', async () => {
  const f = fixture(); f.api.getMain = async () => ({sha: BASE, object: {sha: ADVANCED}}); await blocked(f, 'INVALID_REF');
});
test('rejects baseline commit tree mismatch', async () => {
  const f = fixture(); f.api.getCommit = async sha => ({sha, tree: {sha: NEXT_TREE}, parents: []}); await blocked(f, 'COMMIT_MISMATCH');
});
test('rejects changed Korean blob', async () => {
  const f = fixture(); f.plan.ko_blob_sha = digest('wrong KO'); await blocked(f, 'KOREAN_CHANGED'); assert.equal(f.writes().length, 0);
});
for (const p of [KO_PATH, 'README.md', `.github/workflows/new.yml`, `crypto-news-${SWISS}.html`, `ko/crypto-news-${SWISS}.html`]) {
  test(`rejects disallowed file or deleted Swiss restoration: ${p}`, async () => {
    const f = fixture(); f.plan.files.push(blob(p, 'unauthorized')); await blocked(f, 'DISALLOWED_PATH'); assert.equal(f.writes().length, 0);
  });
}
test('rejects duplicate manifest slug and unsafe slug', async () => {
  for (const slug of [SLUG, '../evil']) { const f = fixture(); f.korean.items.push({slug}); await blocked(f, 'INVALID_KOREAN_MANIFEST'); }
});
test('rejects duplicate plan paths', async () => {
  const f = fixture(); f.plan.files.push(copy(f.plan.files[0])); await blocked(f, 'DUPLICATE_PATH');
});
for (const p of ['../escape', '/absolute', 'data\\escape', '.git/config', 'C:/escape', 'data//escape']) {
  test(`rejects unsafe plan path ${p}`, async () => { const f = fixture(); f.plan.files[0].path = p; await blocked(f, 'INVALID_PATH'); });
}
for (const [mode, type] of [['120000', 'blob'], ['160000', 'commit'], ['100755', 'blob'], ['040000', 'tree']]) {
  test(`rejects planned mode/type ${mode}/${type}`, async () => {
    const f = fixture(); Object.assign(f.plan.files[0], {mode, type}); await blocked(f, 'UNSAFE_PLAN_ENTRY');
  });
}
test('rejects existing output mode changes', async () => {
  const f = fixture(); f.baseTree.tree.find(e => e.path === f.plan.files[0].path).mode = '100755'; await blocked(f, 'MODE_CHANGE');
});
test('rejects malformed hash, size, base64, padding, and extra fields before writes', async () => {
  for (const [field, value, code] of [['sha', 'x', 'INVALID_HASH'], ['size', 900, 'INVALID_FILE_SIZE'],
    ['content', 'not base64!', 'INVALID_BASE64'], ['content', 'Zh==', 'INVALID_BASE64'], ['content', 'Zm9=', 'INVALID_BASE64']]) {
    const f = fixture(); f.plan.files[0][field] = value; await blocked(f, code); assert.equal(f.writes().length, 0);
  }
  const f = fixture(); f.plan.force = true; await blocked(f, 'INVALID_FIELDS');
});
test('rejects absent validation steps', async () => {
  const f = fixture(); f.plan.validation.commands.pop(); await blocked(f, 'INVALID_VALIDATION');
});
test('rejects changed validation subcommand, extra arguments, and reordered steps', async () => {
  const mutations = [
    f => f.plan.validation.commands[1].command[1] = 'bootstrap',
    f => f.plan.validation.commands[0].command.push('--skip-checks'),
    f => f.plan.validation.commands.reverse()];
  for (const mutate of mutations) { const f = fixture(); mutate(f); await blocked(f, 'INVALID_VALIDATION'); assert.equal(f.writes().length, 0); }
});
test('rejects untruncated=false missing, omitted directory, duplicate and case-colliding baseline paths', async () => {
  const operations = [
    [f => f.baseTree.truncated = true, 'INCOMPLETE_TREE'],
    [f => delete f.baseTree.truncated, 'INCOMPLETE_TREE'],
    [f => f.baseTree.tree = f.baseTree.tree.filter(e => e.path !== 'data'), 'INCOMPLETE_TREE'],
    [f => f.baseTree.tree.push(copy(f.baseTree.tree[0])), 'DUPLICATE_PATH'],
    [f => f.baseTree.tree.push({...f.baseTree.tree[0], path: f.baseTree.tree[0].path.toUpperCase()}), 'DUPLICATE_PATH'],
    [f => f.baseTree.tree.push({path: 'link', sha: digest('link'), mode: '120000', type: 'blob'}), 'UNSAFE_TREE_ENTRY']];
  for (const [mutate, code] of operations) { const f = fixture(); mutate(f); await blocked(f, code); assert.equal(f.writes().length, 0); }
});
test('rejects corrupted base64 bytes when GitHub returns the real mismatching blob SHA', async () => {
  const f = fixture(); const changed = blob(f.plan.files[0].path, 'evil');
  f.plan.files[0].content = changed.content; f.plan.files[0].size = changed.size;
  await blocked(f, 'BLOB_MISMATCH'); assert.equal(f.calls.filter(c => c.name === 'createTree').length, 0);
});
test('rejects mismatching blob response', async () => {
  const f = fixture(); f.api.createBlob = async () => ({sha: ADVANCED}); await blocked(f, 'BLOB_MISMATCH');
});
test('rejects tree SHA mismatch before creating commit', async () => {
  const f = fixture(); f.api.createTree = async () => ({sha: BASE_TREE}); await blocked(f, 'TREE_SHA_MISMATCH');
  assert.equal(f.calls.filter(c => c.name === 'createCommit').length, 0);
});
test('rejects dropped unrelated file, unrelated edit/addition, and Korean mutation in candidate', async () => {
  const operations = [
    f => f.nextTree.tree = f.nextTree.tree.filter(e => e.path !== 'README.md'),
    f => f.nextTree.tree.find(e => e.path === 'README.md').sha = ADVANCED,
    f => f.nextTree.tree.push({path: 'surprise.html', mode: '100644', type: 'blob', sha: ADVANCED}),
    f => f.nextTree.tree.find(e => e.path === KO_PATH).sha = ADVANCED];
  for (const mutate of operations) { const f = fixture(); mutate(f); await blocked(f, 'TREE_DIFF_MISMATCH'); }
});
test('rejects duplicate, truncated, or empty directory candidate tree', async () => {
  for (const [mutate, code] of [
    [f => f.nextTree.truncated = true, 'INCOMPLETE_TREE'],
    [f => f.nextTree.tree.push(copy(f.nextTree.tree[0])), 'DUPLICATE_PATH'],
    [f => f.nextTree.tree.push({path: 'empty', type: 'tree', mode: '040000', sha: ADVANCED}), 'INCOMPLETE_TREE']]) {
    const f = fixture(); mutate(f); await blocked(f, code);
  }
});
test('remote advance after blobs/tree prevents commit creation', async () => {
  const f = fixture(); const original = f.api.createTree;
  f.api.createTree = async (...args) => { const result = await original(...args); f.main = ADVANCED; return result; };
  await blocked(f, 'STALE_BASE'); assert.equal(f.calls.filter(c => c.name === 'createCommit').length, 0);
});
test('rejects wrong parent, merge parent, and commit tree mismatch', async () => {
  for (const response of [
    {sha: NEXT, tree: {sha: NEXT_TREE}, parents: [{sha: ADVANCED}]},
    {sha: NEXT, tree: {sha: NEXT_TREE}, parents: [{sha: BASE}, {sha: ADVANCED}]},
    {sha: NEXT, tree: {sha: BASE_TREE}, parents: [{sha: BASE}]}]) {
    const f = fixture(); f.api.createCommit = async () => response;
    await blocked(f, response.tree.sha === BASE_TREE ? 'COMMIT_MISMATCH' : 'COMMIT_PARENT_MISMATCH');
  }
});
test('native createCommit acknowledgement containing only SHA is verified through getCommit', async () => {
  const f = fixture(); const original = f.api.createCommit;
  f.api.createCommit = async (...args) => { const result = await original(...args); return {sha: result.sha}; };
  assert.equal((await publishCloudPlan(f.plan, f.api)).status, 'published');
  const verified = f.calls.findIndex(c => c.name === 'getCommit' && c.args[0] === NEXT);
  const updated = f.calls.findIndex(c => c.name === 'updateRef');
  assert.ok(verified >= 0 && updated > verified);
});
test('SHA-only createCommit response cannot bypass fetched parent or tree verification', async () => {
  for (const wrong of ['parent', 'tree']) {
    const f = fixture(); const original = f.api.getCommit;
    f.api.createCommit = async () => ({sha: NEXT});
    f.api.getCommit = async sha => {
      const result = await original(sha);
      if (sha === NEXT) {
        if (wrong === 'parent') result.parents = [{sha: ADVANCED}];
        else result.tree.sha = BASE_TREE;
      }
      return result;
    };
    await blocked(f, wrong === 'parent' ? 'COMMIT_PARENT_MISMATCH' : 'COMMIT_MISMATCH');
  }
});
test('ref acknowledgement without SHA uses readback without retry', async () => {
  const f = fixture(); const original = f.api.updateRef;
  f.api.updateRef = async (...args) => { await original(...args); return {}; };
  const result = await publishCloudPlan(f.plan, f.api);
  assert.equal(result.status, 'published'); assert.equal(result.recovered_response, true);
  assert.equal(f.calls.filter(c => c.name === 'updateRef').length, 1);
});
test('remote advance after commit prevents ref update', async () => {
  const f = fixture(); const original = f.api.createCommit;
  f.api.createCommit = async (...args) => { const result = await original(...args); f.main = ADVANCED; return result; };
  await blocked(f, 'STALE_BASE');
});
test('reads back lost response and never retries ref update', async () => {
  const f = fixture(); const original = f.api.updateRef;
  f.api.updateRef = async (...args) => { await original(...args); throw new Error('response lost'); };
  const result = await publishCloudPlan(f.plan, f.api);
  assert.equal(result.status, 'published'); assert.equal(result.recovered_response, true);
  assert.equal(f.calls.filter(c => c.name === 'updateRef').length, 1);
});
test('lost response with unchanged main reports not applied without retry', async () => {
  const f = fixture(); let attempts = 0; f.api.updateRef = async () => { attempts++; throw new Error('network'); };
  await assert.rejects(publishCloudPlan(f.plan, f.api), e => e.code === 'REF_UPDATE_NOT_APPLIED'); assert.equal(attempts, 1);
});
test('race at final ref update is rejected non-forced and divergent head is not called success', async () => {
  const f = fixture(); let attempts = 0;
  f.api.updateRef = async (_sha, force) => { assert.equal(force, false); attempts++; f.main = ADVANCED; throw new Error('422'); };
  f.api.compare = async () => ({status: 'diverged', base_commit: {sha: NEXT}, merge_base_commit: {sha: BASE}});
  await assert.rejects(publishCloudPlan(f.plan, f.api), e => e.code === 'REF_UPDATE_UNCONFIRMED'); assert.equal(attempts, 1);
});
test('candidate that landed before descendant reports ancestor and requires fresh live verification', async () => {
  const f = fixture(); const original = f.api.updateRef;
  f.api.updateRef = async (...args) => { await original(...args); f.main = ADVANCED; throw new Error('response lost'); };
  const result = await publishCloudPlan(f.plan, f.api);
  assert.equal(result.status, 'published_ancestor'); assert.equal(result.requires_fresh_verification, true);
  assert.equal(result.head_sha, ADVANCED); assert.equal(result.recovered_response, true);
});
test('ancestry assertion requires actual merge base and base commit', async () => {
  const f = fixture(); f.api.updateRef = async () => { f.main = ADVANCED; throw new Error('unknown'); };
  f.api.compare = async () => ({status: 'ahead', base_commit: {sha: BASE}, merge_base_commit: {sha: NEXT}});
  await assert.rejects(publishCloudPlan(f.plan, f.api), e => e.code === 'REF_UPDATE_UNCONFIRMED');
});
test('failed readback or ancestry call yields uncertain and never replays update', async () => {
  for (const stage of ['readback', 'compare']) {
    const f = fixture(); let attempts = 0; const oldMain = f.api.getMain;
    f.api.updateRef = async () => { attempts++; f.main = ADVANCED; throw new Error('response lost'); };
    f.api.getMain = async () => { if (stage === 'readback' && attempts) throw new Error('offline'); return oldMain(); };
    f.api.compare = async () => { throw new Error('offline'); };
    await assert.rejects(publishCloudPlan(f.plan, f.api), e => e.code === 'REF_UPDATE_UNCERTAIN'); assert.equal(attempts, 1);
  }
});
test('caller cannot mutate plan files after the first asynchronous boundary', async () => {
  const f = fixture(); const original = f.api.getMain;
  f.api.getMain = async () => { const result = await original(); f.plan.files[0].path = 'README.md';
    f.plan.files[0].content = 'bm90IHRydXN0ZWQ='; return result; };
  assert.equal((await publishCloudPlan(f.plan, f.api)).status, 'published');
  assert.equal(f.calls.find(c => c.name === 'createTree').args[1][0].path, 'data/crypto-news.en.json');
});
