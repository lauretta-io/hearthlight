"""Rerun only cases affected by the neutral actor-locator correction."""
import argparse
from datetime import datetime,timezone
from hashlib import sha256
import json
import os
import time
import torch
from transformers import AutoModelForImageTextToText, AutoProcessor
from qwen3_evaluate import infer,OUT

args=argparse.ArgumentParser();args.add_argument('--model',required=True);model_key=args.parse_args().model
protocol=json.loads((OUT/'protocol-v2.json').read_text());digest=sha256((OUT/'protocol-v2.json').read_bytes()).hexdigest()
assert digest==(OUT/'protocol-v2.sha256').read_text().strip()
config=protocol['models'][model_key];folder=OUT/'results'/model_key
windows=[w for w in protocol['windows'] if w['video']=='video-091517' and w['five_frames']]
torch.set_num_threads(4);torch.manual_seed(0);torch.cuda.set_device(0)
processor=AutoProcessor.from_pretrained(config['id'],revision=config['revision'],cache_dir=config['cache'],local_files_only=True,min_pixels=128*32*32,max_pixels=512*512)
model=AutoModelForImageTextToText.from_pretrained(config['id'],revision=config['revision'],cache_dir=config['cache'],local_files_only=True,dtype=torch.bfloat16,low_cpu_mem_usage=True,attn_implementation='sdpa').to('cuda').eval()
torch.cuda.empty_cache();warmup=infer(model,processor,windows[0],'temporal')
(folder/'temporal-repair-warmup.json').write_text(json.dumps(warmup,indent=2))
path=folder/'temporal-repair.jsonl'
done={(r['video'],r['start']) for r in map(json.loads,path.read_text().splitlines())} if path.exists() else set()
for window in windows:
 if (window['video'],window['start']) in done:continue
 row=infer(model,processor,window,'temporal');row.update(model=model_key,model_id=config['id'],revision=config['revision'],protocol_sha256=digest,prompt_revision=2)
 with path.open('a') as f:f.write(json.dumps(row)+'\n');f.flush();os.fsync(f.fileno())
 print(json.dumps({'model':model_key,'workload':'temporal_neutral_repair','start':window['start'],'valid':row['schema_valid'],'seconds':row['elapsed_seconds']}),flush=True)
original=folder/'temporal-v1.jsonl'
if not original.exists():(folder/'temporal.jsonl').replace(original)
rows=[json.loads(s) for s in original.read_text().splitlines() if json.loads(s)['video']!='video-091517']
rows += [json.loads(s) for s in path.read_text().splitlines()]
assert len(rows)==40 and len({(r['video'],r['start']) for r in rows})==40
(folder/'temporal.jsonl').write_text(''.join(json.dumps(r)+'\n' for r in sorted(rows,key=lambda r:(r['video'],r['start']))))
print(json.dumps({'model':model_key,'state':'repair_complete'}),flush=True)
