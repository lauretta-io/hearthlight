"""Check canonical, machine-readable focus-score coverage beyond JSON shape."""
from pathlib import Path
import json
import re
ROOT=Path('/home/lauretta/hearthlight/var/qwen3-evaluation-20261112')
FOCUS=['recklessness','driving','hurt','taking items']
diagnostics={}
for model in ['qwen3-vl-2b','qwen3-vl-4b']:
 rows=[json.loads(s) for s in (ROOT/'results'/model/'standard.jsonl').read_text().splitlines()]
 rows=[r for r in rows if r['frame_count']==5];coverage=[]
 for row in rows:
  data=row.get('parsed') or {};think=data.get('think','');found=[]
  if isinstance(think,str):
   for term in FOCUS:
    if re.search(r'\b'+re.escape(term)+r'\s*[\"\x27]?\s*[:=]\s*(10|[0-9])(?:\.\d+)?',think,re.I):found.append(term)
  coverage.append({'video':row['video'],'start':row['start'],'focus_scores_found':found})
 diagnostics[model]={'all_four_requested_focus_scores_present':sum(len(r['focus_scores_found'])==4 for r in coverage),
  'requests':len(rows),'definition':'All four canonical labels followed by numeric scores in a parseable JSON think field, using the same extraction as the annotated videos.','coverage':coverage}
(ROOT/'focus-score-coverage.json').write_text(json.dumps(diagnostics,indent=2))
p=ROOT/'benchmark-summary.txt';text=p.read_text().split('\nRequested focus-score coverage')[0].rstrip()
text+='\n\nRequested focus-score coverage (all four canonical scores machine-readable in a parseable JSON response):\n'
for model,data in diagnostics.items():text+=f"- {model}: {data['all_four_requested_focus_scores_present']}/{data['requests']} requests.\n"
p.write_text(text)
print(json.dumps({m:{k:v for k,v in d.items() if k!='coverage'} for m,d in diagnostics.items()},indent=2))
