"""Math/periodicity/source-scope fixtures; never simulate fixture circuits."""
import math
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from prepare_driven_pll_noise import render_base,ocean_script,analyses,digest
from measure_driven_pll_noise import integrate_ssb,pss_screen,noise_screen,validate_execution,sideband_comparison,observed_solver_metadata
from measure_pll import reference_boundary_snapshot
from prepare_pss_boundary_retry import shift_only_tstab,prepare as prepare_boundary_retry


class NoiseFixtures(unittest.TestCase):
    def test_boundary_retry_changes_one_literal_preserving_physical_bytes(self):
        old=(self.source()+analyses('pss')).encode('utf8')
        new=shift_only_tstab(old)
        self.assertEqual(new.replace(b'tstab=201n',b'tstab=200n'),old)
        self.assertIn(b'maxstep=1p',new)
        with self.assertRaises(ValueError):
            shift_only_tstab((self.source()+analyses('band')).encode('utf8'))
        with self.assertRaises(ValueError):
            shift_only_tstab(old.replace(b'maxstep=1p',b'maxstep=4p'))

    def test_boundary_retry_manifest_accepts_exact_new_execution_without_overwriting_failure(self):
        root=Path(__file__).resolve().parent
        with tempfile.TemporaryDirectory(dir=str(root)) as directory:
            path=Path(directory);bench=path/'fullpll_driven_pss_sb128.scs'
            bench.write_bytes((self.source()+analyses('pss')).encode('utf8'))
            failed_log=path/'original.log'
            failed_log.write_text('start = 210 ns\nERROR (SPECTRE-16192): minimum step\n')
            original=dict(cases=[dict(name=bench.stem,kind='pss',path=str(bench),
                                     bench_sha256=digest(bench),maxsideband=None)],
                          source_transient_sha256='source',frozen_periodic_base_sha256='samebase',
                          own_model_dependencies=[dict(relative_path='analog/cp.scs',sha256='moshash')],
                          locked_external_model_set_sha256='pdkhash',
                          locked_external_model_dependencies={'pdk':dict(sha256='pdkcontent',bytes=1)},
                          scope='fixture text only')
            oldmanifest=path/'manifest.json';oldmanifest.write_text(json.dumps(original))
            failure=dict(cases=[dict(name=bench.stem,execution=dict(case_id='failed',state='failed',
                         spectre_rc=1,bench_sha256=digest(bench),artifacts=[str(failed_log)]))])
            failedjson=path/'failure.json';failedjson.write_text(json.dumps(failure))
            originals={p:digest(p) for p in [bench,failed_log,oldmanifest,failedjson]}
            retry,newmanifest=prepare_boundary_retry(oldmanifest,failedjson,path)
            self.assertTrue(newmanifest.is_file())
            self.assertEqual(retry['frozen_periodic_base_sha256'],original['frozen_periodic_base_sha256'])
            self.assertEqual(retry['own_model_dependencies'],original['own_model_dependencies'])
            self.assertEqual(len(retry['cases']),1)
            self.assertEqual({p:digest(p) for p in originals},originals)
            newcase=retry['cases'][0];newbench=Path(newcase['path'])
            raw=path/'retry.raw';raw.mkdir();log=path/'retry.log'
            log.write_text('APS Enabled.\nMultithreading is disabled due to the size of the design being too small.\n')
            record=dict(state='completed',spectre_rc=0,bench_sha256=digest(newbench),
                        dependencies={'analog/cp.scs':'moshash'},source_files_unchanged_at_completion=True,
                        external_model_set_sha256='pdkhash',
                        external_model_dependencies=original['locked_external_model_dependencies'],
                        simulator_engine='aps',simulator_threads=2,artifacts=[str(raw),str(log)])
            result=validate_execution(record,retry,newcase,newbench,raw,log)
            self.assertEqual(result['actual_execution_simulator_threads'],1)

    def test_flat_SSB_factor_two_carrier_and_band(self):
        result=integrate_ssb([(1e4,-120),(1e8,-120)])
        expected=math.sqrt(2e-12*(1e8-1e4))/(2*math.pi*3.2e9)
        self.assertAlmostEqual(result['prelayout_PM_equivalent_jitter_rms_s']/expected,1,places=13)
        self.assertEqual(result['SSB_to_double_sideband_factor'],2)

    def test_one_over_f_integral_and_no_band_extrapolation(self):
        result=integrate_ssb([(1e4,-100),(1e8,-140)])
        self.assertAlmostEqual(result['SSB_integrated_power_ratio'],1e-6*math.log(1e4),places=15)
        with self.assertRaises(ValueError):integrate_ssb([(1e5,-120),(1e8,-120)])

    @staticmethod
    def source():
        # Text-parser fixture only. Never emitted as an executable bench.
        return ('simulator lang=spectre\n'
                'simulatorOptions options temp=25 reltol=1e-4 vabstol=1e-6 iabstol=1e-12\n'
                'XRF (out0 x 0 0) n12_ckt_rf\n'
                'XOSC (vdd 0 bn ctrl s0 s1 s2 s3 s4 out0 out90 out180 out270) two_stage_ring_vco\n'
                'XRX (vdd 0 bn out0 out180 clk rxp rxn) pll130_receiver_ac CC=40f RB=1M\n'
                'XD (vdd 0 clk div_rst q1 q2 q3 q4 fb) pll130_div32_cmos\n'
                'XPFD (vdd 0 ref fb rst up dn) pll130_pfd\n'
                'XCP (vdd 0 up dn ctrl) pll130_cp_drain\n'
                'VRSTD (div_rst 0) vsource type=pwl wave=[0 1.2 2n 0]\n'
                'VRSTP (rst 0) vsource type=pwl wave=[0 1.2 300n 0]\n'
                'VEN (enable 0) vsource type=pwl wave=[0 0 300n 1.2]\n'
                'VREF (ref 0) vsource type=pulse val0=0 val1=1.2 period=10n\n'
                'ic ctrl=0.8359375 filter_mid=0.8359375 out0=0.935 out180=0.933\n'
                'saveOptions options save=selected\n'
                'tran tran stop=2u maxstep=4p\n')

    def test_driven_source_freezes_both_resets_and_rejects_VA(self):
        base,frozen=render_base(self.source(),0.84,0.841)
        self.assertEqual({x['node']:x['dc_V'] for x in frozen},{'rst':0,'div_rst':0,'enable':1.2})
        self.assertNotIn('type=pwl',base)
        self.assertNotIn('tran tran',base)
        self.assertIn('ctrl=0.84 filter_mid=0.841',base)
        with self.assertRaises(ValueError):
            render_base(self.source()+'ahdl_include "unused.va"\n',0.84,0.84)
        with self.assertRaises(ValueError):
            render_base(self.source()+'VCTRL (ctrl 0) vsource dc=0.84\n',0.84,0.84)

    @staticmethod
    def waves(fb_hz=100e6):
        t=[i*1e-12 for i in range(10001)]
        y=[math.sin(2*math.pi*3.2e9*x+0.3) for x in t]
        return dict(time=t,out0=[0.934+0.0625*v for v in y],
                    out180=[0.934-0.0625*v for v in y],
                    clk=[0.6+0.6*math.sin(2*math.pi*3.2e9*x+0.15) for x in t],
                    ref=[0.6+0.6*math.sin(2*math.pi*100e6*x+0.25) for x in t],
                    fb=[0.6+0.6*math.sin(2*math.pi*fb_hz*x+0.2) for x in t],
                    ctrl=[0.842 for unused in t],filter_mid=[0.842 for unused in t],
                    vdd=[1.2 for unused in t],rst=[0 for unused in t],
                    **{'VDD:p':[-0.0045/1.2 for unused in t]})

    def test_PSS_checks_all32_VCO_cycles_and_divider_period(self):
        root=Path(__file__).resolve().parent
        with tempfile.TemporaryDirectory(dir=str(root)) as directory:
            raw=Path(directory)/'pss_td.pss'
            raw.write_text('HEADER\n"analysis type" "td.pss"\n'
                           '"fundamental" 1e8\n"period" 1e-8\nTYPE\n')
            with patch('measure_driven_pll_noise.read_psf',return_value=self.waves()):
                result=pss_screen(raw)
            self.assertTrue(result['periodic_screen_pass'])
            self.assertEqual(result['VCO_rising_cycles_per_period'],32)
            self.assertEqual(result['feedback_rising_cycles_per_period'],1)
            self.assertAlmostEqual(result['pss_total_VDD_power_W'],0.0045,places=12)
            with patch('measure_driven_pll_noise.read_psf',return_value=self.waves(200e6)):
                wrong=pss_screen(raw)
            self.assertFalse(wrong['periodic_screen_pass'])

    def test_warm_snapshot_uses_measured_boundary_not_guessed_FF_state(self):
        values=dict(time=[0,9e-9,11e-9],q1=[0,0.2,1.0],out0=[0.9,0.94,0.96])
        snapshot=reference_boundary_snapshot(values)
        self.assertAlmostEqual(snapshot['time_s'],10e-9,places=17)
        self.assertAlmostEqual(snapshot['node_voltage_V']['q1'],0.6,places=12)
        self.assertNotIn('q2',snapshot['node_voltage_V'])
        base,unused=render_base(self.source(),0.842,0.843,snapshot=snapshot)
        self.assertIn('q1=0.6',base)
        self.assertIn('out0=0.95',base)
        self.assertIn('ctrl=0.842 filter_mid=0.843',base)
        with self.assertRaises(ValueError):
            render_base(self.source().replace('period=10n','delay=3n period=10n'),
                        0.842,0.843,snapshot=snapshot)

    def test_changed_actual_include_hash_is_rejected(self):
        root=Path(__file__).resolve().parent
        with tempfile.TemporaryDirectory(dir=str(root)) as directory:
            bench=Path(directory)/'executed.scs';bench.write_text('fixture identity only\n')
            case=dict(bench_sha256=digest(bench))
            model=dict(relative_path='analog/pll130_cp_drain_candidate.scs',sha256='A'*64)
            manifest=dict(own_model_dependencies=[model],locked_external_model_set_sha256='EXT',
                          locked_external_model_dependencies={'/PDK/model.scs':{'sha256':'P'*64,'bytes':100}})
            record=dict(state='completed',spectre_rc=0,bench_sha256=digest(bench),
                        dependencies={model['relative_path']:model['sha256']},
                        source_files_unchanged_at_completion=True,external_model_set_sha256='EXT',
                        external_model_dependencies=manifest['locked_external_model_dependencies'])
            validate_execution(record,manifest,case,bench)
            record['dependencies'][model['relative_path']]='B'*64
            with self.assertRaises(ValueError):validate_execution(record,manifest,case,bench)
            record['dependencies'][model['relative_path']]=model['sha256']
            record['external_model_set_sha256']='CHANGED'
            with self.assertRaises(ValueError):validate_execution(record,manifest,case,bench)
            record['external_model_set_sha256']='EXT'
            raw=Path(directory)/'actual.raw';raw.mkdir()
            log=Path(directory)/'actual.log'
            log.write_text('Command line: +aps +mt=2\n    APS Enabled.\n'
                           '    Multithreading is disabled due to the size of the design being too small.\n')
            record['artifacts']=[str(bench),str(raw),str(log)]
            record.update(simulator_engine='aps',simulator_threads=2)
            checked=validate_execution(record,manifest,case,bench,raw,log)
            self.assertEqual(checked['requested_execution_simulator_threads'],2)
            self.assertEqual(checked['actual_execution_simulator_threads'],1)
            self.assertEqual(checked['actual_execution_simulator_engine'],'aps')
            with self.assertRaises(ValueError):
                validate_execution(record,manifest,case,bench,raw,Path(directory)/'other.log')

    def test_large_phase_noise_keeps_PSD_but_suppresses_valid_jitter_FoM(self):
        root=Path(__file__).resolve().parent
        with tempfile.TemporaryDirectory(dir=str(root)) as directory:
            directory=Path(directory)
            curve=directory/'pn.txt';fd=directory/'fd.txt';scalars=directory/'scalars.txt'
            curve.write_text('pnoise_pm (dBc/Hz)\n10000 -20\n1000000 -20\n10000000 -20\n100000000 -20\n')
            fd.write_text('FD magnitude\n3100000000 .001\n3200000000 .1\n3300000000 .001\n')
            area=.01*(1e8-1e4);formula=math.sqrt(2*area)/(2*math.pi*3.2e9)
            scalars.write_text('PN1M -20\nPN10M -20\nCARRIER32_MAG .1\nLOWER31_MAG .001\n'
                               'UPPER33_MAG .001\nPSS_VDD_POWER_W .0045\nSSB_AREA_RATIO {}\n'
                               'PM_EQUIVALENT_RMS_JITTER_s {}\n'.format(area,formula))
            periodic=dict(periodic_screen_pass=True,fundamental_Hz=1e8,actual_carrier_Hz=3.2e9,
                          pss_total_VDD_power_W=.0045,
                          deterministic_reference_spurs={'31':{'dBc':-40},'33':{'dBc':-40}})
            result=noise_screen(periodic,curve,fd,scalars)
            self.assertTrue(result['noise_calculation_available'])
            self.assertFalse(result['jitter_estimate_valid'])
            self.assertIsNone(result['bandlimited_noise']['prelayout_PM_equivalent_jitter_rms_s'])
            self.assertIsNone(result['nominal_pre_layout_jitter_power_FoM_dB'])

    def test_sideband_comparison_rejects_changed_or_unknown_solver(self):
        common=dict(noise_calculation_available=True,jitter_estimate_valid=True,
                    source_transient_sha256='same physical source',frozen_periodic_base_sha256='same base',
                    own_model_dependencies=['same models'],locked_external_model_set_sha256='same PDK hash',
                    locked_external_model_dependencies={'PDK':'same graph'},
                    bandlimited_noise={'prelayout_PM_equivalent_jitter_rms_s':1e-12},
                    offset_noise={'PN1M_dBc_Hz':-100,'PN10M_dBc_Hz':-110},
                    actual_execution_simulator_engine='aps',actual_execution_simulator_threads=1)
        a=dict(common,maxsideband=128);b=dict(common,maxsideband=192)
        self.assertTrue(sideband_comparison(a,b)['same_engine_verified'])
        b['actual_execution_simulator_engine']='classic'
        with self.assertRaises(ValueError):sideband_comparison(a,b)
        b['actual_execution_simulator_engine']='aps'
        del b['actual_execution_simulator_threads']
        with self.assertRaises(ValueError):sideband_comparison(a,b)
        b['actual_execution_simulator_threads']=None
        with self.assertRaises(ValueError):sideband_comparison(a,b)

    def test_requested_threads_or_APS_advice_are_not_observed_runtime(self):
        root=Path(__file__).resolve().parent
        with tempfile.TemporaryDirectory(dir=str(root)) as directory:
            log=Path(directory)/'runtime.log'
            log.write_text('Command line: +aps +mt=2\n    APS Enabled.\n'
                           'Recommendation: add ++aps on command line\n')
            observed=observed_solver_metadata(log)
            self.assertEqual(observed['actual_execution_simulator_engine'],'aps')
            self.assertIsNone(observed['actual_execution_simulator_threads'])
            log.write_text('Recommendation: add ++aps on command line\n')
            observed=observed_solver_metadata(log)
            self.assertIsNone(observed['actual_execution_simulator_engine'])
            self.assertIsNone(observed['actual_execution_simulator_threads'])


if __name__=='__main__':unittest.main()
