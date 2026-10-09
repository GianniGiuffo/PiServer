import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

SCRIPT = Path(__file__).resolve().parents[1] / 'scripts/recover-onlyoffice.sh'

@unittest.skipUnless(shutil.which('bash'), 'Requires Bash')
class OnlyofficeRecoveryTests(unittest.TestCase):
    def run_scenario(self, scenario):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            executable = root / 'docker'
            executable.write_text('''#!/usr/bin/env python3
import json, os, sys
from pathlib import Path
args = sys.argv[1:]
with open(os.environ['CALL_LOG'], 'a') as out:
    out.write(json.dumps(args) + '\\n')
scenario = os.environ['SCENARIO']
if args[0] == 'inspect':
    if scenario == 'inspect_failure': sys.exit(1)
    print('unhealthy' if scenario == 'unhealthy' else 'healthy')
elif 'ps' in args:
    name = args[-1]
    if scenario != 'missing_' + name: print(name + '-id')
elif 'config:app:get' in args:
    if scenario == 'config_failure': sys.exit(1)
    if scenario != 'normal': print('sensitive-marker')
elif 'onlyoffice:documentserver' in args:
    print('Connection checked')
    if scenario == 'check_failure': sys.exit(1)
else:
    sys.exit(99)
''', encoding='utf8')
            executable.chmod(0o755)
            log = root / 'calls.jsonl'
            env = dict(os.environ, PATH=str(root) + os.pathsep + os.environ['PATH'],
                       SCENARIO=scenario, CALL_LOG=str(log))
            result = subprocess.run(['bash', str(SCRIPT)], env=env, text=True,
                                    capture_output=True, timeout=15)
            calls = [json.loads(line) for line in log.read_text().splitlines()]
            self.assertNotIn('sensitive-marker', result.stdout + result.stderr)
            self.assertFalse(any('up' in call or 'restart' in call or 'config:app:set' in call for call in calls))
            return result, calls

    def test_unavailable_services_and_normal_connector_do_not_recheck(self):
        for scenario in ['missing_onlyoffice', 'missing_nextcloud', 'unhealthy', 'normal']:
            with self.subTest(scenario=scenario):
                result, calls = self.run_scenario(scenario)
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertFalse(any('onlyoffice:documentserver' in call for call in calls))

    def test_stale_error_is_rechecked_with_official_command(self):
        result, calls = self.run_scenario('stale_error')
        self.assertEqual(result.returncode, 0, result.stderr)
        checks = [call for call in calls if 'onlyoffice:documentserver' in call]
        self.assertEqual(len(checks), 1)
        self.assertEqual(checks[0][-2:], ['onlyoffice:documentserver', '--check'])

    def test_failures_remain_visible_without_force_enabling(self):
        for scenario in ['inspect_failure', 'config_failure', 'check_failure']:
            with self.subTest(scenario=scenario):
                result, calls = self.run_scenario(scenario)
                self.assertNotEqual(result.returncode, 0)
                if scenario != 'check_failure':
                    self.assertFalse(any('onlyoffice:documentserver' in call for call in calls))

if __name__ == '__main__':
    unittest.main()
