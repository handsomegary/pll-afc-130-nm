"""Exercise generated literal gate graph and ideal edge flops independently.

The counter-front-end is driven with integer count observations. This checks
the actual source-generator Boolean FSM, arithmetic, snapshots and fail-safe
sequencing, not the physical TG latch timing, phase selector or CDC.
"""
import importlib.util
import itertools
import json
from pathlib import Path


class LiteralModel:
    def __init__(self,circuit):
        self.ops=circuit.logic_ops;self.flops=circuit.flop_records
        self.values={'vdd':1,'vss':0,'ref':0,'fb':0,'rst':1,'start':0}
        self.values.update({r['q']:r['preset'] for r in self.flops})
        self.fixed={};self.history=[];self.states=[];self.done_cycle=None;self.fine_cycle=None;self.fail_cycle=None
        self.arm_age=0;self.measure_age=0

    def settle(self):
        for _ in range(100):
            changed=False
            for record in self.ops:
                op,out,*inputs=record
                if out in self.fixed:continue
                bits=[self.values.get(n,0) for n in inputs]
                value=int(not bits[0]) if op=='INV' else int(not all(bits)) if op=='NAND' else int(not any(bits))
                if self.values.get(out)!=value:self.values[out]=value;changed=True
            self.values.update(self.fixed)
            if not changed:return
        raise AssertionError('Gate graph did not reach a Boolean fixed point')

    def reset_async(self):
        for _ in range(20):
            self.settle();changed=False
            for flop in self.flops:
                if flop['q'] in self.fixed:continue
                if self.values.get(flop['rst'],0) and self.values.get(flop['q'])!=flop['preset']:
                    self.values[flop['q']]=flop['preset'];changed=True
            if not changed:self.settle();return
        raise AssertionError('Async reset did not settle')

    def word(self,prefix,bits=5):
        return sum(self.values.get(prefix+str(i),0)<<i for i in range(bits))

    def counts(self,lead,lag,div,epoch):
        self.fixed={'epoch_valid':int(epoch)}
        for prefix,value in [('lead',lead),('lag',lag),('div',div)]:
            gray=value^(value>>1)
            for i in range(8):self.fixed[prefix+'_sync2_'+str(i)]=(gray>>i)&1
        self.values.update(self.fixed)

    def cycle(self,cycle):
        self.values['ref']=0;self.reset_async()
        clocks={r['clk']:self.values.get(r['clk'],0) for r in self.flops}
        self.values['ref']=1;self.reset_async()
        updates={}
        for r in self.flops:
            if r['q'] in self.fixed:continue
            if self.values.get(r['rst'],0):updates[r['q']]=r['preset']
            elif not clocks[r['clk']] and self.values.get(r['clk'],0):updates[r['q']]=self.values.get(r['d'],0)
        self.values.update(updates);self.reset_async()
        states=tuple(self.values.get(n,0) for n in ('settle','arm','measure','drain'))
        assert sum(states)<=1,('State not one-hot',cycle,states)
        self.states.append(states)
        if self.values.get('arm'):
            if self.arm_age==0:self.history.append(self.word('s'))
            self.arm_age+=1
        else:self.arm_age=0
        if self.values.get('measure'):self.measure_age+=1
        else:self.measure_age=0
        for name,attr in [('done','done_cycle'),('fine_enable','fine_cycle'),('fail','fail_cycle')]:
            if self.values.get(name) and getattr(self,attr) is None:setattr(self,attr,cycle)


def expected(pattern,near_round=None):
    code=16;history=[]
    for i,step in enumerate((8,4,2,1,0)):
        history.append(code)
        if near_round==i:return history,code,False
        direction=pattern[i]
        if step==0:return history,code,code==1 and direction=='F' or code==31 and direction=='S'
        code+=step if direction=='S' else -step
    raise AssertionError('missing terminal')


def run_fixture(circuit,pattern,near_round=None,nofb=False,stucklag=False,start_toggle=False):
    m=LiteralModel(circuit);frozen_after_terminal=None
    for cycle in range(1250):
        m.values['rst']=int(cycle<3)
        m.values['start']=int(cycle>=5 and (not start_toggle or cycle%7!=0))
        round_index=max(0,len(m.history)-1)
        epoch=m.arm_age>=5 or m.values.get('measure') or m.values.get('drain')
        if nofb:epoch=False
        if m.values.get('measure'):
            if stucklag:counts=(0,0,0)
            elif near_round==round_index:
                count=min(128,m.measure_age);counts=(count,count,count)
            elif pattern[round_index]=='F':counts=(2,2,6)
            else:counts=(6,6,2)
        else:counts=(1,0,1)
        m.counts(*counts,epoch=epoch);m.cycle(cycle)
        terminal=bool(m.values.get('fine_enable') or m.values.get('fail'))
        if terminal:
            state=(m.word('s'),m.values.get('done'),m.values.get('fail'),m.values.get('fine_enable'),m.values.get('hold'),m.values.get('pfd_reset'))
            if frozen_after_terminal is None:frozen_after_terminal=state
            else:assert state==frozen_after_terminal,('Post terminal output changed',cycle,state,frozen_after_terminal)
        if terminal and cycle>(m.fine_cycle or m.fail_cycle)+10:break
    if nofb or stucklag:
        assert m.fail_cycle is not None and m.fine_cycle is None and m.done_cycle is None
        assert m.history==[16]
        return {'kind':'no_FB' if nofb else 'stuck_lag_watchdog','passed':True,'history':m.history,'fail_cycle':m.fail_cycle}
    history,code,fails=expected(pattern,near_round)
    assert m.history==history,('Wrong tested candidate ledger',pattern,near_round,m.history,history)
    assert m.word('s')==code,('Wrong frozen code',m.word('s'),code)
    if fails:
        assert m.fail_cycle is not None and m.done_cycle is None and m.fine_cycle is None
    else:
        assert m.done_cycle is not None and m.fine_cycle==m.done_cycle+2 and m.fail_cycle is None
        assert m.values['hold']==0 and m.values['pfd_reset']==0
    return {'kind':'direction_pattern','pattern':''.join(pattern),'near_round':near_round,'start_toggle':start_toggle,'passed':True,'history':m.history,'code':code,'endpoint_fail':fails,'done_cycle':m.done_cycle,'fine_cycle':m.fine_cycle}


def main():
    root=Path(__file__).resolve().parent
    spec=importlib.util.spec_from_file_location('afc_literal_source',str(root/'build_afc2009_mos.py'));module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
    circuit=module.build();results=[]
    for pattern in itertools.product(('F','S'),repeat=5):
        results.append(run_fixture(circuit,pattern));results.append(run_fixture(circuit,pattern,start_toggle=True))
        for near_round in range(5):results.append(run_fixture(circuit,pattern,near_round=near_round))
    results.append(run_fixture(circuit,'SSSSS',nofb=True));results.append(run_fixture(circuit,'SSSSS',stucklag=True))
    for a,b in itertools.product(range(256),repeat=2):
        # Independently verify the source-generator subtract carry network.
        carry=1;diff=0
        for i in range(8):
            x=(a>>i)&1;ny=1-((b>>i)&1);xy=x^ny
            diff|=(xy^carry)<<i;carry=(x&ny)|(xy&carry)
        assert bool(carry and diff>>1)==(a-b>=2)
    result={'status':'all_passed','literal_generated_FSM_fixtures':len(results),'subtractor_pairs':65536,
            'physical_MOS_count':circuit.transistors,'DFF_count':circuit.dffs,
            'limits':'Actual generated Boolean gates and ideal edge-DFF transitions, injected integer frontend counts. Does not prove MOS timing/nonoverlap, native-counter correctness, phase epoch, CDC/metastability or PLL capture.',
            'fixtures':results}
    (root/'literal_fsm_fixture_results.json').write_text(json.dumps(result,indent=2)+'\n',encoding='utf-8')
    print(json.dumps({k:v for k,v in result.items() if k!='fixtures'},indent=2))


if __name__=='__main__':main()
