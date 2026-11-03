"""Write a read-only OCEAN extraction program; never run OCEAN or Spectre."""
import argparse
from pathlib import Path
from prepare_driven_pll_noise import ocean_script


def main():
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--raw',required=True)
    ap.add_argument('--output-prefix',required=True)
    ap.add_argument('--out-script',required=True)
    ap.add_argument('--integrated',action='store_true')
    args=ap.parse_args()
    Path(args.out_script).write_text(ocean_script(args.raw,args.output_prefix,args.integrated),encoding='utf8')
    print('Prepared read-only OCEAN extraction script; no program launched.')


if __name__=='__main__':main()
