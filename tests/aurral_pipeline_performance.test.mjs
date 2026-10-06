import test from 'node:test';
import assert from 'node:assert/strict';
import { mkdtempSync, rmSync, existsSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { spawnSync } from 'node:child_process';
const helper = process.env.AURRAL_PERFORMANCE_PATH || '/app/backend/services/pipelinePerformance.js';
const { pipelinePriority, advanceTransferProgress, TRANSFER_STALL_MS } = await import(helper);

test('fallbacks precede fresh searches while transfers and finalization retain priority', () => {
  const ordered = [
    { phase: 'search' }, { phase: 'search', triedSources: ['slskd'] },
    { phase: 'poll' }, { phase: 'download' }, { phase: 'finalize' },
  ].map(pipelinePriority);
  assert.deepEqual(ordered, [0, 5, 10, 20, 30]);
  assert.equal(pipelinePriority({ phase: 'search', normalVersionFallback: true }), 5);
  assert.equal(pipelinePriority({ phase: 'finalize', upgrade: true }), -70);
});

test('stalls depend on elapsed time, even when the worker has checked only once', () => {
  const now = 1000000;
  const payload = { pollAttempts: 1, transferStartedAt: now - TRANSFER_STALL_MS };
  assert.equal(advanceTransferProgress(payload, { bytesTransferred: 0 }, now).stalled, true);
  assert.equal(advanceTransferProgress({}, null, now, now - TRANSFER_STALL_MS).stalled, true);
  assert.equal(advanceTransferProgress(payload, { bytesTransferred: 100 }, now).stalled, false);
});

test('a slow transfer stays alive while bytes advance, but stops after three minutes idle', () => {
  const p = advanceTransferProgress({ transferStartedAt: 1, transferBytes: 100 },
    { bytesTransferred: 101 }, 1000000);
  assert.equal(p.stalled, false);
  assert.equal(advanceTransferProgress(p, { bytesTransferred: 101 }, 1179999).stalled, false);
  assert.equal(advanceTransferProgress(p, { bytesTransferred: 101 }, 1180000).stalled, true);
});

test('actual mounted queue survives restart, yields searches, and abandons stalled peers',
  { skip: !existsSync('/app/backend/services/slskdOrchestrator.js') }, () => {
  const dir = mkdtempSync(join(tmpdir(), 'aurral-pipeline-test-'));
  try {
    const result = spawnSync(process.execPath, ['--input-type=module', '-e', `
      import assert from 'node:assert/strict';
      import { dbOps } from '/app/backend/db/helpers/index.js';
      dbOps.getSettings = () => ({ integrations: { slskd: { enabled: true, url: 'http://127.0.0.1:1' }, ytdlp: { enabled: false } } });
      const { db } = await import('/app/backend/config/db-sqlite.js');
      const { downloadTracker: tracker, WeeklyFlowDownloadTracker } = await import('/app/backend/services/weeklyFlow/weeklyFlowDownloadTracker.js');
      const { getPipelineQueue, enqueuePipelineJob } = await import('/app/backend/services/honkerDb.js');
      const { processPipelinePayload, enqueuePendingJobsWithoutBatch } = await import('/app/backend/services/slskdOrchestrator.js');
      const { getDownloadClient } = await import('/app/backend/services/download/downloadClientSettings.js');
      const client = getDownloadClient('slskd');
      const id = tracker.addJob({ artistName: 'Example Artist', trackName: 'Example Song', albumName: 'Example Album' }, 'test-playlist');
      assert.equal(tracker.enqueueDownloadPipeline(id), true);
      const restarted = new WeeklyFlowDownloadTracker();
      assert.equal(restarted.enqueueDownloadPipeline(id), false);
      tracker.setDownloading(id);
      const startedAt = tracker.getJob(id).startedAt;
      assert.equal(new WeeklyFlowDownloadTracker().getJob(id).status, 'downloading');
      assert.equal(tracker.resetDownloadingToPending(), 0);
      assert.equal(tracker.getJob(id).startedAt, startedAt);
      assert.equal(enqueuePendingJobsWithoutBatch(), 0);
      assert.equal(db.prepare("SELECT COUNT(*) AS n FROM _honker_live WHERE queue='slskd-pipeline'").get().n, 1);
      const row = db.prepare("SELECT id,payload FROM _honker_live WHERE queue='slskd-pipeline'").get();
      getPipelineQueue().cancel(row.id);
      let queries = 0;
      client.createSearch = async (_, options) => { assert.equal(options.searchTimeoutMs, 20000); return { id: 'query-' + ++queries }; };
      client.waitForSearch = async (_, timeout, options) => { assert.equal(timeout, 20000); assert.equal(options.gracePeriodMs, 0); return {}; };
      client.flattenSearchResults = () => [];
      client.settleSearch = async (_, options) => assert.equal(options.cancel, true);
      let next = await processPipelinePayload({ ...JSON.parse(row.payload), source: 'slskd' });
      assert.equal(queries, 1);
      assert.equal(next.phase, 'search');
      assert.equal(next.searchProgress.queries.length, 1);
      next = await processPipelinePayload(next);
      assert.equal(queries, 2);
      assert.equal(next.searchProgress.queries.length, 2);
      client.getEvents = async () => ({ events: [], totalCount: 0 });
      client.getTransfer = async () => ({ id: 'owned', state: 'Queued, Remotely', bytesTransferred: 0 });
      let removed = 0;
      client.deleteTransfer = async (user, transferId) => { assert.equal(user, 'peer'); assert.equal(transferId, 'owned'); removed++; };
      const candidate = { raw: { user: 'peer', file: 'Example Song.mp3' } };
      next = await processPipelinePayload({ jobId: id, source: 'slskd', phase: 'poll', candidate,
        candidates: [candidate, candidate], candidateIndex: 0, legacyTransfer: { id: 'owned', username: 'peer' },
        transferStartedAt: Date.now() - 180001, pollAttempts: 1 });
      assert.equal(removed, 1);
      assert.equal(next.phase, 'download');
      assert.equal(next.candidateIndex, 1);
      const priorityId = enqueuePipelineJob({ jobId: id, phase: 'search', source: 'ytdlp', triedSources: ['slskd'] });
      assert.equal(db.prepare('SELECT priority FROM _honker_live WHERE id=?').get(priorityId).priority, 5);
      console.log('Mounted pipeline integration passed');
      process.exit(0);
    `], { encoding: 'utf8', timeout: 60000, env: { ...process.env,
      NODE_ENV: 'test', AURRAL_BACKGROUND_WORKER_GROUP: 'maintenance',
      AURRAL_DATA_DIR: dir, AURRAL_DB_PATH: join(dir, 'test.db') } });
    assert.equal(result.status, 0, result.stdout + result.stderr);
  } finally { rmSync(dir, { recursive: true, force: true }); }
});
