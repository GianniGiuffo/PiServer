// Run with Aurral stopped, using the same image/mounts and worker group
// "maintenance". Defaults to a dry run; --apply requires /repair-backup.
import { mkdir } from 'node:fs/promises';
import { db } from '/app/backend/config/db-sqlite.js';
import { getPipelineQueue } from '/app/backend/services/honkerDb.js';
import { getDownloadClient } from '/app/backend/services/download/downloadClientSettings.js';
import { pipelinePriority } from '/app/backend/services/pipelinePerformance.js';

const playlistId = process.argv[2];
if (!playlistId) throw new Error('Pass the playlist ID, optionally followed by --apply');
const apply = process.argv.includes('--apply');
const jobs = db.prepare('SELECT id,status FROM playlist_download_jobs WHERE playlist_id=?').all(playlistId);
const jobById = new Map(jobs.map(job => [job.id, job]));
const groups = new Map();
const rows = db.prepare("SELECT * FROM _honker_live WHERE queue='slskd-pipeline' ORDER BY id").all()
  .map(row => ({ ...row, payload: JSON.parse(row.payload) }))
  .filter(row => jobById.has(row.payload.jobId));
const client = getDownloadClient('slskd');
for (const row of rows) {
  const p = row.payload;
  if (p.phase === 'poll' && p.legacyTransfer?.id) {
    row.transfer = await client.getTransfer(p.legacyTransfer.username, p.legacyTransfer.id);
  }
  if (!groups.has(p.jobId)) groups.set(p.jobId, []);
  groups.get(p.jobId).push(row);
}
function rank(row) {
  const p = row.payload;
  const state = String(row.transfer?.state || '').toLowerCase();
  if (p.phase === 'finalize' || state.includes('completed') || state.includes('succeeded')) return 1000;
  if (Number(row.transfer?.bytesTransferred || 0) > 0) return 900;
  // A fallback proves that Soulseek was already exhausted in a previous run.
  if (p.phase === 'search' && (p.triedSources?.length || p.normalVersionFallback))
    return 500 + (p.normalVersionFallback ? 100 : 0) + (p.triedSources?.length || 0);
  return { download: 300, poll: 200, search: 100 }[p.phase] || 0;
}
const survivors = [];
for (const [id, entries] of groups) {
  if (['done', 'failed', 'blocked'].includes(jobById.get(id).status)) continue;
  entries.sort((a, b) => rank(b) - rank(a) || a.id - b.id);
  survivors.push(entries[0]);
}
console.log(JSON.stringify({ mode: apply ? 'apply' : 'dry-run', playlistId,
  before: rows.length, after: survivors.length, redundant: rows.length - survivors.length,
  phases: survivors.reduce((counts, row) => {
    const key = `${row.payload.source || 'initial'}:${row.payload.phase}`;
    counts[key] = (counts[key] || 0) + 1; return counts;
  }, {}) }));
if (apply) {
  await mkdir('/repair-backup', { recursive: true, mode: 0o700 });
  const backupPath = `/repair-backup/aurral-before-queue-repair-${Date.now()}.db`;
  await db.backup(backupPath);
  const queue = getPipelineQueue();
  // Only transfer IDs explicitly returned to this playlist's pipeline are touched.
  const retainedIds = new Set(survivors.map(r => r.payload.legacyTransfer?.id).filter(Boolean));
  const removedTransfers = new Set();
  let transfersRemoved = 0;
  for (const row of rows) {
    const legacy = row.payload.legacyTransfer;
    if (!legacy?.id || retainedIds.has(legacy.id) || removedTransfers.has(legacy.id)) continue;
    const state = String(row.transfer?.state || '').toLowerCase();
    if (Number(row.transfer?.bytesTransferred || 0) > 0 || state.includes('completed') || state.includes('succeeded')) continue;
    if (await client.deleteTransfer(legacy.username, legacy.id, { remove: true })) transfersRemoved++;
    removedTransfers.add(legacy.id);
  }
  for (const row of survivors) {
    queue.enqueue(row.payload, { priority: pipelinePriority(row.payload), runAt: Math.floor(Date.now() / 1000) });
  }
  for (const row of rows) queue.cancel(row.id);
  console.log(JSON.stringify({ repaired: survivors.length, transfersRemoved, backupPath }));
}
process.exit(0);
