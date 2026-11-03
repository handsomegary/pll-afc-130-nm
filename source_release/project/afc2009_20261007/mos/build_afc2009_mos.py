"""Generate a transistor-only static-CMOS AFC, inspired by Jeong RFIC2009.

This is a new explicit first-feedback-epoch / two-phase adaptation. It is not
the paper's underspecified quadrature divider. No behavioural timestamps,
ideal comparators, voltage-controlled logic sources or Verilog-A are used.
All state is stored in physical resettable static transmission-gate DFFs.
The reused DFF has the same dimensions as pll130_digital_mos.scs but shares
clock/reset control gates between bits to reduce duplicate gate loading.
"""
import argparse
import collections
import hashlib
import json
from pathlib import Path


class Circuit:
    def __init__(self):
        self.lines=[];self.cache={};self.seq=0;self.transistors=0
        self.cells=collections.Counter();self.dffs=0;self.flop_nodes=[]
        self.vdd='vdd';self.vss='vss';self.one='vdd';self.zero='vss'

    def node(self,prefix='n'):
        self.seq+=1;return '{}{}'.format(prefix,self.seq)

    def mos(self,d,g,s,bulk,pmos=False,w=.8,l=.13):
        name=self.node('MP' if pmos else 'MN');model='p12' if pmos else 'n12'
        self.lines.append('{} ({} {} {} {}) {} w={}u l={}u'.format(name,d,g,s,bulk,model,w,l));self.transistors+=1

    def inv(self,a,out=None):
        if out is None:
            if a==self.zero:return self.one
            if a==self.one:return self.zero
            key=('inv',a)
            if key in self.cache:return self.cache[key]
            out=self.node();self.cache[key]=out
        self.mos(out,a,self.zero,self.zero,w=.8)
        self.mos(out,a,self.one,self.one,True,w=2.4);self.cells['INV']+=1;return out

    def nand(self,a,b,out=None):
        if out is None:
            if a==self.zero or b==self.zero:return self.one
            if a==self.one:return self.inv(b)
            if b==self.one:return self.inv(a)
            if a==b:return self.inv(a)
            a,b=sorted((a,b));key=('nand',a,b)
            if key in self.cache:return self.cache[key]
            out=self.node();self.cache[key]=out
        n=self.node();self.mos(out,a,n,self.zero,w=1.6);self.mos(n,b,self.zero,self.zero,w=1.6)
        self.mos(out,a,self.one,self.one,True,w=2.4);self.mos(out,b,self.one,self.one,True,w=2.4)
        self.cells['NAND2']+=1;return out

    def nor(self,a,b,out=None):
        if out is None:
            if a==self.one or b==self.one:return self.zero
            if a==self.zero:return self.inv(b)
            if b==self.zero:return self.inv(a)
            if a==b:return self.inv(a)
            a,b=sorted((a,b));key=('nor',a,b)
            if key in self.cache:return self.cache[key]
            out=self.node();self.cache[key]=out
        n=self.node();self.mos(out,a,self.zero,self.zero,w=.8);self.mos(out,b,self.zero,self.zero,w=.8)
        self.mos(out,a,n,self.one,True,w=4.8);self.mos(n,b,self.one,self.one,True,w=4.8)
        self.cells['NOR2']+=1;return out

    def AND(self,*values):
        vals=list(dict.fromkeys(values))
        if self.zero in vals:return self.zero
        vals=[v for v in vals if v!=self.one]
        if not vals:return self.one
        if len(vals)==1:return vals[0]
        while len(vals)>1:
            vals=[self.inv(self.nand(vals[i],vals[i+1])) if i+1<len(vals) else vals[i] for i in range(0,len(vals),2)]
        return vals[0]

    def OR(self,*values):
        vals=list(dict.fromkeys(values))
        if self.one in vals:return self.one
        vals=[v for v in vals if v!=self.zero]
        if not vals:return self.zero
        if len(vals)==1:return vals[0]
        while len(vals)>1:
            vals=[self.inv(self.nor(vals[i],vals[i+1])) if i+1<len(vals) else vals[i] for i in range(0,len(vals),2)]
        return vals[0]

    def xor(self,a,b):
        if a==b:return self.zero
        if a==self.zero:return b
        if b==self.zero:return a
        if a==self.one:return self.inv(b)
        if b==self.one:return self.inv(a)
        a,b=sorted((a,b));key=('xor',a,b)
        if key in self.cache:return self.cache[key]
        n=self.nand(a,b);out=self.nand(self.nand(a,n),self.nand(b,n));self.cache[key]=out;return out

    def mux(self,sel,one,zero):
        if one==zero:return one
        if sel==self.one:return one
        if sel==self.zero:return zero
        key=('mux',sel,one,zero)
        if key in self.cache:return self.cache[key]
        out=self.nand(self.nand(sel,one),self.nand(self.inv(sel),zero));self.cache[key]=out;return out

    def buffer(self,a,out=None,repeat=1):
        for _ in range(repeat):a=self.inv(self.inv(a))
        if out is not None:
            # Dedicated buffers provide physical ports rather than ideal aliases.
            a=self.inv(a);self.inv(a,out=out);return out
        return a

    def delay_buffer(self,a,stages=16):
        # Deliberately unshared physical inverter chain; an engineering reset
        # release guard, not an ideal delay or a validated timing guarantee.
        if stages%2:raise ValueError('non-inverting chain requires even count')
        for _ in range(stages):
            n=self.node('delay');self.inv(a,out=n);a=n
        return a

    def tg(self,a,b,en,enb):
        self.mos(a,en,b,self.zero,w=1.2);self.mos(a,enb,b,self.one,True,w=3.6);self.cells['TG']+=1

    def latch(self,d,op,opb,hold,holdb,rst,q,qb):
        storage=self.node('storage');self.tg(d,storage,op,opb);self.tg(q,storage,hold,holdb)
        self.mos(qb,storage,self.zero,self.zero,w=.5);self.mos(qb,storage,self.one,self.one,True,w=1.5)
        self.mos(q,qb,self.zero,self.zero,w=.5);self.mos(q,qb,self.one,self.one,True,w=1.5)
        self.mos(storage,rst,self.zero,self.zero,w=2);self.cells['LATCH']+=1

    def dff(self,d,clk,rst,q,preset=0):
        self.dffs+=1;self.flop_nodes.append(q)
        clkb=self.inv(clk);rstb=self.inv(rst)
        low=self.AND(clkb,rstb);high=self.AND(clk,rstb)
        lowb=self.inv(low);highb=self.inv(high)
        qm=self.node('qm');qmb=self.node('qmb')
        if preset:
            d=self.inv(d);pq=self.node('qneg');pqb=q
        else:pq=q;pqb=self.node('qb')
        self.latch(d,low,lowb,high,highb,rst,qm,qmb)
        self.latch(qm,high,highb,low,lowb,rst,pq,pqb)

    def register(self,d,clk,rst,q,en=None,preset=0):
        if en is not None:d=self.mux(en,d,q)
        self.dff(d,clk,rst,q,preset=preset);return q

    def decode_gray(self,gray,prefix=None):
        result=[None]*len(gray);result[-1]=gray[-1]
        for i in range(len(gray)-2,-1,-1):result[i]=self.xor(result[i+1],gray[i])
        if prefix:
            for i,node in enumerate(result):self.buffer(node,out=prefix+str(i))
            result=[prefix+str(i) for i in range(len(gray))]
        return result

    def gray_counter(self,clk,rst,prefix,initial=0,bits=8):
        gray=[prefix+'g'+str(i) for i in range(bits)]
        binary=self.decode_gray(gray)
        carry=self.one;nextb=[]
        for q in binary:nextb.append(self.xor(q,carry));carry=self.AND(q,carry)
        nextg=[self.xor(nextb[i],nextb[i+1]) if i+1<bits else nextb[i] for i in range(bits)]
        initgray=initial^(initial>>1)
        for i,d in enumerate(nextg):self.dff(d,clk,rst,gray[i],preset=(initgray>>i)&1)
        return gray

    def sync_gray(self,word,clk,rst,prefix):
        result=[]
        for i,d in enumerate(word):
            q1=prefix+'sync1_'+str(i);q2=prefix+'sync2_'+str(i)
            self.dff(d,clk,rst,q1);self.dff(q1,clk,rst,q2);result.append(q2)
        return result

    def ge_difference2(self,a,b):
        # Unsigned a-b, carry=no borrow, positive magnitude >=2.
        carry=self.one;diff=[]
        for x,y in zip(a,b):
            ny=self.inv(y);xy=self.xor(x,ny);diff.append(self.xor(xy,carry))
            carry=self.OR(self.AND(x,ny),self.AND(xy,carry))
        return self.AND(carry,self.OR(*diff[1:]))

    def binary_counter(self,clk,rst,prefix,bits=3,en=None):
        q=[prefix+str(i) for i in range(bits)];carry=self.one
        for qi in q:
            d=self.xor(qi,carry);carry=self.AND(qi,carry)
            self.register(d,clk,rst,qi,en=en)
        return q


def build():
    c=Circuit();o=c.one;z=c.zero
    # Controller clocks continue for two clocks after DONE, then stop. FAIL
    # stops clocks immediately. Testbench reset must be asserted to restart.
    run=c.inv(c.OR('fine_enable','fail'));ctrlclk=c.AND('ref',run)
    c.buffer(ctrlclk,out='control_clock')
    started='started';settle='settle';arm='arm';measure='measure';drain='drain'
    launch=c.AND('start',c.inv(started),c.inv('done'),c.inv('fail'))
    c.register(o,ctrlclk,'rst',started,en=launch)
    current=c.OR(settle,arm,measure,drain)
    c.buffer(c.AND(started,c.inv(c.OR('done','fail'))),out='active')

    # The first raw FB edge during ARM captures the current master phase.
    # A held state flop avoids the asynchronous clear pulse that a simple
    # OR(arm,measure) could produce while one state turns off and the other
    # turns on through unequal physical gate delays.
    count_run='count_run'
    count_rst=c.OR('rst',c.inv(count_run));c.buffer(count_rst,out='count_rst')
    c.dff(o,'fb',count_rst,'seen')
    c.register('ref','fb',count_rst,'phase',en=c.inv('seen'))
    seen_delayed=c.delay_buffer('seen',16)
    c.buffer(c.OR(count_rst,c.inv(seen_delayed)),out='reference_count_rst')
    refb=c.inv('ref')
    leadclk=c.mux('phase','ref',refb);lagclk=c.mux('phase',refb,'ref')
    c.buffer(leadclk,out='lead_clock');c.buffer(lagclk,out='lag_clock')
    leadclk=c.AND(leadclk,count_run);lagclk=c.AND(lagclk,count_run)
    # Only first DIV edge increments native Div 0->1; leading phase was
    # already high at that instant and gets exactly one initial credit.
    lead=c.gray_counter(leadclk,'reference_count_rst','lead_',initial=1)
    lag=c.gray_counter(lagclk,'reference_count_rst','lag_',initial=0)
    div=c.gray_counter('fb',count_rst,'div_',initial=0)
    pipe_rst=c.OR('rst',c.inv(count_run))
    sl=c.sync_gray(lead,ctrlclk,pipe_rst,'lead_');sg=c.sync_gray(lag,ctrlclk,pipe_rst,'lag_');sd=c.sync_gray(div,ctrlclk,pipe_rst,'div_')
    cl=c.decode_gray(sl,'cl');cg=c.decode_gray(sg,'cg');cd=c.decode_gray(sd,'cd')
    c.dff('seen',ctrlclk,pipe_rst,'seen_sync1');c.dff('seen_sync1',ctrlclk,pipe_rst,'seen_sync2')
    # Explicit settling mask after first-edge acknowledgement; two more
    # REF cycles allow all three matched pipelines to become established.
    c.dff('seen_sync2',ctrlclk,pipe_rst,'epoch_valid1');c.dff('epoch_valid1',ctrlclk,pipe_rst,'epoch_valid')
    slow=c.ge_difference2(cg,cd);fast=c.ge_difference2(cd,cl)
    c.buffer(slow,out='slow_raw');c.buffer(fast,out='fast_raw')
    direction_rst=c.OR('rst',c.inv(measure))
    c.dff(slow,ctrlclk,direction_rst,'slow_prev');c.dff(fast,ctrlclk,direction_rst,'fast_prev')
    slowq=c.AND(slow,'slow_prev');fastq=c.AND(fast,'fast_prev')
    c.buffer(slowq,out='slow_qualified');c.buffer(fastq,out='fast_qualified')
    window=cg[7]
    conflict=c.AND(slowq,fastq)
    valid=c.AND(measure,c.OR(slowq,fastq,window))
    c.buffer(valid,out='decision')
    c.register(fastq,ctrlclk,'rst','was_fast',en=valid)
    c.register(slowq,ctrlclk,'rst','was_slow',en=valid)
    c.register(c.AND(window,c.inv(c.OR(slowq,fastq))),ctrlclk,'rst','was_near',en=valid)
    for prefix,word in [('dl',cl),('dg',cg),('dd',cd)]:
        for i,d in enumerate(word):c.register(d,ctrlclk,'rst',prefix+str(i),en=valid)

    # Four settling master clocks; counters reset throughout SETTLE.
    st=c.binary_counter(ctrlclk,c.OR('rst',c.inv(settle)),'settletick',bits=3)
    settle_finish=c.AND(settle,st[0],st[1],c.inv(st[2]))
    at=c.binary_counter(ctrlclk,c.OR('rst',c.inv(arm)),'armtick',bits=6)
    arm_finish=c.AND(arm,'epoch_valid')
    arm_timeout=c.AND(arm,at[5],c.inv('epoch_valid'))
    dt=c.binary_counter(ctrlclk,c.OR('rst',c.inv(drain)),'draintick',bits=2)
    drain_finish=c.AND(drain,dt[0])
    mt=c.binary_counter(ctrlclk,c.OR('rst',c.inv(measure)),'measuretick',bits=8)
    measure_timeout=c.AND(measure,mt[7],mt[6])
    c.buffer(measure_timeout,out='measure_watchdog')
    steps=['step1','step2','step4','step8'];last=c.inv(c.OR(*steps))
    code=['s'+str(i) for i in range(5)]
    code1=c.AND(code[0],*[c.inv(n) for n in code[1:]])
    code31=c.AND(*code)
    endpoint=c.OR(c.AND(code1,'was_fast'),c.AND(code31,'was_slow'))
    terminal=c.OR('was_near',last)
    complete=c.AND(drain_finish,terminal,c.inv(endpoint))
    fail_event=c.OR(arm_timeout,measure_timeout,c.AND(measure,conflict),c.AND(drain_finish,terminal,endpoint))
    c.register(c.inv(c.OR(valid,fail_event)),ctrlclk,'rst',count_run,en=c.OR(settle_finish,valid,fail_event))
    c.register(o,ctrlclk,'rst','done',en=complete)
    c.register(o,ctrlclk,'rst','fail',en=fail_event)
    advance=c.AND(drain_finish,c.inv(terminal))

    # Candidate sequence16+/-8+/-4+/-2+/-1. Fifth candidate has actually been
    # counted before handover; unlike a raw SAR there is no untested sixth.
    for i,qi in enumerate(code):
        fastcarry=[];slowcarry=[]
        for k,step in enumerate(steps):
            if k>i:continue
            fastcarry.append(c.AND(step,*[c.inv(code[j]) for j in range(k,i)]))
            slowcarry.append(c.AND(step,*code[k:i]))
        toggle=c.mux('was_fast',c.OR(*fastcarry),c.OR(*slowcarry))
        c.register(c.xor(qi,toggle),ctrlclk,'rst',qi,en=advance,preset=int(i==4))
    for i,qi in enumerate(steps):
        d=steps[i+1] if i+1<len(steps) else z
        c.register(d,ctrlclk,'rst',qi,en=advance,preset=int(i==3))

    c.dff(c.OR(launch,advance,c.AND(settle,c.inv(settle_finish))),ctrlclk,'rst',settle)
    c.dff(c.OR(settle_finish,c.AND(arm,c.inv(c.OR(arm_finish,arm_timeout)))),ctrlclk,'rst',arm)
    c.dff(c.OR(arm_finish,c.AND(measure,c.inv(c.OR(valid,fail_event)))),ctrlclk,'rst',measure)
    c.dff(c.OR(valid,c.AND(drain,c.inv(drain_finish))),ctrlclk,'rst',drain)
    # DONE holds code; filter clamp and CP/PFD release only after two REF
    # clocks. A failed calibration keeps CP disabled and clamp asserted.
    c.dff('done',ctrlclk,'rst','done_delay1')
    c.dff(c.AND('done_delay1',c.inv('fail')),ctrlclk,'rst','fine_enable')
    c.buffer(c.inv('fine_enable'),out='hold')
    c.buffer(c.OR('rst',c.inv('fine_enable')),out='pfd_reset')
    return c


def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--out-dir',default=str(Path(__file__).resolve().parent));args=parser.parse_args()
    out=Path(args.out_dir);out.mkdir(parents=True,exist_ok=True)
    manifest=json.loads((out/'port_manifest.json').read_text(encoding='utf-8'))
    c=build();ports=' '.join(manifest['port_order'])
    header=('// GENERATED transistor-only static-CMOS AFC: Jeong2009-inspired first-edge phase bracket.\n'
            '// NEW130nm implementation; source design unverified until electrical units pass.\n'
            '// All state physical TG DFFs, all compare/control staticMOS gates, no VA.\n'
            '// REF100MHz, FB=VCO/32, positive frequency/code polarity; vdd=1.2V.\n'
            '// VDD/VSS body rails; n12/p12 ordinary tt models required in top-level.\n'
            '// Phase selector reset-release16physicalINV guard is not timing-signoff.\n'
            'simulator lang=spectre\nsubckt afc2009_mos ({})\n'.format(ports))
    text=header+'\n'.join(c.lines)+'\nends afc2009_mos\n'
    path=out/'afc2009_mos.scs';path.write_text(text,encoding='utf-8')
    manifest['source_sha256']=hashlib.sha256(path.read_bytes()).hexdigest();manifest['transistor_count']=c.transistors
    manifest['DFF_count']=c.dffs;manifest['primitive_counts']=dict(c.cells)
    manifest['flattened_MOS']=True;manifest['active_models']=['n12','p12'];manifest['model_files_distributed']=False
    manifest['geometry_um']={'logic_inv':{'WN':.8,'WP':2.4,'L':.13},'nand2':{'WN_each':1.6,'WP_each':2.4,'L':.13},'nor2':{'WN_each':.8,'WP_each':4.8,'L':.13},'TG':{'WN':1.2,'WP':3.6,'L':.13},'latch_inverter':{'WN':.5,'WP':1.5,'L':.13},'latch_reset':{'WN':2,'L':.13}}
    manifest['source_design_status']='generated_transistor_netlist_not_yet_electrically_validated'
    manifest['diagnostic_hierarchy']['epoch_valid']='epoch_valid'
    manifest['diagnostic_hierarchy']['lead_clock']='lead_clock';manifest['diagnostic_hierarchy']['lag_clock']='lag_clock'
    manifest['diagnostic_hierarchy']['controller_clock']='control_clock'
    manifest['diagnostic_hierarchy']['measure_watchdog']='measure_watchdog'
    manifest['measure_watchdog_REF_clocks']=192
    manifest['counter_overflow_guard']='No general hardware overflow detector; within planned VCO/32 range<=113MHz the192REFwatchdog occurs before8bit wrap. Outside that planned range, counteroverflow safety is unverified.'
    (out/'port_manifest.json').write_text(json.dumps(manifest,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    (out/'state_nodes.json').write_text(json.dumps(c.flop_nodes,indent=2)+'\n',encoding='utf-8')
    print(json.dumps({'path':str(path),'sha256':manifest['source_sha256'],'transistors':c.transistors,'DFFs':c.dffs,'primitive_counts':dict(c.cells)},indent=2))


if __name__=='__main__':main()
