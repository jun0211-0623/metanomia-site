'use strict';

const test = require('node:test');
const assert = require('node:assert/strict');
const crypto = require('node:crypto');
const fs = require('node:fs');
const vm = require('node:vm');
const {publishCloudContentPlan, REPOSITORY} = require('../scripts/cloud-content-connector.js');
const digest = text => crypto.createHash('sha1').update(text).digest('hex');
const BASE = digest('base');
const BASE_TREE = digest('base tree');
const NEXT_TREE = digest('candidate tree');
const NEXT = digest('candidate commit');
const ADVANCED = digest('another commit');
const H = 'a'.repeat(64);
const SLUG = '2026-09-09-crypto-news-1234567890';
const SWISS = '2026-09-08-crypto-news-8c5a7fe969';
const KO_PATH = 'ko/articles/report.html';
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
  const korean = '<html lang="ko"><body><a href="/pdfs/report_KOR.pdf">PDF</a><img src="/images/diagram.png"></body></html>';
  const before = [blob(KO_PATH, korean), blob('articles/report.html', 'old english'),
    blob('pdfs/report_KOR.pdf', '%PDF Korean original'), blob('pdfs/report_ENG.pdf', '%PDF old English'),
    blob('images/diagram.png', '\0image'), blob('data/media-videos.ko.json', '{"title":"한글"}'),
    blob('data/media-videos.en.json', '{"title":"old"}'),
    blob('.newsroom/content-translation-state.json', 'old state'), blob('sitemap.xml', 'old sitemap'),
    blob('search-index.json', 'old index'), blob('data/crypto-news.json', 'untouched crypto KO'),
    blob('data/crypto-news.en.json', 'untouched crypto EN'),
    blob('.newsroom/translation-state.json', 'untouched crypto state'),
    blob('README.md', 'keep unrelated bytes'), blob('assets/logo.bin', '\0binary'),
    blob('scripts/check.sh', '#!/bin/sh\n', '100755')];
  const updates = [blob('articles/report.html', '<h1>English report</h1>'),
    blob('pdfs/report_ENG.pdf', '%PDF new English'), blob('data/media-videos.en.json', '{"title":"English"}'),
    blob('.newsroom/content-translation-state.json', 'new state'), blob('sitemap.xml', 'new sitemap'),
    blob('search-index.json', 'new index')];
  const after = new Map(before.map(entry => [entry.path, entry]));
  for (const entry of updates) after.set(entry.path, entry);
  const source = (source_path, output_paths) => ({source_path, output_paths, source_sha: before.find(f => f.path === source_path).sha});
  const plan = {schema_version: '1.0', kind: 'metanomia-cloud-content-publish-plan',
    repository: REPOSITORY, branch: 'main', base_sha: BASE, base_tree_sha: BASE_TREE,
    scope_pairs: [source(KO_PATH, ['articles/report.html']), source('pdfs/report_KOR.pdf', ['pdfs/report_ENG.pdf']),
      source('data/media-videos.ko.json', ['data/media-videos.en.json']), source('images/diagram.png', [])],
    baseline_hash: H, candidate_tree_sha: NEXT_TREE,
    validation: {snapshot_hashes: {source_snapshot_hash: H, english_snapshot_hash: H, state_snapshot_hash: H},
      validated_repository_hash: H, commands: [
        ['scripts/content-translation.py', 'status'], ['scripts/audit-site.py']]
        .map(command => ({command, stdout_sha256: H}))},
    files: copy(updates), plan_hash: H};
  const f = {plan, korean, before, updates, calls: [], main: BASE,
    baseTree: rawTree(BASE_TREE, before), nextTree: rawTree(NEXT_TREE, [...after.values()]), mainReads: 0};
  const record = (name, args) => f.calls.push({name, args: copy(args)});
  f.api = {
    async getMain() { record('getMain', []); f.mainReads++; return {object: {sha: f.main}}; },
    async getCommit(sha) { record('getCommit', [sha]); return {sha,
      tree: {sha: sha === BASE ? BASE_TREE : NEXT_TREE}, parents: [{sha: sha === BASE ? ADVANCED : BASE}]}; },
    async getTree(sha) { record('getTree', [sha]); return copy(sha === BASE_TREE ? f.baseTree : f.nextTree); },
    async getText(path, ref) { record('getText', [path, ref]); assert.equal(path, KO_PATH); assert.equal(ref, BASE); return f.korean; },
    async createBlob(content) { record('createBlob', [content]); const b = Buffer.from(content, 'base64');
      return {sha: crypto.createHash('sha1').update('blob ' + b.length + '\0').update(b).digest('hex')}; },
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
  await assert.rejects(publishCloudContentPlan(f.plan, f.api), err => err.code === code,
    `Expected ${code}`);
  assert.equal(f.calls.filter(c => c.name === 'updateRef').length, 0, 'no ref update after validation failure');
}
function scopeCase(html, sources = [{source_path: 'pdfs/report_KOR.pdf', output_paths: ['pdfs/report_ENG.pdf']}]) {
  const f = fixture(); f.korean = html; f.before[0] = blob(KO_PATH, html);
  f.plan.scope_pairs = [{source_path: KO_PATH, source_sha: f.before[0].sha, output_paths: ['articles/report.html']}];
  for (const pair of sources) {
    let entry = f.before.find(entry => entry.path === pair.source_path);
    if (!entry) { entry = blob(pair.source_path, 'original asset'); f.before.push(entry); }
    f.plan.scope_pairs.push({...pair, source_sha: entry.sha});
  }
  f.baseTree = rawTree(BASE_TREE, f.before); f.plan.files = []; f.plan.candidate_tree_sha = BASE_TREE;
  return f;
}

test('publishes exact verified additions/modifications atomically and preserves every other leaf', async () => {
  const f = fixture();
  const result = await publishCloudContentPlan(f.plan, f.api);
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
  assert.equal((await publishCloudContentPlan(f.plan, f.api)).status, 'noop');
  assert.equal(f.writes().length, 0);
});
test('no-op cannot conceal a different candidate tree', async () => {
  const f = fixture(); f.plan.files = []; await blocked(f, 'INVALID_NOOP'); assert.equal(f.calls.length, 0);
});
test('pure JS global export works without Node globals, crypto, network, or filesystem', async () => {
  const context = vm.createContext({});
  vm.runInContext(fs.readFileSync(require.resolve('../scripts/cloud-content-connector.js'), 'utf8'), context);
  assert.equal(typeof context.MetanomiaCloudContentPublisher.publishCloudContentPlan, 'function');
  const f = fixture(); f.plan.files = []; f.plan.candidate_tree_sha = BASE_TREE;
  assert.equal((await context.MetanomiaCloudContentPublisher.publishCloudContentPlan(f.plan, f.api)).status, 'noop');
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
  const f = fixture(); f.plan.scope_pairs[0].source_sha = digest('wrong KO'); await blocked(f, 'SOURCE_CHANGED'); assert.equal(f.writes().length, 0);
});
for (const p of [KO_PATH, 'README.md', `.github/workflows/new.yml`, `crypto-news-${SWISS}.html`, `ko/crypto-news-${SWISS}.html`]) {
  test(`rejects disallowed file or deleted Swiss restoration: ${p}`, async () => {
    const f = fixture(); f.plan.files.push(blob(p, 'unauthorized')); await blocked(f, 'DISALLOWED_PATH'); assert.equal(f.writes().length, 0);
  });
}
test('rejects duplicate or unsafe source scope', async () => {
  const a = fixture(); a.plan.scope_pairs.push(copy(a.plan.scope_pairs[0])); await blocked(a, 'DUPLICATE_SOURCE');
  const b = fixture(); b.plan.scope_pairs[0].source_path = '../evil'; await blocked(b, 'INVALID_PATH');
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
    f => f.plan.validation.commands[0].command[1] = 'bootstrap',
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
  assert.equal((await publishCloudContentPlan(f.plan, f.api)).status, 'published');
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
  const result = await publishCloudContentPlan(f.plan, f.api);
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
  const result = await publishCloudContentPlan(f.plan, f.api);
  assert.equal(result.status, 'published'); assert.equal(result.recovered_response, true);
  assert.equal(f.calls.filter(c => c.name === 'updateRef').length, 1);
});
test('lost response with unchanged main reports not applied without retry', async () => {
  const f = fixture(); let attempts = 0; f.api.updateRef = async () => { attempts++; throw new Error('network'); };
  await assert.rejects(publishCloudContentPlan(f.plan, f.api), e => e.code === 'REF_UPDATE_NOT_APPLIED'); assert.equal(attempts, 1);
});
test('race at final ref update is rejected non-forced and divergent head is not called success', async () => {
  const f = fixture(); let attempts = 0;
  f.api.updateRef = async (_sha, force) => { assert.equal(force, false); attempts++; f.main = ADVANCED; throw new Error('422'); };
  f.api.compare = async () => ({status: 'diverged', base_commit: {sha: NEXT}, merge_base_commit: {sha: BASE}});
  await assert.rejects(publishCloudContentPlan(f.plan, f.api), e => e.code === 'REF_UPDATE_UNCONFIRMED'); assert.equal(attempts, 1);
});
test('candidate that landed before descendant reports ancestor and requires fresh live verification', async () => {
  const f = fixture(); const original = f.api.updateRef;
  f.api.updateRef = async (...args) => { await original(...args); f.main = ADVANCED; throw new Error('response lost'); };
  const result = await publishCloudContentPlan(f.plan, f.api);
  assert.equal(result.status, 'published_ancestor'); assert.equal(result.requires_fresh_verification, true);
  assert.equal(result.head_sha, ADVANCED); assert.equal(result.recovered_response, true);
});
test('ancestry assertion requires actual merge base and base commit', async () => {
  const f = fixture(); f.api.updateRef = async () => { f.main = ADVANCED; throw new Error('unknown'); };
  f.api.compare = async () => ({status: 'ahead', base_commit: {sha: BASE}, merge_base_commit: {sha: NEXT}});
  await assert.rejects(publishCloudContentPlan(f.plan, f.api), e => e.code === 'REF_UPDATE_UNCONFIRMED');
});
test('failed readback or ancestry call yields uncertain and never replays update', async () => {
  for (const stage of ['readback', 'compare']) {
    const f = fixture(); let attempts = 0; const oldMain = f.api.getMain;
    f.api.updateRef = async () => { attempts++; f.main = ADVANCED; throw new Error('response lost'); };
    f.api.getMain = async () => { if (stage === 'readback' && attempts) throw new Error('offline'); return oldMain(); };
    f.api.compare = async () => { throw new Error('offline'); };
    await assert.rejects(publishCloudContentPlan(f.plan, f.api), e => e.code === 'REF_UPDATE_UNCERTAIN'); assert.equal(attempts, 1);
  }
});
test('caller cannot mutate plan files after the first asynchronous boundary', async () => {
  const f = fixture(); const original = f.api.getMain;
  f.api.getMain = async () => { const result = await original(); f.plan.files[0].path = 'README.md';
    f.plan.files[0].content = 'bm90IHRydXN0ZWQ='; return result; };
  assert.equal((await publishCloudContentPlan(f.plan, f.api)).status, 'published');
  assert.equal(f.calls.find(c => c.name === 'createTree').args[1][0].path, 'articles/report.html');
});
test('published crypto manifests and translation records are never content outputs', async () => {
  for (const path of ['data/crypto-news.json', 'data/crypto-news.en.json', '.newsroom/translation-state.json']) {
    const f = fixture(); f.plan.files.push(blob(path, 'wrong')); await blocked(f, 'DISALLOWED_PATH'); assert.equal(f.writes().length, 0);
  }
});
test('HTML and language JSON require their one exact English counterpart', async () => {
  for (const [index, outputs] of [[0, ['about.html']], [0, []], [0, ['articles/report.html', 'about.html']],
    [2, ['data/private.en.json']], [2, []]]) {
    const f = fixture(); f.plan.scope_pairs[index].output_paths = outputs; await blocked(f, 'PAIR_MISMATCH'); assert.equal(f.writes().length, 0);
  }
});
test('generated news details and crypto language JSON cannot enter source scope', async () => {
  for (const [source_path, output] of [[`ko/crypto-news-${SLUG}.html`, `crypto-news-${SLUG}.html`],
    ['ko/crypto-news-detail.html', 'crypto-news-detail.html'], ['data/crypto-news.ko.json', 'data/crypto-news.en.json']]) {
    const f = scopeCase('', [{source_path, output_paths: [output]}]); await blocked(f, 'CRYPTO_SCOPE');
  }
});
test('unsupported source types and sources absent from base are rejected', async () => {
  const f = scopeCase('', [{source_path: 'scripts/private.js', output_paths: ['scripts/private.en.js']}]);
  await blocked(f, 'INVALID_SOURCE_SCOPE');
  const missing = scopeCase(''); missing.plan.scope_pairs[1].source_path = 'pdfs/missing_KOR.pdf';
  await blocked(missing, 'SOURCE_CHANGED');
});
test('PDF translation cannot be omitted or directed to an unrelated file', async () => {
  for (const output_paths of [[], ['pdfs/another_ENG.pdf'], ['pdfs/report_KOR.pdf']]) {
    const f = scopeCase('<a href="/pdfs/report_KOR.pdf">PDF</a>', [{source_path: 'pdfs/report_KOR.pdf', output_paths}]);
    await blocked(f, 'PAIR_MISMATCH');
  }
});
test('root, relative, encoded, and HTML-entity local PDF links prove asset scope', async () => {
  for (const href of ['/pdfs/report_KOR.pdf', '../../pdfs/report_KOR.pdf', '/pdfs/report%5FKOR.pdf',
    '/pdfs/report_KOR.pdf?a=1&amp;b=2#p3', '&#47;pdfs/report_KOR.pdf',
    'https://metanomia.org/pdfs/report_KOR.pdf', 'https://www.metanomia.org/pdfs/report_KOR.pdf',
    '//metanomia-site.vercel.app/pdfs/report_KOR.pdf']) {
    const f = scopeCase(`<a href="${href}">PDF</a>`);
    assert.equal((await publishCloudContentPlan(f.plan, f.api)).status, 'noop'); assert.equal(f.writes().length, 0);
  }
});
test('asset language-name mapping is deterministic across supported markers and fallback', async () => {
  for (const [source_path, target] of [['pdfs/report_ko.pdf', 'pdfs/report_en.pdf'],
    ['pdfs/report.ko.pdf', 'pdfs/report.en.pdf'], ['pdfs/report-ko-v2.pdf', 'pdfs/report-en-v2.pdf'],
    ['pdfs/KOR-report.pdf', 'pdfs/ENG-report.pdf'], ['pdfs/report.pdf', 'pdfs/report.en.pdf']]) {
    const f = scopeCase(`<a href="/${source_path}">PDF</a>`, [{source_path, output_paths: [target]}]);
    assert.equal((await publishCloudContentPlan(f.plan, f.api)).status, 'noop');
  }
});
test('multiple asset language markers are rejected as ambiguous', async () => {
  const f = scopeCase('<a href="/pdfs/report_KOR_ko.pdf">PDF</a>',
    [{source_path: 'pdfs/report_KOR_ko.pdf', output_paths: ['pdfs/report_ENG_ko.pdf']}]);
  await blocked(f, 'AMBIGUOUS_ASSET_PAIR');
});
test('an English output cannot overwrite another original asset in scope', async () => {
  const f = scopeCase('<a href="/pdfs/report_KOR.pdf">PDF</a><a href="/pdfs/report_ENG.pdf">Other source</a>',
    [{source_path: 'pdfs/report_KOR.pdf', output_paths: ['pdfs/report_ENG.pdf']},
      {source_path: 'pdfs/report_ENG.pdf', output_paths: ['pdfs/report_ENG.en.pdf']}]);
  await blocked(f, 'OUTPUT_COLLISION');
});
test('images can be reused unchanged or translated to a deterministic English counterpart', async () => {
  for (const output_paths of [[], ['images/diagram.en.png']]) {
    const f = scopeCase('<img src="/images/diagram.png">', [{source_path: 'images/diagram.png', output_paths}]);
    assert.equal((await publishCloudContentPlan(f.plan, f.api)).status, 'noop');
  }
  const f = scopeCase('<img src="/ko/images/diagram.png">', [{source_path: 'ko/images/diagram.png', output_paths: []}]);
  assert.equal((await publishCloudContentPlan(f.plan, f.api)).status, 'noop');
});
test('translated assets cannot modify paths under the Korean tree', async () => {
  const f = scopeCase('<a href="/ko/pdfs/report_KOR.pdf">PDF</a>',
    [{source_path: 'ko/pdfs/report_KOR.pdf', output_paths: ['ko/pdfs/report_ENG.pdf']}]);
  await blocked(f, 'PAIR_MISMATCH');
});
test('images linked by poster, srcset, object, CSS attributes or style elements are recognized', async () => {
  for (const html of ['<video poster="/images/diagram.png"></video>', '<img srcset="/images/diagram.png 2x">',
    '<object data="/images/diagram.png"></object>', '<div style="background:url(/images/diagram.png)"></div>',
    '<style>.diagram{background:url("/images/diagram.png")}</style>']) {
    const f = scopeCase(html, [{source_path: 'images/diagram.png', output_paths: []}]);
    assert.equal((await publishCloudContentPlan(f.plan, f.api)).status, 'noop');
  }
});
test('unlinked assets and external/data URLs never prove local asset scope', async () => {
  for (const html of ['', '<a href="https://unrelated.example/pdf/report_KOR.pdf">PDF</a>',
    '<a href="//unrelated.example/pdf/report_KOR.pdf">PDF</a>', '<a href="data:text/html,pdfs/report_KOR.pdf">PDF</a>',
    '<a href="../../../../pdfs/report_KOR.pdf">PDF</a>', '<a href="/pdfs%5Creport_KOR.pdf">PDF</a>']) {
    const f = scopeCase(html); await blocked(f, 'UNLINKED_ASSET'); assert.equal(f.writes().length, 0);
  }
});
test('lookalike site hostnames, credentials and port overrides are not local assets', async () => {
  for (const host of ['metanomia.org.evil.example', 'metanomia.org@evil.example', 'evil@metanomia.org', 'metanomia.org:444']) {
    const f = scopeCase(`<a href="https://${host}/pdfs/report_KOR.pdf">PDF</a>`); await blocked(f, 'UNLINKED_ASSET');
  }
});
test('nested language JSON and linked ICO images use deterministic source pairing', async () => {
  const f = scopeCase('', [{source_path: 'data/nested/videos.ko.json', output_paths: ['data/nested/videos.en.json']}]);
  assert.equal((await publishCloudContentPlan(f.plan, f.api)).status, 'noop');
  const image = scopeCase('<link rel="icon" href="/images/favicon.ico">', [{source_path: 'images/favicon.ico', output_paths: []}]);
  assert.equal((await publishCloudContentPlan(image.plan, image.api)).status, 'noop');
});
test('asset scope requires a scoped HTML source, not merely any known blob', async () => {
  const f = scopeCase('<a href="/pdfs/report_KOR.pdf">PDF</a>'); f.plan.scope_pairs.shift(); await blocked(f, 'UNLINKED_ASSET');
});
test('comment, script, inert template, textarea, title, and plain prose cannot forge links', async () => {
  const link = '<a href="/pdfs/report_KOR.pdf">PDF</a>';
  for (const html of [`<!--${link}-->`, `<!--${link}`, `<script>const x='${link}';</script>`,
    `<script>const x='${link}';`, `<textarea>${link}</textarea>`, `<template>${link}</template>`,
    `<title>${link}</title>`, 'Example style="background:url(/pdfs/report_KOR.pdf)"',
    'The raw URL is /pdfs/report_KOR.pdf']) {
    const f = scopeCase(html); await blocked(f, 'UNLINKED_ASSET');
  }
});
test('a data-URL comma inside srcset cannot masquerade as a separate local asset', async () => {
  const f = scopeCase('<img srcset="data:image/png;base64,/images/diagram.png 1x">',
    [{source_path: 'images/diagram.png', output_paths: []}]); await blocked(f, 'UNLINKED_ASSET');
});
test('malformed or failed HTML reads block all publication, never infer absent links', async () => {
  const f = fixture(); f.api.getText = async () => ({content: f.korean}); await blocked(f, 'INVALID_HTML_RESPONSE');
  const denied = fixture(); denied.api.getText = async () => { throw new Error('403: denied'); };
  await assert.rejects(publishCloudContentPlan(denied.plan, denied.api), /403/); assert.equal(denied.writes().length, 0);
});
test('scope and outputs are copied before awaits so caller mutation cannot expand authority', async () => {
  const f = fixture(); const original = f.api.getMain;
  f.api.getMain = async () => { const value = await original();
    f.plan.scope_pairs[0].output_paths[0] = 'README.md'; f.plan.scope_pairs[0].source_sha = ADVANCED; return value; };
  assert.equal((await publishCloudContentPlan(f.plan, f.api)).status, 'published');
});
test('actual external PDF links grant only HTML-owned numbered English PDF counterparts', async () => {
  const f = scopeCase('<a href="https://research.example.org/report.pdf">PDF</a>', []);
  f.plan.scope_pairs[0].output_paths.push('pdfs/translated/articles/report/document-1.en.pdf');
  assert.equal((await publishCloudContentPlan(f.plan, f.api)).status, 'noop'); assert.equal(f.writes().length, 0);
});
test('external PDF output can be published atomically with its translated HTML', async () => {
  const f = fixture(); f.korean += '<iframe src="https://research.example.org/report.pdf"></iframe>';
  f.before[0] = blob(KO_PATH, f.korean); f.plan.scope_pairs[0].source_sha = f.before[0].sha;
  f.baseTree = rawTree(BASE_TREE, f.before);
  const output = blob('pdfs/translated/articles/report/document-1.en.pdf', '%PDF complete translated report');
  f.plan.scope_pairs[0].output_paths.push(output.path); f.plan.files.push(output);
  const expected = new Map(f.before.map(entry => [entry.path, entry]));
  for (const file of f.plan.files) expected.set(file.path, file);
  f.nextTree = rawTree(NEXT_TREE, [...expected.values()]);
  assert.equal((await publishCloudContentPlan(f.plan, f.api)).status, 'published');
  assert.ok(f.calls.find(c => c.name === 'createTree').args[1].some(e => e.path === output.path));
});
test('unique literal external PDF count controls exact numbered outputs', async () => {
  const html = '<a href="https://research.example.org/b.pdf">B</a><a href="https://research.example.org/a.pdf?x=1&amp;y=2">A</a>'
    + '<a href="https://research.example.org/b.pdf">B again</a><a href="https://research.example.org/a.pdf?x=1&#38;y=2">A again</a>';
  const f = scopeCase(html, []);
  f.plan.scope_pairs[0].output_paths.push('pdfs/translated/articles/report/document-1.en.pdf',
    'pdfs/translated/articles/report/document-2.en.pdf');
  assert.equal((await publishCloudContentPlan(f.plan, f.api)).status, 'noop');
  f.plan.scope_pairs[0].output_paths.push('pdfs/translated/articles/report/document-3.en.pdf');
  await blocked(f, 'PAIR_MISMATCH');
});
test('missing, unrelated, reordered, or unlinked external PDF targets are rejected', async () => {
  for (const output_paths of [['articles/report.html'], ['articles/report.html', 'pdfs/arbitrary.en.pdf'],
    ['articles/report.html', 'pdfs/translated/articles/another/document-1.en.pdf'],
    ['pdfs/translated/articles/report/document-1.en.pdf', 'articles/report.html']]) {
    const f = scopeCase('<a href="https://research.example.org/report.pdf">PDF</a>', []);
    f.plan.scope_pairs[0].output_paths = output_paths; await blocked(f, 'PAIR_MISMATCH');
  }
  const f = scopeCase('<p>No external report</p>', []);
  f.plan.scope_pairs[0].output_paths.push('pdfs/translated/articles/report/document-1.en.pdf'); await blocked(f, 'PAIR_MISMATCH');
});
test('external targets cannot be derived from private hosts, IPs, credentials, ports or non-HTTP protocols', async () => {
  for (const url of ['http://localhost/report.pdf', 'http://127.0.0.1/report.pdf', 'http://10.0.0.1/report.pdf',
    'http://[::1]/report.pdf', 'https://admin@research.example.org/report.pdf', 'https://research.example.org:8443/report.pdf',
    'https://server.internal/report.pdf', 'ftp://research.example.org/report.pdf', '//research.example.org/report.pdf',
    'javascript:https://research.example.org/report.pdf']) {
    const f = scopeCase(`<a href="${url}">PDF</a>`, []);
    f.plan.scope_pairs[0].output_paths.push('pdfs/translated/articles/report/document-1.en.pdf'); await blocked(f, 'PAIR_MISMATCH');
  }
});
test('ownsite absolute PDFs are local and never expand external output scope', async () => {
  const f = scopeCase('<a href="https://metanomia.org/pdfs/report_KOR.pdf">PDF</a>');
  f.plan.scope_pairs[0].output_paths.push('pdfs/translated/articles/report/document-1.en.pdf'); await blocked(f, 'PAIR_MISMATCH');
});
test('script, comment, plain prose and CSS external URLs cannot mint report outputs', async () => {
  for (const html of ['<!--<a href="https://research.example.org/report.pdf">PDF</a>-->',
    '<script>const x="https://research.example.org/report.pdf";</script>',
    'https://research.example.org/report.pdf', '<style>a{background:url(https://research.example.org/report.pdf)}</style>']) {
    const f = scopeCase(html, []); f.plan.scope_pairs[0].output_paths.push('pdfs/translated/articles/report/document-1.en.pdf');
    await blocked(f, 'PAIR_MISMATCH');
  }
});
test('the static crypto-news list page is an exact eligible HTML pair', async () => {
  const f = scopeCase('<html><h1>뉴스 목록</h1></html>', []);
  const source = blob('ko/crypto-news.html', f.korean); f.before.push(source);
  f.plan.scope_pairs = [{source_path: source.path, source_sha: source.sha, output_paths: ['crypto-news.html']}];
  f.baseTree = rawTree(BASE_TREE, f.before);
  f.api.getText = async (path, ref) => { assert.equal(path, source.path); assert.equal(ref, BASE); return f.korean; };
  assert.equal((await publishCloudContentPlan(f.plan, f.api)).status, 'noop');
});
test('Korean-tree image and PDF assets map outside ko while keeping their source blobs immutable', async () => {
  for (const [source_path, target] of [['ko/images/figure.png', 'images/figure.en.png'],
    ['ko/pdfs/report_KOR.pdf', 'pdfs/report_ENG.pdf']]) {
    const f = scopeCase(`<a href="/${source_path}">asset</a>`, [{source_path, output_paths: [target]}]);
    const original = f.before.find(entry => entry.path === source_path);
    const output = blob(target, source_path.endsWith('.pdf') ? '%PDF English' : 'English diagram');
    f.plan.files = [output]; f.plan.candidate_tree_sha = NEXT_TREE;
    f.nextTree = rawTree(NEXT_TREE, [...f.before.filter(entry => entry.path !== target), output]);
    assert.equal((await publishCloudContentPlan(f.plan, f.api)).status, 'published');
    assert.equal(f.nextTree.tree.find(entry => entry.path === source_path).sha, original.sha);
    assert.deepEqual(f.calls.find(c => c.name === 'createTree').args[1].map(e => e.path), [target]);
  }
});
test('a crypto-news substring does not forbid a separate eligible language JSON UI file', async () => {
  const f = scopeCase('', [{source_path: 'data/crypto-news-filters.ko.json', output_paths: ['data/crypto-news-filters.en.json']}]);
  assert.equal((await publishCloudContentPlan(f.plan, f.api)).status, 'noop');
});
