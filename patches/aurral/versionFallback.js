import { getCoreTitle, stripPromoDescriptors } from "./trackMatching/semanticPolicy.js";

// A second, bounded source pass. Never relax the requested version while
// another source can still supply it, and never substitute an upgrade.
export function nextVersionSource(payload, sources, failedSource, reason, job) {
  const tried = new Set(payload.triedSources || []);
  const sourceErrors = [...(payload.sourceErrors || [])];
  if (failedSource) {
    tried.add(failedSource);
    if (reason) sourceErrors.push({ source: failedSource, message: payload.normalVersionFallback ? `Normal version: ${reason}` : reason });
  }
  let next = sources.find(source => !tried.has(source.id));
  let normalVersionFallback = payload.normalVersionFallback === true;
  if (!next && !normalVersionFallback && !payload.upgrade && !payload.upgradeForJobId && !job?.upgradeForJobId && job?.playlistType !== "library") {
    const title = job?.trackName || payload.track?.trackName || "";
    const core = getCoreTitle(title);
    if (core && core !== stripPromoDescriptors(title)) {
      next = sources[0];
      normalVersionFallback = true;
      tried.clear();
    }
  }
  if (!next) return null;
  return {
    ...payload,
    normalVersionFallback,
    track: normalVersionFallback ? { ...(payload.track || {}), normalVersionFallback: true } : payload.track,
    source: next.id,
    phase: "search",
    searchId: null,
    searchIds: [],
    candidates: [],
    candidate: null,
    candidateIndex: 0,
    candidateRetryCounts: {},
    pollAttempts: 0,
    batchId: null,
    batch: null,
    legacyTransfer: null,
    nzbId: null,
    history: null,
    downloadedPath: null,
    resolvedTrack: null,
    searchProgress: null,
    transferStartedAt: null,
    transferProgressAt: null,
    transferBytes: 0,
    delaySeconds: 0,
    triedSources: [...tried],
    sourceErrors,
  };
}

export function resolveNormalVersionTrack(track, payloadTrack) {
  if (payloadTrack?.normalVersionFallback !== true) return track;
  return {
    ...track,
    trackName: getCoreTitle(track.trackName),
    albumName: track.albumName ? getCoreTitle(track.albumName) : null,
    // The requested version's identity and length do not describe the normal
    // recording. Keep its artist, validate the normal title against the file,
    // and avoid attaching the Slowed recording/release identity to the result.
    durationMs: null,
    trackMbid: null,
    recordingMbid: null,
    albumMbid: null,
    releaseMbid: null,
    trackNumber: null,
    albumTrackCount: null,
    albumTrackTitles: [],
  };
}
