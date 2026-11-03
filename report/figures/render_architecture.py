#!/usr/bin/env python3
"""Build the GitHub SVG from the report's shared American CircuitikZ source."""
import argparse
from pathlib import Path
import subprocess


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--pdflatex', default='pdflatex')
    parser.add_argument('--pdftocairo', default='pdftocairo')
    args = parser.parse_args()
    report = Path(__file__).resolve().parent.parent
    build = report / 'build' / 'architecture'
    build.mkdir(parents=True, exist_ok=True)
    svg = report.parent / 'docs' / 'figures' / 'system-architecture.svg'
    svg.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run([
        args.pdflatex, '-no-shell-escape', '-interaction=nonstopmode',
        '-halt-on-error', '-output-directory=' + str(build),
        '-jobname=system-architecture',
        'figures/system-architecture-standalone.tex',
    ], cwd=report, check=True)
    subprocess.run([
        args.pdftocairo, '-svg', str(build / 'system-architecture.pdf'),
        str(svg),
    ], check=True)
    # Keep black symbols legible in both light and dark GitHub themes.
    drawing = svg.read_text(encoding='utf-8')
    if drawing.count('</defs>') != 1:
        raise ValueError('Unexpected SVG structure from pdftocairo')
    drawing = drawing.replace(
        '</defs>',
        '</defs>\n<rect width="100%" height="100%" fill="white"/>', 1)
    svg.write_bytes(drawing.encode('utf-8'))
    print('Updated ' + str(svg.relative_to(report.parent)))


if __name__ == '__main__':
    main()
