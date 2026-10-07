// Only the operator's checked-out policy is used; remote configs are ignored.
const policy = require('./renovate-repository.json');

module.exports = {
  ...policy,
  platform: 'github',
  repositories: ['GianniGiuffo/PiServer'],
  autodiscover: false,
  onboarding: false,
  requireConfig: 'ignored',
  baseDir: '/state/base',
  cacheDir: '/state/cache',
  persistRepoData: true,
  allowScripts: false,
  allowPlugins: false,
  allowedCommands: [],
  exitCodeForErrors: true,
  force: {
    automerge: false,
    platformAutomerge: false,
    autoApprove: false,
  },
};
