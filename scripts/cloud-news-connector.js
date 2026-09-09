/*
 * Atomic GitHub-connector publishing of a trusted, locally validated cloud plan.
 * No network, filesystem, token, model, eval, or platform crypto dependency.
 *
 * The caller MUST obtain the plan from the trusted Python preparation/verification
 * helper, not from article text or arbitrary remote instructions. SHA-256 fields
 * are audit identifiers: this adapter does not recalculate them. Git's returned
 * blob SHA and the precomputed candidate tree SHA bind every uploaded byte to
 * that plan; the entire remote tree is also compared against the fixed baseline.
 *
 * api is a caller-supplied connector wrapper bound LITERALLY to REPOSITORY/main:
 * getMain(), getCommit(sha), getTree(sha) [recursive, untruncated],
 * getJson(path, ref), createBlob(base64), createTree(baseTreeSha, elements),
 * createCommit(treeSha, parentSha, message), updateRef(sha, false),
 * compare(baseCommitSha, headCommitSha). All results are raw GitHub REST objects.
 * Each write is awaited, never retried. Uploaded orphan Git objects are harmless
 * if validation fails; only the final non-forced ref update publishes anything.
 */
(function (root) {
  'use strict';

  const REPOSITORY = 'jun0211-0623/metanomia-site';
  const KO_PATH = 'data/crypto-news.json';
  const SHA1 = /^[0-9a-f]{40}$/;
  const SHA256 = /^[0-9a-f]{64}$/;
  const SLUG = /^20\d{2}-\d{2}-\d{2}-crypto-news-[0-9a-f]{10}$/;
  const SNAPSHOTS = ['source_snapshot_hash', 'english_snapshot_hash', 'state_snapshot_hash'];
  const PLAN_FIELDS = ['schema_version', 'kind', 'repository', 'branch', 'base_sha',
    'base_tree_sha', 'ko_blob_sha', 'baseline_hash', 'candidate_tree_sha',
    'validation', 'files', 'plan_hash'];
  const FILE_FIELDS = ['path', 'mode', 'type', 'sha', 'sha256', 'content', 'size'];
  const METHODS = ['getMain', 'getCommit', 'getTree', 'getJson', 'createBlob',
    'createTree', 'createCommit', 'updateRef', 'compare'];

  class CloudPublishError extends Error {
    constructor(code, message, details) {
      super(message);
      this.name = 'CloudPublishError';
      this.code = code;
      if (details) this.details = details;
    }
  }
  function check(ok, code, message, details) {
    if (!ok) throw new CloudPublishError(code, message, details);
  }
  function object(value, label) {
    check(value !== null && typeof value === 'object' && !Array.isArray(value),
      'INVALID_OBJECT', `${label} must be an object.`);
  }
  function exact(value, fields, label) {
    object(value, label);
    check(Object.keys(value).sort().join('\0') === fields.slice().sort().join('\0'),
      'INVALID_FIELDS', `${label} has missing or unexpected fields.`);
  }
  function hash(value, expression, label) {
    check(typeof value === 'string' && expression.test(value), 'INVALID_HASH', `${label} is invalid.`);
    return value;
  }
  function path(value) {
    check(typeof value === 'string' && value.length > 0 && !/[\\:\x00-\x1f\x7f]/.test(value)
      && value.split('/').every(part => part && part !== '.' && part !== '..' && part.toLowerCase() !== '.git'),
    'INVALID_PATH', 'A tree or plan path is unsafe.');
    return value;
  }
  function base64Size(content) {
    check(typeof content === 'string' && /^(?:[A-Za-z0-9+/]{4})*(?:[A-Za-z0-9+/]{2}==|[A-Za-z0-9+/]{3}=)?$/.test(content),
      'INVALID_BASE64', 'File content must be canonical base64 without whitespace.');
    const alphabet = 'ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/';
    if (content.endsWith('==')) {
      check((alphabet.indexOf(content[content.length - 3]) & 15) === 0,
        'INVALID_BASE64', 'Base64 padding contains nonzero unused bits.');
    } else if (content.endsWith('=')) {
      check((alphabet.indexOf(content[content.length - 2]) & 3) === 0,
        'INVALID_BASE64', 'Base64 padding contains nonzero unused bits.');
    }
    return content.length / 4 * 3 - (content.endsWith('==') ? 2 : content.endsWith('=') ? 1 : 0);
  }
  function mainSha(raw) {
    object(raw, 'main ref');
    const values = [raw.sha, raw.object && raw.object.sha, raw.commit && raw.commit.sha]
      .filter(value => value !== undefined);
    check(values.length > 0 && values.every(value => value === values[0]),
      'INVALID_REF', 'Main response has no unambiguous commit SHA.');
    return hash(values[0], SHA1, 'main SHA');
  }
  function commit(raw, sha, treeSha, parentSha) {
    object(raw, 'commit');
    check(raw.sha === sha && raw.tree && raw.tree.sha === treeSha,
      'COMMIT_MISMATCH', 'Commit SHA or tree does not match the verified plan.');
    check(Array.isArray(raw.parents) && raw.parents.every(p => p && SHA1.test(p.sha)),
      'COMMIT_MISMATCH', 'Commit parents are missing or malformed.');
    if (parentSha !== undefined) {
      check(raw.parents.length === 1 && raw.parents[0].sha === parentSha,
        'COMMIT_PARENT_MISMATCH', 'Publication commit must have exactly the fixed base as its parent.');
    }
  }
  function tree(raw, expectedSha) {
    object(raw, 'recursive tree');
    check(raw.sha === expectedSha && raw.truncated === false && Array.isArray(raw.tree),
      'INCOMPLETE_TREE', 'A full, untruncated recursive tree with the expected SHA is required.');
    const entries = new Map();
    const casePaths = new Set();
    const leaves = new Map();
    const directories = new Set();
    for (const item of raw.tree) {
      object(item, 'tree entry');
      path(item.path);
      hash(item.sha, SHA1, 'tree entry SHA');
      check(!casePaths.has(item.path.toLowerCase()), 'DUPLICATE_PATH', 'Tree contains a duplicate or case-colliding path.');
      casePaths.add(item.path.toLowerCase());
      entries.set(item.path, item);
      if (item.type === 'tree' && item.mode === '040000') directories.add(item.path);
      else {
        check(item.type === 'blob' && (item.mode === '100644' || item.mode === '100755'),
          'UNSAFE_TREE_ENTRY', 'Symlinks, gitlinks, and unsupported tree entries are not permitted.');
        leaves.set(item.path, {path: item.path, type: item.type, mode: item.mode, sha: item.sha});
      }
    }
    const requiredDirectories = new Set();
    for (const leafPath of leaves.keys()) {
      const parts = leafPath.split('/');
      for (let i = 1; i < parts.length; i += 1) requiredDirectories.add(parts.slice(0, i).join('/'));
    }
    check(directories.size === requiredDirectories.size
      && [...requiredDirectories].every(p => directories.has(p)),
    'INCOMPLETE_TREE', 'Recursive tree has missing, empty, or conflicting directories.');
    return {leaves, directories};
  }
  function sameLeaf(a, b) {
    return Boolean(a && b && a.sha === b.sha && a.mode === b.mode && a.type === b.type);
  }
  function exactLeaves(actual, expected) {
    check(actual.size === expected.size && [...expected].every(([p, entry]) => sameLeaf(actual.get(p), entry)),
      'TREE_DIFF_MISMATCH', 'Candidate tree deletes, adds, or changes a file outside the exact verified plan.');
  }
  function allowedPaths(korean) {
    object(korean, 'fixed Korean manifest');
    check(korean.schema_version === '1.0' && Array.isArray(korean.items),
      'INVALID_KOREAN_MANIFEST', 'Korean manifest must contain its schema and article list.');
    const allowed = new Set(['data/crypto-news.en.json', '.newsroom/translation-state.json', 'sitemap.xml']);
    const seen = new Set();
    for (const item of korean.items) {
      check(item && typeof item.slug === 'string' && SLUG.test(item.slug) && !seen.has(item.slug),
        'INVALID_KOREAN_MANIFEST', 'Korean manifest has an unsafe or duplicate article slug.');
      seen.add(item.slug);
      allowed.add(`crypto-news-${item.slug}.html`);
      allowed.add(`ko/crypto-news-${item.slug}.html`);
    }
    return allowed;
  }
  function validatePlan(input) {
    exact(input, PLAN_FIELDS, 'plan');
    check(input.schema_version === '1.0' && input.kind === 'metanomia-cloud-news-publish-plan',
      'INVALID_PLAN_VERSION', 'Unsupported cloud plan version or kind.');
    check(input.repository === REPOSITORY && input.branch === 'main',
      'WRONG_TARGET', 'Only the approved repository main branch may be published.');
    for (const key of ['base_sha', 'base_tree_sha', 'ko_blob_sha', 'candidate_tree_sha']) hash(input[key], SHA1, key);
    for (const key of ['baseline_hash', 'plan_hash']) hash(input[key], SHA256, key);
    exact(input.validation, ['snapshot_hashes', 'commands', 'validated_repository_hash'], 'validation');
    hash(input.validation.validated_repository_hash, SHA256, 'validated repository hash');
    exact(input.validation.snapshot_hashes, SNAPSHOTS, 'snapshot_hashes');
    for (const key of SNAPSHOTS) hash(input.validation.snapshot_hashes[key], SHA256, key);
    check(Array.isArray(input.validation.commands) && input.validation.commands.length === 4,
      'INVALID_VALIDATION', 'All four validation command results are required.');
    const validationCommands = [['scripts/build-news-pages.py'], ['scripts/codex-news-translation.py', 'verify'],
      ['scripts/publish_crypto_news.py', 'verify-static-pages', '--repository', '.'], ['scripts/audit-site.py']];
    for (let i = 0; i < validationCommands.length; i += 1) {
      const result = input.validation.commands[i];
      exact(result, ['command', 'stdout_sha256'], 'validation command');
      hash(result.stdout_sha256, SHA256, 'validation stdout hash');
      check(Array.isArray(result.command) && result.command.every(s => typeof s === 'string')
        && JSON.stringify(result.command) === JSON.stringify(validationCommands[i]),
      'INVALID_VALIDATION', 'Validation command arguments or order do not match the trusted verifier.');
    }
    check(Array.isArray(input.files), 'INVALID_FILES', 'Plan files must be an array.');
    const seen = new Set();
    const files = input.files.map(file => {
      exact(file, FILE_FIELDS, 'plan file');
      path(file.path);
      check(!seen.has(file.path.toLowerCase()), 'DUPLICATE_PATH', 'Plan contains a duplicate or case-colliding file path.');
      seen.add(file.path.toLowerCase());
      check(file.type === 'blob' && file.mode === '100644',
        'UNSAFE_PLAN_ENTRY', 'Only regular non-executable blob additions or modifications are permitted.');
      hash(file.sha, SHA1, 'file SHA');
      hash(file.sha256, SHA256, 'file SHA-256');
      check(Number.isSafeInteger(file.size) && file.size >= 0 && base64Size(file.content) === file.size,
        'INVALID_FILE_SIZE', 'Plan file size does not match its base64 bytes.');
      return Object.freeze({...file});
    });
    check(files.length > 0 || input.candidate_tree_sha === input.base_tree_sha,
      'INVALID_NOOP', 'An empty plan cannot change the tree.');
    // Copy all inputs before the first await; caller mutation cannot alter a checked plan.
    return Object.freeze({...input, validation: Object.freeze({
      validated_repository_hash: input.validation.validated_repository_hash,
      snapshot_hashes: Object.freeze({...input.validation.snapshot_hashes}),
      commands: Object.freeze(input.validation.commands.map(result => Object.freeze({
        stdout_sha256: result.stdout_sha256, command: Object.freeze(result.command.slice())})))
    }), files: Object.freeze(files)});
  }

  async function publishCloudPlan(input, api) {
    const plan = validatePlan(input);
    object(api, 'connector API');
    for (const method of METHODS) check(typeof api[method] === 'function', 'MISSING_API', `Missing connector method ${method}.`);
    // Bind once so later mutation of the wrapper cannot change selected methods.
    const call = Object.fromEntries(METHODS.map(method => [method, api[method].bind(api)]));
    const assertMain = async () => check(mainSha(await call.getMain()) === plan.base_sha,
      'STALE_BASE', 'Main changed. Regenerate and revalidate a plan from the new Korean publication.');
    await assertMain();
    commit(await call.getCommit(plan.base_sha), plan.base_sha, plan.base_tree_sha);
    const baseline = tree(await call.getTree(plan.base_tree_sha), plan.base_tree_sha);
    const koEntry = baseline.leaves.get(KO_PATH);
    check(koEntry && koEntry.mode === '100644' && koEntry.sha === plan.ko_blob_sha,
      'KOREAN_CHANGED', 'The fixed Korean source blob does not match the verified plan.');
    const allowed = allowedPaths(await call.getJson(KO_PATH, plan.base_sha));
    const expected = new Map(baseline.leaves);
    for (const file of plan.files) {
      check(allowed.has(file.path), 'DISALLOWED_PATH', 'Plan includes a path absent from the current Korean manifest allowlist.');
      const previous = baseline.leaves.get(file.path);
      check(!previous || previous.mode === file.mode, 'MODE_CHANGE', 'Plan may not change a file mode.');
      check(!previous || previous.sha !== file.sha, 'UNCHANGED_FILE', 'Plan includes an unchanged file.');
      expected.set(file.path, {path: file.path, type: file.type, mode: file.mode, sha: file.sha});
    }
    await assertMain();
    if (plan.files.length === 0) return {status: 'noop', base_sha: plan.base_sha, plan_hash: plan.plan_hash};
    check(plan.candidate_tree_sha !== plan.base_tree_sha, 'INVALID_CANDIDATE', 'Nonempty plan must produce a different tree.');

    for (const file of plan.files) {
      const created = await call.createBlob(file.content);
      check(created && created.sha === file.sha, 'BLOB_MISMATCH', 'GitHub blob SHA does not match the validated file bytes.');
    }
    const elements = plan.files.map(({path: p, mode, type, sha}) => ({path: p, mode, type, sha}));
    const createdTree = await call.createTree(plan.base_tree_sha, elements);
    check(createdTree && createdTree.sha === plan.candidate_tree_sha,
      'TREE_SHA_MISMATCH', 'GitHub candidate tree SHA does not match the precomputed validated tree.');
    const candidateTree = tree(await call.getTree(plan.candidate_tree_sha), plan.candidate_tree_sha);
    exactLeaves(candidateTree.leaves, expected);
    check(sameLeaf(candidateTree.leaves.get(KO_PATH), koEntry),
      'KOREAN_CHANGED', 'Publication must preserve Korean manifest bytes exactly.');
    await assertMain();
    const message = `chore: publish verified cloud English crypto news\n\nCloud-plan: ${plan.plan_hash}`;
    const createdCommit = await call.createCommit(plan.candidate_tree_sha, plan.base_sha, message);
    const candidateSha = hash(createdCommit && createdCommit.sha, SHA1, 'created commit SHA');
    // The native connector can return only {sha}; never infer parents or tree
    // from that acknowledgement. Check any metadata it does return, then always
    // fetch the actual Git commit object before attempting a ref update.
    if (createdCommit.tree !== undefined || createdCommit.parents !== undefined) {
      commit(createdCommit, candidateSha, plan.candidate_tree_sha, plan.base_sha);
    }
    commit(await call.getCommit(candidateSha), candidateSha, plan.candidate_tree_sha, plan.base_sha);
    await assertMain();
    let updateError = false;
    try {
      const updated = await call.updateRef(candidateSha, false);
      check(mainSha(updated) === candidateSha, 'REF_RESPONSE_MISMATCH', 'Ref update returned an unexpected SHA.');
    } catch (_) {
      // Never retry a ref update after either a rejection or a lost response.
      updateError = true;
    }
    const details = {candidate_sha: candidateSha, base_sha: plan.base_sha, plan_hash: plan.plan_hash};
    let observed;
    try { observed = mainSha(await call.getMain()); }
    catch (_) { throw new CloudPublishError('REF_UPDATE_UNCERTAIN', 'Could not read main after the single ref-update attempt. Do not retry blindly.', details); }
    if (observed === candidateSha) return {...details, status: 'published', head_sha: observed, recovered_response: updateError};
    if (observed === plan.base_sha) throw new CloudPublishError('REF_UPDATE_NOT_APPLIED', 'Main is still at the base. Publication was not confirmed; do not retry this plan blindly.', details);
    let comparison;
    try { comparison = await call.compare(candidateSha, observed); }
    catch (_) { throw new CloudPublishError('REF_UPDATE_UNCERTAIN', 'Main changed, but ancestry could not be verified. Do not retry blindly.', {...details, head_sha: observed}); }
    check(comparison && comparison.status === 'ahead' && comparison.base_commit
      && comparison.base_commit.sha === candidateSha && comparison.merge_base_commit
      && comparison.merge_base_commit.sha === candidateSha,
    'REF_UPDATE_UNCONFIRMED', 'The candidate is not a verified ancestor of current main.', {...details, head_sha: observed});
    // The commit landed but somebody may have legitimately published newer news.
    // Caller must inspect the new head and live site, never report it as unchanged.
    return {...details, status: 'published_ancestor', head_sha: observed,
      recovered_response: updateError, requires_fresh_verification: true};
  }

  const exported = Object.freeze({publishCloudPlan, CloudPublishError, REPOSITORY});
  if (typeof module !== 'undefined' && module.exports) module.exports = exported;
  root.MetanomiaCloudPublisher = exported;
})(globalThis);
