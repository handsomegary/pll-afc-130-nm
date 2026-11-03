"""Small RF ownership/worker fixtures; no launches, signals or SSH."""
import importlib.util
from pathlib import Path
import types
import unittest
from unittest.mock import patch
import sys


def load():
    spec=importlib.util.spec_from_file_location('resume_rf_guard',str(Path(__file__).parent/'resume_rf_two_workers_20261007.py'))
    module=importlib.util.module_from_spec(spec)
    with patch.dict(sys.modules,fcntl=types.SimpleNamespace()):spec.loader.exec_module(module)
    return module


class OwnershipFixtures(unittest.TestCase):
    def setUp(self):
        self.m=load();self.driver=self.m.expected_driver(123978,'1646852',1000,1)
        self.driver.update(comm='python3',ppid=1,state='S')

    def pair(self,case,wpid,bpid):
        m=self.m;tag='rfvalidation_'+case+'_a1'
        tail=[str(m.PROJECT/'netlists'/(tag+'.scs')),'-format','psfascii','-raw',
              str(m.PROJECT/'results/rfvalidation'/(tag+'.raw')),'+log',str(m.PROJECT/'logs'/(tag+'.log'))]
        def row(pid,ppid,argv):return dict(pid=pid,ppid=ppid,uid=1000,uids=[1000]*4,
                  cwd=str(m.PROJECT),start_ticks=str(pid+100),argv=argv,comm='spectre',state='S')
        return [row(wpid,self.driver['pid'],['/bin/ksh',m.SPECTRE_WRAPPER]+tail),
                row(bpid,wpid,[m.SPECTRE_BINARY]+tail)]

    def test_two_pairs_are_two_workers_not_four(self):
        rows=[self.driver]+self.pair('pvt_c24_u1000000_tt_1080_25_abcd',50068,50081)+self.pair('pvt_c23_u300000_tt_1080_25_efgh',50100,50101)
        self.m.analyze_rf_processes(rows,1000,self.driver,2)
        with self.assertRaises(RuntimeError):self.m.analyze_rf_processes(rows,1000,self.driver,1)

    def test_same_case_two_actual_jobs_and_unknown_wrapper_rejected(self):
        rows=[self.driver]+self.pair('pvt_c24_u1000000_tt_1080_25_abcd',50068,50081)+self.pair('pvt_c24_u1000000_tt_1080_25_abcd',50100,50101)
        with self.assertRaises(RuntimeError):self.m.analyze_rf_processes(rows,1000,self.driver,2)
        rows=[self.driver]+self.pair('pvt_c24_u1000000_tt_1080_25_abcd',50068,50081)
        rows[1]['argv'][0]='/bin/bash'
        with self.assertRaises(RuntimeError):self.m.analyze_rf_processes(rows,1000,self.driver,2)

    def test_wrapper_birth_gap_is_bounded_reread_not_duplicate_job(self):
        pair=self.pair('pvt_c24_u1000000_tt_1080_25_abcd',50068,50081)
        with patch.object(self.m,'inventory',side_effect=[[self.driver,pair[0]],[self.driver]+pair]),\
             patch.object(self.m.time,'sleep'):
            self.m.current_guards(1000,self.driver,1)
        pair[0]['ppid']=999
        with self.assertRaises(RuntimeError):self.m.analyze_rf_processes([self.driver]+pair,1000,self.driver,1)

    def test_signal_requires_exact_starttick_and_all_uids(self):
        changed=dict(self.driver,start_ticks='1646853')
        with patch.object(self.m,'inspect',return_value=changed),patch.object(self.m.os,'kill') as kill:
            with self.assertRaises(RuntimeError):self.m.signal_driver_only(self.driver)
            kill.assert_not_called()
        with patch.object(self.m,'inspect',return_value=dict(self.driver)),patch.object(self.m.os,'kill') as kill:
            self.m.signal_driver_only(self.driver);kill.assert_called_once_with(123978,self.m.signal.SIGTERM)

    def test_reviewed_schedule_has136_unique_specs_and_foreign_driver_not_signaled(self):
        specs=self.m.case_schedule(26,.8359375)
        self.assertEqual(len(specs),136)
        self.assertEqual(len({tuple(sorted(spec.items())) for spec in specs}),136)
        other=dict(self.driver,pid=999,uid=2000,uids=[2000]*4)
        with patch.object(self.m.os,'kill') as kill:
            with self.assertRaises(RuntimeError):self.m.analyze_rf_processes([self.driver,other],1000,self.driver,1)
            kill.assert_not_called()


if __name__=='__main__':unittest.main()
