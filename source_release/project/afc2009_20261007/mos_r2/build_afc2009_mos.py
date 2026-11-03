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
        self.clock_delays={};self.clock_groups={};self.logic_ops=[];self.flop_records=[]

    def node(self,prefix='n'):
        self.seq+=1;return '{}{}'.format(prefix,self.seq)

    def mos(self,d,g,s,bulk,pmos=False,w=.8,l=.13):
        name=self.node('MP' if pmos else 'MN');model='p12' if pmos else 'n12'
        self.lines.append('{} ({} {} {} {}) {} w={}u l={}u'.format(name,d,g,s,bulk,model,w,l));self.transistors+=1

    def inv(self,a,out=None,wn=.8,wp=2.4):
        if out is None:
            if a==self.zero:return self.one
            if a==self.one:return self.zero
            key=('inv',a)
            if key in self.cache:return self.cache[key]
            out=self.node();self.cache[key]=out
        self.mos(out,a,self.zero,self.zero,w=wn)
        self.mos(out,a,self.one,self.one,True,w=wp);self.cells['INV']+=1
        self.logic_ops.append(('INV',out,a));return out

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
        self.cells['NAND2']+=1;self.logic_ops.append(('NAND',out,a,b));return out

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
        self.cells['NOR2']+=1;self.logic_ops.append(('NOR',out,a,b));return out

    def nand4(self,a,b,d,e,out=None):
        if out is None:out=self.node()
        nodes=[out,self.node(),self.node(),self.node(),self.zero]
        for i,g in enumerate((a,b,d,e)):
            self.mos(nodes[i],g,nodes[i+1],self.zero,w=3.2)
            self.mos(out,g,self.one,self.one,True,w=2.4)
        self.cells['NAND4']+=1;self.logic_ops.append(('NAND',out,a,b,d,e));return out

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
        self.flop_records.append({'d':d,'clk':clk,'rst':rst,'q':q,'preset':preset})
        low,lowb,high,highb=self.clock_controls(clk,rst)
        qm=self.node('qm');qmb=self.node('qmb')
        if preset:
            d=self.inv(d);pq=self.node('qneg');pqb=q
        else:pq=q;pqb=self.node('qb')
        self.latch(d,low,lowb,high,highb,rst,qm,qmb)
        self.latch(qm,high,highb,low,lowb,rst,pq,pqb)

    def clock_controls(self,clk,rst):
        key=(clk,rst)
        if key in self.clock_groups:return self.clock_groups[key]
        if clk not in self.clock_delays:self.clock_delays[clk]=self.delay_buffer(clk,6)
        delayed=self.clock_delays[clk];clkb=self.inv(clk);delayedb=self.inv(delayed);rstb=self.inv(rst)
        low=self.node('clk_low');lowb=self.node('clk_lowb');high=self.node('clk_high');highb=self.node('clk_highb')
        # R1: physical mutual interlock, plus delayed-CLK guard. Master closes
        # before the slave opens; on the falling edge slave closes before
        # master opens. 8/24um final buffers drive shared TG clock loads.
        ln=self.nand4(clkb,delayedb,highb,rstb)
        hn=self.nand4(clk,delayed,lowb,rstb)
        self.inv(ln,out=low,wn=8,wp=24);self.inv(low,out=lowb,wn=8,wp=24)
        self.inv(hn,out=high,wn=8,wp=24);self.inv(high,out=highb,wn=8,wp=24)
        result=(low,lowb,high,highb);self.clock_groups[key]=result;return result

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
    count_rst='count_rst'
    # R1 counter reset is held through SETTLE, released for ARM/MEASURE,
    # and remains released for the two DRAIN clocks after the snapshot.
    # Glitch-free FB clock gate: count_run is latched only while raw FB low.
    flo,flob,fhi,fhib=c.clock_controls('fb','rst')
    c.latch(count_run,flo,flob,fhi,fhib,'rst','fb_clock_enable','fb_clock_enableb')
    gatedfb=c.AND('fb','fb_clock_enable');c.buffer(gatedfb,out='counter_fb_clock')
    c.dff(o,gatedfb,count_rst,'seen')
    c.register('ref',gatedfb,count_rst,'phase',en=c.inv('seen'))
    seen_delayed=c.delay_buffer('seen',16)
    c.buffer(c.OR(count_rst,c.inv(seen_delayed)),out='reference_count_rst')
    refb=c.inv('ref')
    leadclk=c.mux('phase','ref',refb);lagclk=c.mux('phase',refb,'ref')
    c.buffer(leadclk,out='lead_clock');c.buffer(lagclk,out='lag_clock')
    leadclk=c.AND(leadclk,count_run);lagclk=c.AND(lagclk,count_run)
    # Only first DIV edge increments native Div 0->1; leading phase was
    # already high at that instant and gets exactly one initial credit.
    lead=c.gray_counter(leadclk,'reference_count_rst','lead_',initial=1,bits=9)
    lag=c.gray_counter(lagclk,'reference_count_rst','lag_',initial=0,bits=9)
    div=c.gray_counter(gatedfb,count_rst,'div_',initial=0,bits=9)
    pipe_rst=count_rst
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
    # R2: unsigned9bit C_lag>=224. cg8 handles values>=256 safely.
    window=c.OR(cg[8],c.AND(cg[7],cg[6],cg[5]))
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
    # R2: global counter-epoch age starts at held count_rst release, across
    # ARM and MEASURE. A dedicated reset alias keeps this clock group off
    # the large CDC clock-control group. DRAIN has frozen native counters,
    # so a late age during DRAIN must not turn a valid candidate into FAIL.
    age_rst=c.buffer(count_rst,out='counter_age_reset')
    age=c.binary_counter(ctrlclk,age_rst,'counterage',bits=8)
    age_limit=c.AND(age[7],age[6],age[5],age[4],age[3])
    epoch_timeout=c.AND(count_run,c.OR(arm,measure),c.inv(count_rst),c.inv(c.OR('done','fail')),age_limit)
    c.buffer(epoch_timeout,out='epoch_watchdog')
    c.buffer(epoch_timeout,out='measure_watchdog')
    steps=['step1','step2','step4','step8'];last=c.inv(c.OR(*steps))
    code=['s'+str(i) for i in range(5)]
    code1=c.AND(code[0],*[c.inv(n) for n in code[1:]])
    code31=c.AND(*code)
    endpoint=c.OR(c.AND(code1,'was_fast'),c.AND(code31,'was_slow'))
    terminal=c.OR('was_near',last)
    fail_event=c.OR(arm_timeout,epoch_timeout,c.AND(measure,conflict),c.AND(drain_finish,terminal,endpoint))
    complete=c.AND(drain_finish,terminal,c.inv(endpoint),c.inv(fail_event))
    c.register(c.inv(c.OR(valid,fail_event)),ctrlclk,'rst',count_run,en=c.OR(settle_finish,valid,fail_event))
    c.register(o,ctrlclk,'rst','done',en=complete)
    c.register(o,ctrlclk,'rst','fail',en=fail_event)
    advance=c.AND(drain_finish,c.inv(terminal),c.inv(fail_event))
    resetcounts=c.OR(launch,advance,complete,fail_event)
    c.register(c.inv(settle_finish),ctrlclk,'rst',count_rst,en=c.OR(settle_finish,resetcounts),preset=1)

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

    # R2 global-age FAIL has priority over every state entry, candidate
    # advance and DONE. It cannot produce both done=1/fail=1 at thedeadline.
    nofault=c.inv(fail_event)
    c.dff(c.AND(nofault,c.OR(launch,advance,c.AND(settle,c.inv(settle_finish)))),ctrlclk,'rst',settle)
    c.dff(c.AND(nofault,c.OR(settle_finish,c.AND(arm,c.inv(c.OR(arm_finish,arm_timeout))))),ctrlclk,'rst',arm)
    c.dff(c.AND(nofault,c.OR(arm_finish,c.AND(measure,c.inv(c.OR(valid,fail_event))))),ctrlclk,'rst',measure)
    c.dff(c.AND(nofault,c.OR(valid,c.AND(drain,c.inv(drain_finish)))),ctrlclk,'rst',drain)
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
            '// R2 OFFLINE PREPARED:9bitnativeGray/CDC/snapshots,lag224/globalepochage248.\n'
            '// RetainsR1 non-overlap interlocked clock controls and frozen-DRAIN counters.\n'
            '// NOT the selectedphysicalimplementation; electricallyunverified.\n'
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
    manifest['geometry_um']['clock_control_output_inv']={'WN':8,'WP':24,'L':.13}
    manifest['geometry_um']['clock_control_NAND4']={'WN_each':3.2,'WP_each':2.4,'L':.13}
    manifest['source_design_status']='prepared_unverified_offline_candidate_not_selected'
    manifest['version']='1.2-R2-prepared-unverified'
    manifest['revises_R0_source_sha256']='4b0874902106b01e21f2498b28336dcd5f01bfa88c8de0f41f57354bbd761dde'
    manifest['R1_changes']=['All TG DFFs use mutual-interlocked low/high phases plus6physicalINVclockdelay guard.','8um n/24um p clock-control output buffers drive shared TG loading.','Counter resetheldstate persists through2REFDRAIN so frozendecisiondata is not cleared oncaptureedge.','FB clock enable low-level latched; blocksstart ghostedge andstopsnativeFB-clockedlogic aftertrial.','Source literalgate/idealDFFfunctionalmodel supplied; stillnot physicaltiming/CDCproof.']
    manifest['revises_R1_source_sha256']='12044e0dc052c06682a3372f17c0b8612d637954af88e0d8662cf1d8c0f8f6b8'
    manifest['R2_changes']=['All three native Gray counters, CDC pipelines and frozen decision words widened from 8 to 9 bits.','NEAR deadline uses unsigned C_lag >= 224.','Global 248 REF counter age starts at held count_rst release; watchdog covers active counting across ARM and MEASURE. DRAIN is frozen and cannot trip this watchdog.','Independent 32 REF ARM timeout retained.','Global epoch-age FAIL has priority over DONE, advance and every state entry; watchdog disabled after terminal state.','No changes to two-phase sign, 2-count guard, two observations, five tested codes, 17 ports, physical interlock with 6 INV, or low-phase FB gate.']
    manifest['counter_bits']=9
    manifest['window_lag_counts']=224
    manifest['counter_epoch_watchdog_REF_clocks']=248
    manifest.pop('measure_watchdog_REF_clocks',None)
    for key,prefix in [('counts_lead','cl'),('counts_lag','cg'),('counts_div','cd'),('decision_lead','dl'),('decision_lag','dg'),('decision_div','dd')]:
        manifest['diagnostic_hierarchy'][key]=[prefix+str(i) for i in range(9)]
    for word in ('lead','lag','div'):
        manifest['diagnostic_hierarchy']['native_'+word+'_Gray']=[word+'_g'+str(i) for i in range(9)]
        manifest['diagnostic_hierarchy']['sync2_'+word+'_Gray']=[word+'_sync2_'+str(i) for i in range(9)]
    manifest['diagnostic_hierarchy']['epoch_valid']='epoch_valid'
    manifest['diagnostic_hierarchy']['lead_clock']='lead_clock';manifest['diagnostic_hierarchy']['lag_clock']='lag_clock'
    manifest['diagnostic_hierarchy']['controller_clock']='control_clock'
    manifest['diagnostic_hierarchy']['measure_watchdog']='measure_watchdog'
    manifest['diagnostic_hierarchy']['counter_FB_clock']='counter_fb_clock'
    manifest['diagnostic_hierarchy']['counter_FB_clock_enable']='fb_clock_enable'
    primary=next(r for r in c.flop_records if r['q']=='started')
    primarycontrols=c.clock_groups[(primary['clk'],primary['rst'])]
    for name,node in zip(('controller_master_open','controller_master_openb','controller_slave_open','controller_slave_openb'),primarycontrols):
        manifest['diagnostic_hierarchy'][name]=node
    manifest['clock_nonoverlap_groups']=[{'clock':clock,'reset':reset,'master_open':v[0],'master_openb':v[1],'slave_open':v[2],'slave_openb':v[3]} for (clock,reset),v in c.clock_groups.items()]
    manifest['clock_control_formula']={'delayed_clock':'6physicalinverters noninverting CLKd','master_open':'!CLK & !CLKd & slave_openb & !RST','slave_open':'CLK & CLKd & master_openb & !RST','complements':'dedicated8/24um inverters','limits':'Mutual interlock and physicaldelay guard; actual deadtime and race-through still require transient/PVT measurement.'}
    manifest['diagnostic_hierarchy']['epoch_watchdog']='epoch_watchdog'
    manifest['diagnostic_hierarchy']['counter_epoch_age']=['counterage'+str(i) for i in range(8)]
    manifest['diagnostic_hierarchy']['counter_age_reset']='counter_age_reset'
    manifest['counter_epoch_watchdog_scope']='count_run & (arm | measure) & !count_rst & !(done | fail) & age >= 248; age begins at count_rst release. Native counters are frozen in DRAIN, so DRAIN age cannot assert FAIL.'
    manifest['counter_overflow_guard']='No general-purpose overflow detector. Conditional bound: fb <= 113 MHz, REF = 100 MHz and at most 3 REF cycles after age 248 until native freeze gives at most 1 + floor(1.13 * 251) = 284 edges, below 512. Arbitrary higher frequency, CDC, metastability, edge credits and PVT remain electrically unverified.'
    (out/'port_manifest.json').write_text(json.dumps(manifest,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    (out/'state_nodes.json').write_text(json.dumps(c.flop_nodes,indent=2)+'\n',encoding='utf-8')
    (out/'logical_gate_records.json').write_text(json.dumps({'gates':c.logic_ops,'flops':c.flop_records,'assumption':'Flops model ideal positive-edge capture and asyncpreset; nativephase/CDCelectricaltimingisnotmodeled.'},indent=2)+'\n',encoding='utf-8')
    print(json.dumps({'path':str(path),'sha256':manifest['source_sha256'],'transistors':c.transistors,'DFFs':c.dffs,'primitive_counts':dict(c.cells)},indent=2))


if __name__=='__main__':main()
