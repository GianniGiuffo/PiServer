// Usage: node tests/renovate_manager_integration.mjs PATH_TO_RENOVATE_PACKAGE
// Run against the exact pinned npm package; all replacement writes go to temp.
import fs from 'node:fs';
import os from 'node:os';
import assert from 'node:assert/strict';
import { pathToFileURL, fileURLToPath } from 'node:url';
import path from 'node:path';

const packagePath = process.argv[2];
if (!packagePath) throw new Error('Provide the installed Renovate package path.');
const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const moduleFrom = (name) => import(pathToFileURL(path.join(packagePath, 'dist', name)).href);
const log = await moduleFrom('logger/index.js');
await log.init();
const { GlobalConfig } = await moduleFrom('config/global.js');
const temp = fs.mkdtempSync(path.join(os.tmpdir(), 'piserver-renovate-test-'));
GlobalConfig.set({ localDir: temp.replaceAll('\\', '/'), platform: 'github' });
const manager = await moduleFrom('modules/manager/custom/regex/index.js');
const replace = await moduleFrom('workers/repository/update/branch/auto-replace.js');
const versioning = await moduleFrom('modules/versioning/index.js');
const config = JSON.parse(fs.readFileSync(path.join(root, 'renovate.json'), 'utf8'));
const content = fs.readFileSync(path.join(root, '.env.example'), 'utf8');
const managerConfig = config.customManagers[0];
const extracted = manager.extractPackageFile(content, '.env.example', managerConfig);
const variables = new Set();
for (const name of ['compose.yaml', 'compose.media.yaml', 'compose.automation.yaml']) {
  for (const match of fs.readFileSync(path.join(root, name), 'utf8')
    .matchAll(/image: \$\{([A-Z0-9_]+_IMAGE)/g)) variables.add(match[1]);
}
assert.equal(extracted.deps.length, variables.size);
for (const [key, newValue, pin] of [
  ['AURRAL_IMAGE', '2.11.0', true],
  ['LIDARR_IMAGE', 'nightly', true],
  ['IMMICH_REDIS_IMAGE', '9', false],
]) {
  const index = extracted.deps.findIndex((dep) => dep.depType === key);
  const dep = extracted.deps[index];
  const digest = 'sha256:' + 'a'.repeat(64);
  const upgrade = {
    ...managerConfig, ...dep, manager: 'regex', packageFile: '.env.example',
    depIndex: index, newValue, newDigest: digest, isPinDigest: pin,
    autoReplaceGlobalMatch: true,
  };
  const updated = await replace.doAutoReplace(upgrade, content, false);
  assert(updated.includes(key + '=' + dep.depName + ':' + newValue + '@' + digest));
  assert.equal(updated.split('\n').length, content.split('\n').length);
  assert.equal(manager.extractPackageFile(updated, '.env.example', managerConfig).deps.length,
    variables.size);
}
for (const rule of config.packageRules.filter((r) => r.versioning)) {
  const api = versioning.get(rule.versioning);
  for (const dep of extracted.deps.filter((d) => rule.matchDepTypes.includes(d.depType))) {
    assert(api.isValid(dep.currentValue), dep.depType);
  }
}
console.log(`Renovate integration: ${variables.size} image references verified.`);

