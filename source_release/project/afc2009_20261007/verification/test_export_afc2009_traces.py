"""Trace-export fixtures, not simulation evidence; frozen reader unchanged."""
from array import array
import math
import json
from pathlib import Path
import export_afc2009_traces as trace


def main():
    t=array('d',(i*50e-12 for i in range(24001)))
    data={'time':t,'out0':array('d',(.934+.08*math.sin(2*math.pi*3.2e9*x) for x in t)),
        'out180':array('d',(.934-.08*math.sin(2*math.pi*3.2e9*x) for x in t))}
    f=trace.actual_frequency_windows(data)
    assert f['available'] and len(f['windows'])==23
    assert all(row['frequency_Hz'] is not None and abs(row['frequency_Hz']/3.2e9-1)<.001 for row in f['windows'])
    codes,omitted=trace.stable_codes([[0,16],[200e-9,0],[200.1e-9,24],[500e-9,28]],1.2e-6)
    assert [row[1] for row in codes]==[16,24,28] and omitted[0]['code']==0
    digital={'enable':{'levels':[[0,0],[120e-9,1]]},
             'done':{'levels':[[0,0],[700e-9,1]]},
             'fine_enable':{'levels':[[0,0],[720e-9,1]]}}
    points,selection=trace.report_time_grid(t,codes,digital,1000,f)
    assert len(points)<=1000 and points==sorted(set(points))
    assert all(any(abs(p-time)<1e-18 for p in points) for time in [200.1e-9,500e-9,700e-9,720e-9])
    assert any(abs(p-700e-9)<1e-18 for p in points)
    assert trace.plot_frequency(f,0) is None and trace.plot_frequency(f,1.2) is None
    assert abs(trace.plot_frequency(f,.4)-3.2)<.0032
    absent=trace.actual_frequency_windows({'time':t})
    assert not absent['available'] and absent['windows']==[]
    tiny={'time':t,'out0':array('d',(.934+.001*math.sin(2*math.pi*3.2e9*x) for x in t)),
          'out180':array('d',(.934-.001*math.sin(2*math.pi*3.2e9*x) for x in t))}
    assert all(row['frequency_Hz'] is None for row in trace.actual_frequency_windows(tiny)['windows'])
    result={'fixtures_passed':7,'checks':['actual differential edge frequency',
        'sub-ns carry words excluded from stable trial-code plot',
        'bounded sorted report grid','actual code/handoff landmarks preserved',
        'plot-only frequency interpolation remains within measured center coverage',
        'missing VCO never becomes ideal-feedback proxy','insufficient amplitude frequency unknown'],
        'simulator_started':False,'scope':'Trace exporter fixtures only; no new MOS or PLL evidence.'}
    Path(__file__).with_name('trace_export_fixture_results.json').write_text(json.dumps(result,indent=2)+'\n',encoding='utf8')
    print(json.dumps(result,indent=2))


if __name__=='__main__':
    main()
