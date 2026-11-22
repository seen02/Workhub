"""Export every image referenced by a selected Compose stack after user builds it."""
import argparse
import subprocess
from pathlib import Path
from configure import ROOT,load_env

parser=argparse.ArgumentParser()
parser.add_argument('--output',default='dist/images.tar')
args=parser.parse_args()
env=load_env()
compose='compose.native.yaml' if env['DEPLOY_MODE']=='native' else 'compose.yaml'
images=subprocess.check_output(['docker','compose','-f',compose,'config','--images'],cwd=ROOT,text=True).splitlines()
images=list(dict.fromkeys(value.strip() for value in images if value.strip()))
target=Path(args.output)
if not target.is_absolute():target=ROOT/target
target.parent.mkdir(parents=True,exist_ok=True)
subprocess.run(['docker','image','save','-o',str(target),*images],cwd=ROOT,check=True)
print('Saved image archive:',target)
