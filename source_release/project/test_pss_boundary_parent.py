"""No-process fixtures for the unique bounded PSS parent. Never simulate."""
import hashlib
import importlib.util
import json
from pathlib import Path
import tempfile
import threading
import types
import unittest
from unittest.mock import patch
import sys

ROOT=Path(__file__).resolve().parent
sys.path.insert(0,str(ROOT/'pll_full/analog'))
from prepare_pss_boundary_retry import prepare,shift_only_tstab
from prepare_driven_pll_noise import analyses


def load_parent():
    spec=importlib.util.spec_from_file_location('pss_boundary_parent',str(ROOT/'run_pss_boundary_retry_20261007.py'))
    module=importlib.util.module_from_spec(spec)
    fake=types.SimpleNamespace(LOCK_EX=1,LOCK_NB=2,flock=lambda *args:None)
    with patch.dict(sys.modules,fcntl=fake):spec.loader.exec_module(module)
    return module


class ParentFixture(unittest.TestCase):
    def run_fixture(self,passed):
        parent=load_parent()
        with tempfile.TemporaryDirectory(dir=str(ROOT)) as directory:
            project=Path(directory);benches=project/'pll_full/analog/benches';benches.mkdir(parents=True)
            folder=project/'results/fullpll/noise';folder.mkdir(parents=True)
            # Parser fixture text only, never handed to a simulator.
            original=benches/'fullpll_driven_pss_sb128.scs'
            original.write_bytes(('// fixture, never execute\n'+analyses('pss')).encode())
            oldlog=folder/'original.log';oldlog.write_text('start = 210 ns\nERROR (SPECTRE-16192)\n')
            oldmanifest=benches/'driven_noise_manifest.json'
            oldmanifest.write_text(json.dumps(dict(cases=[dict(name=original.stem,path=str(original),kind='pss',
                maxsideband=None,bench_sha256=parent.digest(original))],scope='fixture only')))
            failure=dict(cases=[dict(name=original.stem,execution=dict(state='failed',spectre_rc=1,
                          case_id='original',bench_sha256=parent.digest(original),artifacts=[str(oldlog)]))])
            oldstatus=project/'results/driven_pll_noise_status_20261007.json'
            oldstatus.write_text(json.dumps(failure));oldsummary=folder/'driven_noise_summary.json'
            oldsummary.write_text(json.dumps(failure))
            retry,newmanifest=prepare(oldmanifest,oldstatus,benches)
            before={p:parent.digest(p) for p in [original,oldlog,oldstatus,oldsummary,oldmanifest]}
            calls=[]
            def atomic_json(path,data):path.write_text(json.dumps(data))
            def run_process(command,output,cwd,deadline):
                calls.append(command);output.write_text('fixture subprocess replacement; no subprocess launched')
                paths=parent.output_paths(project)
                if '--group' in command:
                    self.assertEqual(command[-2:],['--timeout-seconds','1185'])
                    raw=folder/'new.raw';raw.mkdir();log=folder/'new.log';log.write_text('fixture only')
                    record=dict(name=parent.CASE,state='completed' if passed else 'failed',
                                spectre_rc=0 if passed else 1,
                                artifacts=[retry['cases'][0]['path'],str(raw),str(log)],
                                error=None if passed else 'fixture convergence failure')
                    paths['execution'].write_text(json.dumps([record]));return 0
                self.assertIn('measure_driven_pll_noise.py',command[1])
                self.assertEqual(command[command.index('--manifest')+1],str(newmanifest))
                self.assertEqual(command[command.index('--case-name')+1],parent.CASE)
                paths['measurement'].write_text(json.dumps(dict(periodic_screen_pass=True)));return 0
            helper=types.SimpleNamespace(atomic_json=atomic_json,run_process=run_process,
                STOP=threading.Event(),ACTIVE_LOCK=threading.Lock(),ACTIVE={},
                stop_process_group=lambda *args:None)
            with patch.object(parent,'PROJECT',project),patch.object(parent.Path,'cwd',return_value=project),\
                 patch.object(parent.signal,'signal'),patch.object(sys,'argv',['runner','--manifest',str(newmanifest)]),\
                 patch.dict(sys.modules,run_background_phase3=helper):
                self.assertEqual(parent.main(),0)
            result=json.loads(parent.output_paths(project)['summary'].read_text())
            self.assertEqual({p:parent.digest(p) for p in before},before)
            self.assertTrue(result['original_status_summary_unchanged'])
            self.assertFalse(result['noise_calculation_available'])
            self.assertIsNone(result['PLL_noise_jitter_rms_s'])
            self.assertEqual(len(calls),2 if passed else 1)
            self.assertEqual(result['PSS_periodic_evidence_available'],passed)
            if not passed:self.assertTrue(result['no_more_retries'])
            # Unique case cannot be launched again once summary/record exists.
            with self.assertRaises(ValueError):parent.review_inputs(project,newmanifest)

    def test_rc1_never_extracts_and_preserves_original_evidence(self):self.run_fixture(False)
    def test_rc0_uses_exact_new_manifest_for_read_only_screen(self):self.run_fixture(True)


if __name__=='__main__':unittest.main()
