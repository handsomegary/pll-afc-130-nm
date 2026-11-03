"""Meaningful math/measurement fixtures, not transistor performance tests."""
import math
import unittest
import tempfile
from pathlib import Path
from loop_design import crossover, design, impedance, open_loop
from measure_pll import measure_lock, read_psf


class AnalogFixtures(unittest.TestCase):
    def test_psf_scalar_type_and_prop_are_parsed(self):
        fixture_root=Path(__file__).resolve().parent
        with tempfile.TemporaryDirectory(dir=str(fixture_root)) as folder:
            Path(folder).resolve().relative_to(fixture_root)
            path=Path(folder)/'fixture.dc'
            path.write_text('HEADER\n"ignored" 12\nVALUE\n'
                            '"VCLAMP:p" "I" 2.025e-05 PROP(\n'
                            '"ctrl" "V" 0.8359375\n'
                            '"time" 1.0e-9\nEND\n')
            result=read_psf(path)
            self.assertEqual(result['VCLAMP:p'],[2.025e-5])
            self.assertEqual(result['ctrl'],[0.8359375])
            self.assertNotIn('ignored',result)

    def test_small_signal_unity_and_pole_zero(self):
        p = design()
        self.assertAlmostEqual(abs(open_loop(2e6,20e-6,423e6,32,
                                             p['R_ohm'],p['C_shunt_F'],
                                             p['C_series_F'])),1.0,places=10)
        self.assertAlmostEqual(crossover(p)['phase_margin_deg'],64.653824058,places=7)
        wz = 1/(p['R_ohm']*p['C_series_F'])
        wp = (p['C_shunt_F']+p['C_series_F'])/(
            p['R_ohm']*p['C_shunt_F']*p['C_series_F'])
        self.assertAlmostEqual(wz/(2*math.pi),500e3,places=6)
        self.assertAlmostEqual(wp/(2*math.pi),10e6,places=6)

    def test_filter_dc_and_high_frequency_limits(self):
        p = design()
        low = impedance(1,p['R_ohm'],p['C_shunt_F'],p['C_series_F'])
        high = impedance(1e12,p['R_ohm'],p['C_shunt_F'],p['C_series_F'])
        low_expected = 1/(2j*math.pi*(p['C_shunt_F']+p['C_series_F']))
        high_expected = 1/(2j*math.pi*1e12*p['C_shunt_F'])
        self.assertLess(abs(low/low_expected-1),1e-4)
        self.assertLess(abs(high/high_expected-1),1e-4)

    @staticmethod
    def waveforms(fb_hz=100e6):
        step = 20e-12
        t = [i*step for i in range(60001)]
        sine = [math.sin(2*math.pi*3.2e9*x) for x in t]
        return dict(time=t,
                    out0=[0.934+0.0625*x for x in sine],
                    out180=[0.934-0.0625*x for x in sine],
                    ref=[0.6+0.6*math.sin(2*math.pi*100e6*x) for x in t],
                    fb=[0.6+0.6*math.sin(2*math.pi*fb_hz*x+0.03) for x in t],
                    ctrl=[0.84 for x in t],vdd=[1.2 for x in t],
                    **{'VDD:p':[-0.0022/1.2 for x in t]})

    def test_lock_and_power_do_not_imply_noise_jitter(self):
        result = measure_lock(self.waveforms(),enable_s=100e-9)
        self.assertTrue(result['locked'])
        self.assertAlmostEqual(result['final_power_W'],0.0022,places=12)
        self.assertIsNone(result['physical_noise_jitter_s'])
        self.assertLess(abs(result['final_frequency_Hz']/3.2e9-1),1e-5)

    def test_reference_slip_rejects_average_frequency_only_lock(self):
        result = measure_lock(self.waveforms(fb_hz=101e6),enable_s=100e-9)
        # VCO remains exactly target, but feedback slips. Frequency-only
        # measurement would falsely pass this intentionally broken fixture.
        self.assertFalse(result['locked'])

    def test_missing_feedback_is_not_lock(self):
        waves = self.waveforms()
        waves['fb'] = [0 for unused in waves['time']]
        result = measure_lock(waves,enable_s=100e-9)
        self.assertFalse(result['locked'])
        self.assertIsNone(result['lock_time_s'])


if __name__=='__main__':
    unittest.main()
