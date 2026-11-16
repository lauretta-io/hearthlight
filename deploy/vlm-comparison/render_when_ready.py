"""Render completed model/video pairs while inference continues."""
import argparse
import json
from pathlib import Path
import time

from render import render

ROOT = Path('/home/lauretta/hearthlight/var/vlm-comparison')
parser = argparse.ArgumentParser()
parser.add_argument('--model', required=True)
args = parser.parse_args()
manifest = json.loads((ROOT/'input-manifest.json').read_text())
for video in manifest['videos']:
    path = ROOT/'results'/args.model/(video['key']+'.jsonl')
    expected = {window['start'] for window in video['windows']}
    while True:
        rows = []
        if path.exists():
            rows = [json.loads(line) for line in path.read_text().splitlines() if line.strip()]
        if {row['start'] for row in rows if row.get('status')=='ok'} == expected:
            break
        time.sleep(2)
    render(args.model, video['key'])
