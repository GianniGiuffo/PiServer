// Scheduling and progress rules for the single Aurral 2.10 pipeline worker.
export const SEARCH_TIMEOUT_MS = 20000;
export const TRANSFER_STALL_MS = 180000;

export function pipelinePriority(payload) {
  const phase = { search: 0, poll: 10, download: 20, finalize: 30 }[payload?.phase] || 0;
  const fallback = payload?.phase === "search" &&
    (payload?.triedSources?.length > 0 || payload?.normalVersionFallback) ? 5 : 0;
  return phase + fallback - (payload?.upgrade ? 100 : 0);
}

export function advanceTransferProgress(payload, transfer, now = Date.now(), startedAt = now) {
  const bytes = Number(transfer?.bytesTransferred ?? transfer?.BytesTransferred ?? 0);
  const previousBytes = Number(payload.transferBytes || 0);
  const lastProgressAt = bytes > previousBytes ? now :
    Number(payload.transferProgressAt || payload.transferStartedAt || startedAt || now);
  return {
    transferStartedAt: Number(payload.transferStartedAt || startedAt || now),
    transferProgressAt: lastProgressAt,
    transferBytes: Math.max(bytes, previousBytes),
    stalled: now - lastProgressAt >= TRANSFER_STALL_MS,
  };
}
