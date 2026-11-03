#!/usr/bin/env python3
"""Draw any archived Spectre subcircuit in bounded, indexed CircuitikZ pages."""
import argparse
import collections
import hashlib
import json
import math
from pathlib import Path
import re

HERE = Path(__file__).resolve().parent
DEFAULT_SOURCE = HERE.parent.parent / 'source_release'
HEADER = re.compile(r'^\.?subckt\s+(\w+)\s*\(([^)]*)\)\s*$', re.I)
CARD = re.compile(r'^(\S+)\s*\(([^)]*)\)\s+(\S+)(?:\s+(.*))?$')
PREAMBLE = r"""\documentclass[10pt]{article}
\usepackage[landscape,a4paper,margin=1.4cm]{geometry}
\usepackage[T1]{fontenc}
\usepackage{lmodern,graphicx,array,url}
\usepackage[american]{circuitikz}
\pagestyle{plain}
\setlength{\parindent}{0pt}
\urlstyle{tt}
\begin{document}
"""


def digest(value):
    return hashlib.sha256(value).hexdigest()


def object_digest(obj):
    return digest(json.dumps(obj, separators=(',', ':'), ensure_ascii=True).encode())


def parse_deck(path):
    """Return literal subcircuit bodies with physical source line numbers."""
    current = None
    pending = []
    for number, line in enumerate(path.read_text(encoding='ascii').splitlines(), 1):
        line = line.partition('//')[0].strip()
        if not line or line.startswith('*'):
            continue
        if not pending:
            start = number
        if line.endswith('\\'):
            pending.append(line[:-1].strip())
            continue
        statement = ' '.join(pending+[line])
        pending = []
        if HEADER.match(statement):
            if current:
                raise ValueError('Unexpected nested subcircuit in ' + str(path))
            name, ports = HEADER.match(statement).groups()
            current = {'name': name, 'ports': ports.split(), 'first_line': start,
                       'parameters': [], 'cards': []}
        elif re.match(r'^\.?ends\b', statement, re.I):
            if current is None:
                raise ValueError('Unmatched ends in ' + str(path))
            current['last_line'] = number
            yield current
            current = None
        elif current:
            if statement.startswith('parameters '):
                current['parameters'].append(statement)
            else:
                match = CARD.fullmatch(statement)
                if not match:
                    raise ValueError('%s:%d unsupported subcircuit statement: %s' % (path, start, statement))
                inst, pins, model, params = match.groups()
                current['cards'].append((inst, pins.split(), model, params or '', start, number))
    if current or pending:
        raise ValueError('Incomplete subcircuit or continuation in ' + str(path))


def scan(source):
    manifest = json.loads((source/'manifest.json').read_text(encoding='ascii'))
    decks = [e for e in manifest['files'] if e['path'].endswith('.scs')]
    families, headers, occurrences = {}, {}, {}
    for e in decks:
        rel = e['path']
        path = source/rel
        if digest(path.read_bytes()) != e['published_sha256']:
            raise ValueError('Deck differs from the release manifest: '+rel)
        occurrences[rel] = {}
        for mod in parse_deck(path):
            name = mod['name']
            prior = headers.setdefault(name, mod['ports'])
            if prior != mod['ports'] or name in occurrences[rel]:
                raise ValueError('Ambiguous port declaration: '+name+' in '+rel)
            shape = [(i,nodes,model) for i,nodes,model,_,_,_ in mod['cards']]
            key = name+'-'+object_digest([name, mod['ports'], shape])[:12]
            full = object_digest([name, mod['ports'], mod['parameters'], [v[:4] for v in mod['cards']]])
            if key not in families:
                families[key] = {'id':key, 'module':name, 'ports':mod['ports'], 'cards':len(shape),
                    'model_counts':dict(collections.Counter(v[2] for v in shape)), 'representative':rel,
                    'representative_start_line':mod['first_line'], 'representative_end_line':mod['last_line'],
                    'definitions':0, 'body_ids':set()}
            row = families[key]
            row['definitions'] += 1
            row['body_ids'].add(full)
            occurrences[rel][name] = [key,full,mod['first_line'],mod['last_line']]
    for row in families.values():
        row['parameterized_bodies'] = len(row.pop('body_ids'))
    for row in families.values():
        for model in row['model_counts']:
            if model not in headers and model not in ('n12','p12','n12_ckt_rf','resistor','isource','capacitor'):
                raise ValueError('No device drawing rule for '+model)
    return {'deck_count':len(decks),'module_names':len(headers),'family_count':len(families),
            'subcircuit_definitions':sum(v['definitions'] for v in families.values()),
            'scope':'Explicit .scs subcircuit definitions and their immediate device cards. Family identity uses the name, formal pins, ordered instance/model names and ordered net terminals. Body identity also includes parameter expressions. Top-level stimuli and analyses remain in each deck.',
            'occurrence_columns':['family_id','parameterized_body_sha256','first_line','last_line'],
            'families':families,'decks':occurrences}, headers


def tex(s):
    escaped = {'_':r'\_', '#':r'\#', '%':r'\%', '$':r'\$', '{':r'\{', '}':r'\}',
               '&':r'\&', '~':r'\textasciitilde{}', '^':r'\textasciicircum{}', '\\':r'\textbackslash{}'}
    return ''.join(escaped.get(c,c) for c in str(s))


def net_index(mod):
    nets = dict.fromkeys(mod['ports'])
    for _,pins,_,_,_,_ in mod['cards']:
        nets.update(dict.fromkeys(pins))
    return {s:i for i,s in enumerate(nets,1)}


def cell(card, number, nets, headers):
    inst,pins,model,params,lo,hi=card
    number_label = [r'\tiny N%d' % nets[p] for p in pins]
    pic = [r'\begin{circuitikz}[american,font=\scriptsize]']
    if model in ('n12','p12','n12_ckt_rf'):
        terms=['D','G','S','B']
        if len(pins)!=4:raise ValueError('Expected 4 MOS terminals')
        kind='pmos' if model=='p12' else 'nmos'
        pic.append(r'\draw (0,0) node[%s,bulk] (Q) {};' % kind)
        # CircuitikZ's symbolic D/S anchors retain model order for both polarities.
        delta_d,delta_s = ('-.32','.32') if kind=='pmos' else ('.32','-.32')
        for pin, offset, label, place in [('D','0,'+delta_d,0,'right'),('G','-.45,0',1,'left'),('S','0,'+delta_s,2,'right'),('bulk','.45,0',3,'right')]:
            pic.append(r'\draw (Q.%s) -- ++(%s) node[%s] {%s};' % (pin,offset,place,number_label[label]))
    elif model in ('resistor','capacitor','isource'):
        terms=['1','2']
        if len(pins)!=2:raise ValueError('Expected 2 passive or source terminals')
        symbol={'resistor':'R','capacitor':'C','isource':'I'}[model]
        pic.append(r'\draw (0,0) node[left]{%s} to[%s] (2.3,0) node[right]{%s};' % (number_label[0],symbol,number_label[1]))
    else:
        terms=headers[model]
        if len(terms)!=len(pins):raise ValueError('Pin count differs for '+model)
        half=(len(pins)+1)//2
        height=half*.32+.16
        pic.append(r'\draw (0,0) rectangle (2.0,%.4f);' % height)
        for i in range(len(pins)):
            left=i<half; y=height-.25-(i if left else i-half)*.32
            x,end,pos=(0,-.32,'left') if left else (2,2.32,'right')
            pic.append(r'\draw (%.2f,%.3f) -- (%.2f,%.3f) node[%s]{%s};' % (x,y,end,y,pos,number_label[i]))
            pic.append(r'\node[%s,font=\tiny] at (%.2f,%.3f) {%s};' % ('right' if left else 'left',x,y,tex(terms[i])))
    pic.append(r'\end{circuitikz}')
    conn=' \\quad '.join(r'\textbf{%s}~N%d~=~\texttt{%s}'%(tex(t),nets[p],tex(p)) for t,p in zip(terms,pins))
    head=r'\textbf{%d.\quad \texttt{%s}}\quad\texttt{%s}\hfill source line %d'%(number,tex(inst),tex(model),lo)
    if hi!=lo:head+=r'--%d'%hi
    card_text='%% Source lines %d-%d: %s (%s) %s %s' % (lo,hi,inst,' '.join(pins),model,params)
    return ('\n'.join([card_text,r'\begin{minipage}[t][5.95cm][t]{.475\linewidth}',r'\raggedright\small '+head,r'\par\smallskip\centering',
                 *pic,r'\par\raggedright\footnotesize '+conn+r'\par',r'\medskip\scriptsize\texttt{'+tex(params)+'}' if params else '',
                 r'\vfill\hrule\end{minipage}']))


def pages(index, headers, source, rel, modname, first, count):
    family=index['decks'][rel][modname][0]
    mod=next(x for x in parse_deck(source/rel) if x['name']==modname)
    nets=net_index(mod)
    limit=min(first+count-1,len(mod['cards']))
    if not 1<=first<=limit:raise ValueError('Requested card range outside subcircuit')
    output=[]
    for offset in range(first,limit+1,4):
        end=min(offset+3,limit)
        title=r'{\Large\sffamily\bfseries %s}\hfill Cards %d--%d of %d\par'%(tex(modname),offset,end,len(mod['cards']))
        output.extend([r'\clearpage',title,r'\small Family \texttt{'+tex(family)+'}'+r'\quad Declaration lines %d--%d\par'%(mod['first_line'],mod['last_line']),
                       r'\textbf{Source} \path{'+rel+r'}\par',r'\textbf{Ports in declaration order} '+', '.join(r'\texttt{%s} (N%d)'%(tex(p),nets[p]) for p in mod['ports'])+r'\par',
                       r'\smallskip Equal net IDs connect within this module. MOS terminal letters follow the deck order D, G, S, B. Each RF MOS symbol represents the external four-terminal model.\par\medskip'])
        for i in range(offset,end+1):
            output.append(cell(mod['cards'][i-1],i,nets,headers))
            if (i-offset)%2==0 and i<end:output.append(r'\hfill%')
            else:output.append(r'\par\medskip')
    return '\n'.join(output)


def main():
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--source-root',type=Path,default=DEFAULT_SOURCE)
    ap.add_argument('--output',type=Path,required=True)
    ap.add_argument('--mode',choices=['index','gallery','draw'],default='draw')
    ap.add_argument('--family',help='Exact family ID from catalog.json')
    ap.add_argument('--deck',help='Exact deck path relative to source_release')
    ap.add_argument('--module',help='Module name from selected deck')
    ap.add_argument('--first',type=int,default=1,help='One-based first device ordinal')
    ap.add_argument('--count',type=int,default=4,help='Number of device cards to draw')
    args=ap.parse_args()
    idx,headers=scan(args.source_root)
    if args.mode=='index':
        data=json.dumps(idx,separators=(',',':'),ensure_ascii=True)+'\n'
    else:
        if args.mode=='gallery':
            groups=[]
            for key,row in sorted(idx['families'].items()):
                n=row['cards']
                groups.append(pages(idx,headers,args.source_root,row['representative'],row['module'],1,n if n<=128 else 4))
        else:
            if args.family:
                if args.deck or args.module:ap.error('Select a family or a deck and module')
                if args.family not in idx['families']:ap.error('Unknown family')
                row=idx['families'][args.family]
                deck,mod=row['representative'],row['module']
            else:
                deck,mod=args.deck,args.module
            if deck not in idx['decks'] or mod not in idx['decks'][deck]:ap.error('Unknown deck/module pair')
            groups=[pages(idx,headers,args.source_root,deck,mod,args.first,args.count)]
        data=PREAMBLE+'\n'.join(groups)+'\n\\end{document}\n'
    args.output.write_bytes(data.encode('ascii'))
    print(json.dumps({'decks':idx['deck_count'],'module_names':idx['module_names'],'families':idx['family_count'],
                      'definitions':idx['subcircuit_definitions'],'output':str(args.output),'bytes':len(data)}))


if __name__=='__main__':
    main()
