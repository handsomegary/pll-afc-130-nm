import csv
import json
import math
from pathlib import Path
import re
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt

root=Path(__file__).resolve().parent.parent
work=root/'work'
out=root/'outputs'
out.mkdir(exist_ok=True)

def noise_points(path):
    result=[]
    for line in path.read_text(encoding='utf-8-sig').splitlines():
        m=re.match(r'\s*([\d.eE+-]+)\s+([\d.eE+-]+)\s*$',line)
        if m: result.append(tuple(map(float,m.groups())))
    return result

baseline=noise_points(work/'final_pn_ssb.txt')
tg=noise_points(work/'tg_pn_ssb.txt') if (work/'tg_pn_ssb.txt').exists() else []
corners=json.loads((work/('tg_final_corners.json' if (work/'tg_final_corners.json').exists() else 'final_cases.json')).read_text(encoding='utf-8-sig'))
fig,axes=plt.subplots(1,2,figsize=(11.5,4.7))
fig.suptitle('cmos130 VCO: first 3.2 GHz migration',fontsize=16,fontweight='bold',y=.985)
fig.text(.5,.905,'1.2 V, 25 C | VCO + bias + static control | Pre-layout simulation',ha='center',fontsize=10,color='#526077')
colors={'tt':'#2563eb','ss':'#d97706','ff':'#16a34a'}
for corner in ['tt','ss','ff']:
    points=[p for p in corners if p['corner']==corner and p['code'] in [0,16,31] and p.get('vctrl_V')==.6]
    points=sorted(points,key=lambda p:p['code'])
    axes[0].scatter([p['code'] for p in points],[p['frequency_Hz']/1e9 for p in points],s=65,label=corner.upper(),color=colors[corner],zorder=3)
axes[0].axhline(3.2,color='#475569',linestyle='--',linewidth=1.2,label='3.2 GHz target')
axes[0].set(xlabel='5-bit control code',ylabel='Frequency (GHz)',xticks=[0,8,16,24,31],xlim=(-1,32),ylim=(1,4.8))
axes[0].set_title('Corner samples at Vctrl = 0.6 V',fontsize=12)
axes[0].legend(frameon=False,fontsize=9)
axes[0].text(.03,.03,'3 codes per corner; band overlap not yet verified',transform=axes[0].transAxes,fontsize=8,color='#64748b')
for points,label,color in [(baseline,'NMOS pass switches','#64748b'),(tg,'Transmission gates','#2563eb')]:
    points=[(f,n) for f,n in points if f>=1e6]
    if points: axes[1].semilogx([f for f,n in points],[n for f,n in points],label=label,color=color,linewidth=2)
axes[1].set(xlabel='Offset frequency (Hz)',ylabel='SSB phase noise (dBc/Hz)',xlim=(1e6,1e8))
axes[1].set_title('Free-running VCO near 3.2 GHz',fontsize=12)
axes[1].legend(frameon=False,fontsize=9)
axes[1].text(.03,.03,'Noise model enabled; this is not locked-PLL jitter',transform=axes[1].transAxes,fontsize=8,color='#64748b')
for ax in axes:
    ax.grid(True,alpha=.22)
    ax.spines[['top','right']].set_visible(False)
fig.tight_layout(rect=(0,.02,1,.91))
fig.savefig(out/'cmos130_first_results.png',dpi=180)
plt.close(fig)

with open(out/'cmos130_corner_samples.csv','w',newline='',encoding='utf-8-sig') as handle:
    writer=csv.DictWriter(handle,fieldnames=['corner','code','vctrl_V','frequency_Hz','differential_vpp_V','supply_power_W','q_rising_phase_deg'])
    writer.writeheader()
    for p in corners:
        writer.writerow({k:p.get(k) for k in writer.fieldnames})
with open(out/'cmos130_phase_noise.csv','w',newline='',encoding='utf-8-sig') as handle:
    writer=csv.writer(handle)
    writer.writerow(['offset_Hz','baseline_SSB_dBc_per_Hz','TG_SSB_dBc_per_Hz'])
    td=dict(tg)
    for f,n in baseline: writer.writerow([f,n,td.get(f,'')])
print('Written plot and CSV files.')
