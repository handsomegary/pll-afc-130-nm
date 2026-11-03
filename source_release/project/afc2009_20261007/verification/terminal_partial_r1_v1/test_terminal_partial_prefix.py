"""Digital-only PSF prefix/proc fixtures. No generated analogue actual result."""
from __future__ import print_function
import json
from pathlib import Path
import tempfile
import postprocess_terminal_partial as reader
import collect_terminal_partial_proof as proof

HERE=Path(__file__).resolve().parent


def raw_text(end=False,missing_index=None,incomplete=True):
    lines=['HEADER','VALUE']
    for index in range(32):
        lines.extend(['"time" '+repr(index*1e-9),'"bit" '+str(index%2)])
        if index!=missing_index:
            lines.append('"unselected_bit" '+str((index//2)%2))
    if incomplete:
        lines.extend(['"time" '+repr(32e-9),'"bit"'])
    if end:
        lines.append('END')
    return '\n'.join(lines)+'\n'


def main():
    cases=[]
    cfg={'analogs':{},'digitals':{'test_bit':'bit'},'words':{}}
    with tempfile.TemporaryDirectory(prefix='terminal-prefix-fixture-',dir=str(HERE)) as directory:
        directory=Path(directory)
        raw=directory/'synthetic_digital_only.tran'
        destination=directory/'prefix.tran'
        raw.write_text(raw_text(),encoding='utf8')
        evidence=reader.complete_prefix(raw,destination,cfg)
        assert evidence['accepted_complete_blocks']==32
        assert evidence['observed_stop_s']==31e-9
        assert evidence['discarded_unclosed_EOF_block_time_s']==32e-9
        assert not evidence['original_PSF_END_seen'] and evidence['derivative_adds_parser_END_only']
        assert '"unselected_bit"' not in destination.read_text(encoding='utf8')
        cases.append('Incomplete EOF block excluded; only 32 blocks closed by next time are retained, with parser END explicitly derivative')
        raw.write_text(raw_text(incomplete=False),encoding='utf8')
        evidence=reader.complete_prefix(raw,destination,cfg)
        assert evidence['accepted_complete_blocks']==31 and abs(evidence['observed_stop_s']-30e-9)<1e-21
        cases.append('Apparently complete final EOF block still excluded without an original next-time/END closure')
        raw.write_text(raw_text(end=True,incomplete=False),encoding='utf8')
        evidence=reader.complete_prefix(raw,destination,cfg)
        assert evidence['accepted_complete_blocks']==32 and evidence['original_PSF_END_seen']
        cases.append('A genuine original END closes the last block but does not establish numerical simulation PASS')
        evidence=reader.complete_prefix(raw,destination,cfg,max_stop_s=25e-9)
        assert evidence['accepted_complete_blocks']==26 and abs(evidence['observed_stop_s']-25e-9)<1e-21
        assert evidence['max_stop_reached']
        cases.append('max_stop admits only complete blocks at or before declared bounded stop')
        raw.write_text(raw_text(missing_index=20),encoding='utf8')
        try:
            reader.complete_prefix(raw,destination,cfg)
        except ValueError as error:
            assert 'scalar fields' in str(error)
        else:
            raise AssertionError('Missing unselected scalar in interior closed block accepted')
        cases.append('Missing unselected field inside a closed block invalidates completeness, not merely selected vectors')
        raw.write_text(raw_text(),encoding='utf8')
        try:
            reader.complete_prefix(raw,destination,cfg,max_stop_s=10e-9)
        except ValueError as error:
            assert 'Fewer than 20' in str(error)
        else:
            raise AssertionError('Insufficient closed prefix accepted')
        cases.append('Fewer than 20 actually closed prefix blocks cannot produce a diagnostic')
        for bound in [-1,float('inf'),float('nan')]:
            try:
                reader.complete_prefix(raw,destination,cfg,max_stop_s=bound)
            except ValueError:
                pass
            else:
                raise AssertionError('Invalid prefix bound accepted')
        cases.append('Negative/infinite/NaN max-stop values rejected')
        proc=directory/'proc'
        proc.mkdir()
        absent=proof.check_process(100,123,proc)
        assert absent['identity_gone'] and not absent['same_identity_present']
        cases.append('Absent exact own PID proves that identity gone without signaling any process')
        (proc/'100').mkdir()
        tail=['S']+['0']*18+['123']+['0']*8
        (proc/'100'/'stat').write_text('100 (synthetic own process) '+' '.join(tail)+'\n',encoding='utf8')
        alive=proof.check_process(100,123,proc)
        assert alive['same_identity_present'] and not alive['identity_gone']
        reused=proof.check_process(100,122,proc)
        assert reused['identity_gone'] and reused['reason'].startswith('PID reused')
        cases.append('Matching PID/startticks remains live; reused PID proves original identity gone and preserves the new process')
    out={'fixtures_passed':len(cases),'checks':cases,'simulator_started':False,
        'analogue_waveforms_generated':False,'physical_case_pass':None,'numerical_completion':False,
        'scope':'Digital-only PSF structure and synthetic /proc identity parser fixtures. '
            'No actual PLL measurement or artificial analogue result generated.'}
    (HERE/'prefix_fixture_results.json').write_text(json.dumps(out,indent=2)+'\n',encoding='utf8')
    print(json.dumps(out,indent=2))


if __name__=='__main__':
    main()
