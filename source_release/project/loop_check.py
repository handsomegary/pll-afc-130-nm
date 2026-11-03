import numpy as np
C1,C2,C3=10e-15,3e-12,50e-15
R2,R3=140e3,280e3
f=np.logspace(3,9,200000)
s=2j*np.pi*f
Z=(1+R2*C2*s)/(R2*R3*C1*C2*C3*s**3+(R2*C1*C2+R2*C2*C3+R3*C2*C3+R3*C1*C3)*s**2+(C1+C2+C3)*s)
for kv in [250e6,55e6,417e6]:
    for label,mul in [('Hz/V corrected',1),('Hz/V with extra 2pi denominator',1/(2*np.pi))]:
        L=10e-6*kv/32*Z/s*mul
        k=int(np.argmin(abs(abs(L)-1)))
        H=L/(1+L)
        h=int(np.argmin(abs(abs(H)-1/np.sqrt(2))))
        pm=180+np.angle(L[k],deg=True)
        print(f'KVCO {kv/1e6:g}MHz/V {label}: unity gain {f[k]/1e6:.5f}MHz PM {pm:.3f}deg closedloop3dB {f[h]/1e6:.5f}MHz')
for power in [11.4,25]:
    print('conditional FOMj only, no physical noise verification:',power,10*np.log10((37.3e-15)**2*power))
print('TuningRangePctTT=',100*2*(5.6-2.3)/(5.6+2.3))
