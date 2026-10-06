"""Offline integration checks, run inside the Aurral image with its tools.

python3 /tmp/test_aurral_ytdlp.py /tmp/yt-dlp.conf
"""

import functools
import http.server
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import threading
import unittest


CONFIG = Path(sys.argv.pop(1)) if len(sys.argv) > 1 and sys.argv[1].endswith('.conf') else Path(__file__).resolve().parents[1] / 'config/aurral/yt-dlp.conf'
HAS_TOOLS = all(shutil.which(tool) for tool in ('yt-dlp', 'ffmpeg', 'ffprobe', 'node')) and Path('/app/backend/services/ytdlpClient.js').exists()


@unittest.skipUnless(HAS_TOOLS, 'Run inside the Aurral image')
class YtdlpSourceMetadataTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory(prefix='aurral-source-metadata-')
        cls.root = Path(cls.temp.name)
        subprocess.run(['ffmpeg', '-v', 'error', '-f', 'lavfi', '-i', 'anoisesrc=r=44100', '-t', '4', '-c:a', 'aac', '-b:a', '192k', str(cls.root / 'source.m4a')], check=True)
        handler = functools.partial(http.server.SimpleHTTPRequestHandler, directory=cls.temp.name)
        cls.server = http.server.ThreadingHTTPServer(('127.0.0.1', 0), handler)
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()
        cls.thread.join()
        cls.temp.cleanup()

    def run_ytdlp(self, title, download):
        info = {'id': 'abc123DEF45', 'title': title, 'uploader': 'Music Channel', 'duration': 4, 'extractor': 'generic', 'extractor_key': 'Generic', 'webpage_url': 'https://example.test/video', 'url': f'http://127.0.0.1:{self.server.server_port}/source.m4a', 'ext': 'm4a'}
        fixture = self.root / 'video.json'
        fixture.write_text(json.dumps(info), encoding='utf-8')
        args = ['yt-dlp', '--ignore-config', '--config-locations', str(CONFIG), '--load-info-json', str(fixture)]
        if download:
            args += ['--force-overwrites', '--no-playlist', '-x', '--audio-format', 'm4a', '--audio-quality', '0', '-o', str(self.root / '%(id)s.%(ext)s')]
        else:
            args += ['--flat-playlist', '--dump-json', '--no-download']
        return subprocess.run(args, check=True, text=True, capture_output=True, timeout=30)

    def test_search_keeps_original_title(self):
        title = 'ZAYLO - MONTAGEM URANIUM - Slowed'
        output = self.run_ytdlp(title, False)
        self.assertEqual(json.loads(output.stdout)['title'], title)

    def test_source_tags_and_actual_aurral_validation(self):
        script = """
const { validateDownloadedTrackFile } = await import(process.env.AURRAL_VALIDATOR_PATH || '/app/backend/services/trackMatching/index.js');
const { extractVariants } = await import('/app/backend/services/trackMatching/semanticPolicy.js');
const request = JSON.parse(process.argv[1]);
const result = await validateDownloadedTrackFile({request, filePath: process.argv[2], source: 'ytdlp', candidate: {provider: {id: 'abc123DEF45'}, variants: extractVariants(request.trackName)}});
console.log(JSON.stringify({valid: result.valid, reason: result.reason, title: result.parsedTags?.title}));
process.exit(0);
"""
        cases = [
            ('ZAYLO - MONTAGEM URANIUM', 'ZAYLO', 'MONTAGEM URANIUM', True),
            ('ZAYLO - MONTAGEM URANIUM (Official Audio)', 'ZAYLO', 'MONTAGEM URANIUM', True),
            ('ZAYLO - MONTAGEM URANIUM - Slowed', 'ZAYLO', 'MONTAGEM URANIUM - Slowed', True),
            ('ZAYLO – MONTAGEM URANIUM - Slowed', 'ZAYLO', 'MONTAGEM URANIUM - Slowed', True),
            ('BRYX - PARA VIBRAR - Super Slowed', 'BRYX', 'PARA VIBRAR - Super Slowed', True),
            ('BRYX - PARA VIBRAR - Slowed', 'BRYX', 'PARA VIBRAR - Super Slowed', False),
            ('ZAYLO - MONTAGEM URANIUM', 'ZAYLO', 'MONTAGEM URANIUM - Slowed', False),
            ('ZAYLO - MONTAGEM URANIUM (Karaoke Version)', 'ZAYLO', 'MONTAGEM URANIUM', False),
            ('Another Artist - Another Track', 'ZAYLO', 'MONTAGEM URANIUM', False),
        ]
        for title, artist, track, valid in cases:
            with self.subTest(title=title, request=track):
                self.run_ytdlp(title, True)
                audio = self.root / 'abc123DEF45.m4a'
                tags = json.loads(subprocess.run(['ffprobe', '-v', 'error', '-show_entries', 'format_tags=title,artist', '-of', 'json', str(audio)], check=True, text=True, capture_output=True).stdout)['format']['tags']
                self.assertEqual(tags['title'], title.split(' – ' if ' – ' in title else ' - ', 1)[1])
                self.assertEqual(tags['artist'], title.split(' – ' if ' – ' in title else ' - ', 1)[0])
                env = {**os.environ, 'AURRAL_DATA_DIR': str(self.root / 'db'), 'AURRAL_DB_PATH': str(self.root / 'db/aurral.db'), 'NODE_ENV': 'test'}
                request = json.dumps({'artistName': artist, 'trackName': track, 'durationMs': 4000})
                output = subprocess.run(['node', '--input-type=module', '-e', script, request, str(audio)], check=True, text=True, capture_output=True, env=env, timeout=60)
                result = json.loads(output.stdout.strip().splitlines()[-1])
                self.assertEqual(result['valid'], valid, result)


if __name__ == '__main__':
    unittest.main()
