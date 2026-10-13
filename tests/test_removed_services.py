from pathlib import Path
import re
import unittest

ROOT=Path(__file__).resolve().parents[1]

class RemovedServicesTests(unittest.TestCase):
    def test_retired_services_cannot_reappear_in_runtime_configuration(self):
        for name in ['.env.example','compose.media.yaml','compose.automation.yaml',
                     'scripts/start-stack.sh','scripts/stop-stack.sh','scripts/update-images.sh',
                     'scripts/bootstrap.sh','scripts/backup.sh','renovate.json',
                     'config/homepage/services.yaml']:
            source=(ROOT/name).read_text(encoding='utf-8')
            self.assertNotRegex(source,re.compile(r'bazarr|searxng',re.I),name)
        serve=(ROOT/'scripts/configure-tailscale-serve.sh').read_text()
        self.assertNotIn('--https=8462',serve)
        self.assertFalse((ROOT/'scripts/configure-bazarr-arr.py').exists())
        self.assertFalse((ROOT/'config/searxng/settings.yml').exists())

    def test_remaining_ai_connector_keeps_its_network_isolation(self):
        automation=(ROOT/'compose.automation.yaml').read_text()
        media=(ROOT/'compose.media.yaml').read_text()
        n8n=automation.split('  n8n:',1)[1].split('\nnetworks:',1)[0]
        nextcloud=media.split('  nextcloud:',1)[1].split('  nextcloud-readonly:',1)[0]
        readonly=media.split('  nextcloud-readonly:',1)[1].split('  nextcloud-cron:',1)[0]
        self.assertIn('ai-connectors',n8n)
        self.assertNotIn('ai-connectors',nextcloud)
        self.assertIn('ai-connectors',readonly)
        self.assertIn('internal: true',automation.split('  ai-connectors:',1)[1])

if __name__=='__main__':unittest.main()
