import csv
import json
import math
import statistics
import sys


def read_psf(path):
    data = {}
    reading = False
    with open(path) as handle:
        for line in handle:
            if line.strip() == 'VALUE':
                reading = True
                continue
            if not reading or line.strip() == 'END':
                continue
            if not line.startswith('"'):
                continue
            name, value = line[1:].split('"', 1)
            try:
                value = float(value.strip())
            except ValueError:
                continue
            data.setdefault(name, []).append(value)
    return data


def integral_mean(t, values):
    return sum((t[i+1]-t[i])*(values[i]+values[i+1])/2 for i in range(len(t)-1))/(t[-1]-t[0])


def crossings(t, y):
    return [t[i] - y[i]*(t[i+1]-t[i])/(y[i+1]-y[i])
            for i in range(len(t)-1) if y[i] <= 0 < y[i+1]]


data = read_psf(sys.argv[1])
begin = float(sys.argv[2]) if len(sys.argv) > 2 else 30e-9
end = float(sys.argv[3]) if len(sys.argv) > 3 else 90e-9
idx = [i for i, t in enumerate(data['time']) if begin <= t <= end]
if len(idx)<2:
    raise ValueError('Measurement window contains fewer than two samples.')
t = [data['time'][i] for i in idx]
selected = {name: [values[i] for i in idx] for name, values in data.items() if len(values) == len(data['time'])}
result = {'window_start_s': t[0], 'window_end_s': t[-1], 'samples': len(t)}
for name, values in selected.items():
    if name != 'time':
        result[name] = {'min': min(values), 'max': max(values), 'mean': integral_mean(t, values)}
if 'out0' in selected and 'out180' in selected:
    diff = [a-b for a,b in zip(selected['out0'],selected['out180'])]
    cr = crossings(t,diff)
    result['differential_vpp_V'] = max(diff)-min(diff)
    result['rising_crossings'] = len(cr)
    result['frequency_Hz'] = (len(cr)-1)/(cr[-1]-cr[0]) if len(cr)>2 else None
    if result['frequency_Hz'] and result['differential_vpp_V'] < 1e-3:
        result['frequency_Hz'] = None
        result['oscillation_note'] = 'Differential swing below 1 mV; crossings invalid.'
    if result['frequency_Hz'] and 'out90' in selected and 'out270' in selected:
        qdiff = [a-b for a,b in zip(selected['out90'],selected['out270'])]
        qcr = crossings(t,qdiff)
        if len(cr)>2 and len(qcr)>2 and max(qdiff)-min(qdiff)>=1e-3:
            period = (cr[-1]-cr[0])/(len(cr)-1)
            qperiod = (qcr[-1]-qcr[0])/(len(qcr)-1)
            if abs(qperiod/period-1)<0.01:
                phases = [((min(qcr,key=lambda q:abs(q-c))-c)/period*360)%360 for c in cr[1:-1]]
                result['q_rising_phase_deg'] = statistics.median(phases)
if 'VDD:p' in selected:
    vdd = selected.get('vdd',[1.2]*len(t))
    power = [-v*i for v,i in zip(vdd,selected['VDD:p'])]
    result['supply_power_W'] = integral_mean(t,power)
print(json.dumps(result,indent=2,sort_keys=True))
if len(sys.argv)>4:
    names=['time','out0','out180','out90','out270','VDD:p']
    with open(sys.argv[4],'w',newline='') as handle:
        writer=csv.writer(handle)
        writer.writerow(names)
        for i in range(len(data['time'])):
            if data['time'][i]>=85e-9:
                writer.writerow([data.get(n,[math.nan]*len(data['time']))[i] for n in names])
