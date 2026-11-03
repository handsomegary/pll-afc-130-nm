"""Authored vector schematics for teaching, stdlib only. No simulation."""
from pathlib import Path
import html


def label(x,y,s,size=16,anchor='start'):
    return '<text x="{}" y="{}" font-size="{}" text-anchor="{}">{}</text>'.format(x,y,size,anchor,html.escape(s))


def wire(x1,y1,x2,y2):
    return '<line x1="{}" y1="{}" x2="{}" y2="{}"/>'.format(x1,y1,x2,y2)


def node(x,y):
    return '<circle cx="{}" cy="{}" r="4" fill="#263238"/>'.format(x,y)


def mos(x,y,p=False,name=''):
    # Source/drain on the right channel; gate on the left, conventional p bubble.
    s=wire(x,y-45,x,y-22)+wire(x,y+22,x,y+45)
    s+=wire(x,y-22,x,y+22)+wire(x-18,y-20,x-18,y+20)
    s+=wire(x-65,y,x-18,y)
    if p:
        s+='<circle cx="{}" cy="{}" r="5" fill="white"/>'.format(x-28,y)
    s+=label(x+14,y+5,name,15)
    return s


def save(name,content,w=1000,h=700):
    style='<style>text{font-family:Arial,sans-serif;fill:#263238}line,path,rect,circle{stroke:#263238;stroke-width:2;fill:none}.title{font-weight:bold}</style>'
    svg='<svg xmlns="http://www.w3.org/2000/svg" width="{}" height="{}" viewBox="0 0 {} {}"><rect width="100%" height="100%" fill="white" stroke="none"/>{}{}</svg>'.format(w,h,w,h,style,content)
    (Path(__file__).resolve().parent/name).write_text(svg,encoding='utf-8')


def cp():
    s=label(45,40,'Authored 1.2 V gate-switched charge pump candidate',23)
    s+=label(45,65,'Physical n12/p12 MOS; ideal reference current; no matching op-amp',16)
    s+=wire(70,105,895,105)+label(70,96,'VDD = 1.2 V')
    s+=wire(70,575,895,575)+label(70,603,'VSS; NMOS bodies to VSS, PMOS bodies to VDD')
    # NMOS reference diode and ideal current supply.
    s+=wire(115,105,115,145)+'<circle cx="115" cy="175" r="30"/>'
    s+=wire(115,153,115,195)+'<path d="M108 185 L115 195 L122 185"/>'
    s+=wire(115,205,115,315)+label(45,228,'IREF = 20 uA')
    s+=mos(115,440,False,'MNREF')+wire(115,315,115,395)+wire(115,485,115,575)
    s+=wire(115,315,50,315)+wire(50,315,50,440)+node(115,315)
    s+=label(70,299,'BN_CP',15)
    # Matching mirror reference branch.
    s+=mos(275,195,True,'MPREF')+wire(275,105,275,150)
    s+=wire(275,240,275,395)+mos(275,440,False,'MNPMIRROR')+wire(275,485,275,575)
    s+=wire(275,300,210,300)+wire(210,195,210,300)+node(275,300)
    s+=wire(50,355,210,355)+wire(210,355,210,440)+wire(50,315,50,355)
    s+=label(293,291,'BP_CP',15)
    # Gate mux boxes. Boxes explicitly describe authored transistor TG mux.
    s+='<rect x="420" y="165" width="185" height="100" rx="8"/>'
    s+=label(432,186,'Complementary TG mux',14)+label(432,211,'UP=1: BP_CP',14)+label(432,237,'UP=0: VDD',14)
    s+=wire(275,300,385,300)+wire(385,215,385,300)+wire(385,215,420,215)
    s+=wire(605,195,695,195)+label(625,182,'GP')
    s+=mos(760,195,True,'MPUP')+wire(760,105,760,150)
    s+=wire(760,240,760,350)+node(760,350)+wire(760,350,940,350)+label(825,337,'Vctrl / LPF')
    s+='<rect x="420" y="390" width="185" height="100" rx="8"/>'
    s+=label(432,411,'Complementary TG mux',14)+label(432,436,'DN=1: BN_CP',14)+label(432,462,'DN=0: VSS',14)
    s+=wire(115,315,355,315)+wire(355,315,355,440)+wire(355,440,420,440)
    s+=wire(605,440,695,440)+label(625,427,'GN')
    s+=mos(760,440,False,'MNDN')+wire(760,350,760,395)+wire(760,485,760,575)
    s+=label(435,295,'UP injects current into Vctrl',15)+label(435,520,'DN sinks current from Vctrl',15)
    s+=label(45,642,'Current mirrors: NMOS 4/1.04 um; PMOS 12/1.04 um.  TG N/P: 0.5/0.13, 1.5/0.13 um.',15)
    s+=label(45,668,'This diagram corresponds to pll130_cp_transistor.scs, not paper Fig.4.',15)
    save('cp_candidate_schematic.svg',s)


def lpf():
    s=label(45,45,'Authored passive PLL filter and loop definition',23)
    s+=label(45,77,'Calculated nominal: Icp=20 uA, Kvco=423 MHz/V, N=32; no PEX',17)
    s+=wire(80,180,730,180)+node(190,180)+label(80,160,'CP output / Vctrl')
    # Cshunt, parallel branch.
    s+=wire(190,180,190,265)+wire(145,265,235,265)+wire(145,283,235,283)
    s+=wire(190,283,190,425)+label(45,325,'Cshunt = 0.3384 pF')
    # Resistor in the series branch, drawn horizontal.
    s+=wire(350,180,350,265)+'<rect x="335" y="265" width="30" height="100"/>'
    s+=wire(350,365,350,395)+node(350,395)+label(387,325,'R = 49.501 kohm')
    s+=wire(350,395,350,465)+wire(305,465,395,465)+wire(305,483,395,483)
    s+=wire(350,483,350,550)+label(430,485,'Cseries = 6.4303 pF')
    s+=wire(80,550,700,550)+wire(190,425,190,550)+label(80,580,'VSS')
    s+=label(387,409,'filter_mid')
    s+=label(680,166,'To VCO fine input')+wire(730,180,770,180)
    s+=label(45,620,'fz = 500 kHz; fp = 10 MHz; analytic unity gain = 2 MHz; phase margin = 64.65 deg',17)
    s+=label(45,654,'Continuous-time small-signal estimate. MOS/PFD delays and sampled nonlinear lock require transient verification.',15)
    save('lpf_candidate_schematic.svg',s)


if __name__=='__main__':
    cp();lpf()
