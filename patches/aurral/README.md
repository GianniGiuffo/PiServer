# Aurral 2.10.0: source metadata validation

`postDownloadValidator-2.10.0.js` is the upstream v2.10.0 file with two changes:
use the embedded title unchanged for the identity comparison; apply
`claimedTitle()` only when falling back to a filename. In 2.10.0 that helper
keeps only the last segment of a string separated by ` - `, so a correctly
tagged `MONTAGEM URANIUM - Slowed` becomes just `Slowed` and fails validation.
The Beets comparison also uses `getCoreTitle()` on the candidate, as it
already does on the request and on search candidates. Version differences
are checked by the semantic policy before this comparison; a regular
recording still fails a request for Slowed or Super Slowed.

`config/aurral/yt-dlp.conf` also embeds the video's own metadata and parses
`Artist - Title` before downloading. This preserves source evidence before
Aurral validates it. It does not write the requested title or artist into an
unverified download, and it leaves flat search JSON unchanged.

The compose mounts both files read-only. The validator backport is specific
to `ghcr.io/lklynet/aurral:2.10.0`. When upgrading Aurral, remove or rebase this
mount after confirming that the new validator preserves embedded titles.
Never carry the 2.10.0 module into a different version without checking its
imports and API. The yt-dlp configuration can remain.

Upstream source: <https://github.com/lklynet/aurral/tree/v2.10.0>
(commit `832ae3dfdfe7cec124e392a60df7356736c6737a`), MIT license in `LICENSE`.

Run the offline integration checks inside the Aurral container:

```sh
docker cp tests/test_aurral_ytdlp.py raspberry-server-aurral-1:/tmp/test_aurral_ytdlp.py
docker exec raspberry-server-aurral-1 python3 /tmp/test_aurral_ytdlp.py /etc/yt-dlp.conf
```

The tests download synthetic audio from a temporary loopback HTTP server,
check the tags with ffprobe, and use the actual Aurral validator with a
temporary database. Matching Slowed/Super Slowed tracks must pass; a wrong
version, karaoke, or a different track must fail.
