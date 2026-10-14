"""Download usability checks: missing includes fail before a simulator starts."""
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]


class DownloadTests(unittest.TestCase):
    def invoke(self, root):
        return subprocess.run([sys.executable, str(ROOT / 'tools' / 'run_simulation.py'),
            '--root', str(root), '--bench', 'on', '--spectre', sys.executable, '--check-only'],
            capture_output=True, text=True, timeout=10)

    def test_preflight_does_not_start_process_or_create_runs(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / 'circuits/benches').mkdir(parents=True)
            (root / 'config').mkdir()
            (root / 'circuits/benches/pll_afc_on.scs').write_text(
                'simulator lang=spectre\ninclude "../../config/process_models.local.scs"\n')
            missing = self.invoke(root)
            self.assertEqual(missing.returncode, 2)
            self.assertIn('adapter first', missing.stderr)
            (root / 'config/process_models.local.scs').write_text('include "test.lib"\n')
            missing_include = self.invoke(root)
            self.assertEqual(missing_include.returncode, 2)
            self.assertIn('Missing include', missing_include.stderr)
            # A tiny dummy file tests file resolution only, never device semantics.
            (root / 'config/test.lib').write_text('// preflight file fixture\n')
            valid = self.invoke(root)
            self.assertEqual(valid.returncode, 0, valid.stderr)
            record = json.loads(valid.stdout)
            self.assertFalse(record['simulator_started'])
            self.assertFalse(record['electrical_or_model_semantics_verified'])
            self.assertEqual(record['public_dependencies'], 1)
            self.assertEqual(record['local_model_dependencies'], 2)
            self.assertFalse((root / 'runs').exists())

    def test_saved_export_is_portable_and_source_preserving(self):
        with tempfile.TemporaryDirectory() as temporary:
            target = Path(temporary) / 'reproduced'
            run = subprocess.run([sys.executable, str(ROOT / 'tools/reproduce_saved_results.py'),
                '--outdir', str(target)], capture_output=True, text=True, timeout=30)
            self.assertEqual(run.returncode, 0, run.stderr)
            result = json.loads((target / 'summary.json').read_text())
            self.assertFalse(result['simulator_started'])
            self.assertEqual(result['compact_trace_rows'], {'afc_on': 1000, 'afc_off': 999})
            self.assertEqual(result['recorded_results']['afc_on']['code'], 29)
            self.assertEqual(len((target / 'afc_on_compact_trace.csv').read_text().splitlines()), 1001)
        run = subprocess.run([sys.executable, str(ROOT / 'tools/reproduce_saved_results.py'),
            '--outdir', str(ROOT / 'results')], capture_output=True, text=True, timeout=30)
        self.assertEqual(run.returncode, 2)
        self.assertIn('ignored runs/', run.stderr)


if __name__ == '__main__':
    unittest.main()
