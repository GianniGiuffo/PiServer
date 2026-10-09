"""Security-sensitive connector configuration regression tests."""
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('configure_onlyoffice', ROOT/'scripts/configure-onlyoffice.py')
configure = importlib.util.module_from_spec(spec)
spec.loader.exec_module(configure)

class PublicOfficeConnectorTests(unittest.TestCase):
    def run_configurator(self, hostname):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            secret = 'a'*64
            (root/'.env').write_text('NEXTCLOUD_PUBLIC_DOMAIN='+hostname+'\nONLYOFFICE_JWT_SECRET='+secret+'\n')
            with patch.object(configure, 'ROOT', root), \
                 patch.object(configure.subprocess, 'check_output', return_value=b'{"enabled":{"onlyoffice":"10.2.1"}}'), \
                 patch.object(configure.subprocess, 'run') as run:
                configure.main()
                calls = run.call_args_list
                settings = json.loads(calls[0].kwargs['input'])
                for call in calls:
                    self.assertNotIn(secret, ' '.join(call.args[0]))
                return settings, calls

    def test_public_editor_uses_existing_host_and_private_callbacks(self):
        settings, calls = self.run_configurator('cloud.example.com')
        self.assertEqual(settings['DocumentServerUrl'], 'https://cloud.example.com/office/')
        self.assertEqual(settings['DocumentServerInternalUrl'], 'http://onlyoffice/')
        self.assertEqual(settings['StorageUrl'], 'http://nextcloud/')
        self.assertEqual(settings['verify_peer_off'], 'false')
        self.assertEqual(settings['jwt_header'], 'AuthorizationJwt')
        self.assertEqual(calls[-1].args[0][-3:], ['occ','onlyoffice:documentserver','--check'])

    def test_url_and_header_injection_is_rejected_before_mutation(self):
        for hostname in ['https://cloud.example.com', 'cloud.example.com/office',
                         'cloud.example.com:443', 'cloud..example.com', 'cloud.example.com#bad', 'localhost']:
            with self.subTest(hostname=hostname):
                with self.assertRaises(SystemExit):
                    self.run_configurator(hostname)

if __name__ == '__main__':
    unittest.main()
