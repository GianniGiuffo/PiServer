import test from 'node:test';
import assert from 'node:assert/strict';
const { nextVersionSource, resolveNormalVersionTrack } = await import(process.env.AURRAL_VERSION_FALLBACK_PATH || '/app/backend/services/versionFallback.js');
const sources = [{ id: 'slskd' }, { id: 'ytdlp' }];
const job = { playlistType: 'playlist', trackName: 'MONTAGEM URANIUM - Slowed', artistName: 'ZAYLO', trackMbid: 'slowed-recording', albumMbid: 'slowed-release', durationMs: 120000 };

test('requested version exhausts every source before the normal pass', () => {
  let payload = { jobId: 'test', phase: 'search', track: { ...job } };
  const sequence = [];
  for (let i = 0; i < 4; i++) {
    payload = nextVersionSource(payload, sources, payload.source || null, i ? 'not found' : null, job);
    assert.ok(payload);
    sequence.push([payload.source, payload.normalVersionFallback]);
  }
  assert.deepEqual(sequence, [['slskd', false], ['ytdlp', false], ['slskd', true], ['ytdlp', true]]);
  assert.equal(nextVersionSource(payload, sources, 'ytdlp', 'not found', job), null);
  assert.equal(payload.sourceErrors.length, 3);
});

test('a normal request has one pass and a single configured source has two bounded version passes', () => {
  const payload = { track: { trackName: 'MONTAGEM URANIUM' }, triedSources: ['slskd'], source: 'ytdlp' };
  assert.equal(nextVersionSource(payload, sources, 'ytdlp', 'not found', { ...job, trackName: 'MONTAGEM URANIUM' }), null);
  const fallback = nextVersionSource({ track: job, source: 'slskd' }, sources.slice(0, 1), 'slskd', 'not found', job);
  assert.equal(fallback.normalVersionFallback, true);
  assert.equal(nextVersionSource(fallback, sources.slice(0, 1), 'slskd', 'not found', job), null);
});

test('only the explicit normal pass clears variant metadata, without mutating the job', () => {
  assert.equal(resolveNormalVersionTrack(job, {}), job);
  const normal = resolveNormalVersionTrack(job, { normalVersionFallback: true });
  assert.equal(normal.trackName, 'MONTAGEM URANIUM');
  assert.equal(normal.artistName, 'ZAYLO');
  assert.equal(normal.durationMs, null);
  assert.equal(normal.trackMbid, null);
  assert.equal(normal.albumMbid, null);
  assert.equal(job.trackMbid, 'slowed-recording');
  assert.equal(job.trackName, 'MONTAGEM URANIUM - Slowed');
});

test('upgrades and library requests never receive a different recording', () => {
  for (const protectedJob of [{ ...job, upgradeForJobId: 'original' }, { ...job, playlistType: 'library' }]) {
    assert.equal(nextVersionSource({ track: job, triedSources: ['slskd'] }, sources, 'ytdlp', 'not found', protectedJob), null);
  }
});

test('edit variants can fall back; promotional titles do not start another pass', () => {
  assert.equal(nextVersionSource({ triedSources: ['slskd'] }, sources, 'ytdlp', 'not found', { ...job, trackName: 'MONTAGEM SETHRON - Edit Version' }).normalVersionFallback, true);
  assert.equal(nextVersionSource({ triedSources: ['slskd'] }, sources, 'ytdlp', 'not found', { ...job, trackName: 'MONTAGEM URANIUM (Official Audio)' }), null);
});
