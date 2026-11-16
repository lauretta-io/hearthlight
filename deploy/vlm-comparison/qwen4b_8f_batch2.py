"""Paced batch-size-two capacity test on two phase-offset copies of one recording."""
from pathlib import Path
from datetime import datetime,timezone
import json
import math
import os
import statistics
import time
from PIL import Image
import torch
from transformers import AutoModelForImageTextToText,AutoProcessor
from qwen3_evaluate import DevicePeak,parsed_json,schema_ok

ROOT=Path('/probe');manifest=json.loads((ROOT/'manifest.json').read_text())
torch.set_num_threads(4);torch.manual_seed(0);torch.cuda.set_device(0)
processor=AutoProcessor.from_pretrained(manifest['model_id'],revision=manifest['revision'],cache_dir='/bench/models/huggingface/hub',local_files_only=True,min_pixels=manifest['min_pixels'],max_pixels=manifest['max_pixels'])
processor.tokenizer.padding_side='left'
model=AutoModelForImageTextToText.from_pretrained(manifest['model_id'],revision=manifest['revision'],cache_dir='/bench/models/huggingface/hub',local_files_only=True,dtype=torch.bfloat16,low_cpu_mem_usage=True,attn_implementation='sdpa').to('cuda').eval()
eos=model.generation_config.eos_token_id;end_ids=set(eos if isinstance(eos,list) else [eos])

def infer(pair):
 torch.cuda.synchronize();torch.cuda.reset_peak_memory_stats()
 with DevicePeak() as memory:
  started=time.perf_counter();conversations=[]
  for w in pair:
   images=[Image.open(ROOT/p).convert('RGB') for p in w['frames']];content=[]
   for i,image in enumerate(images):content += [{'type':'text','text':f'Frame {i}:'},{'type':'image','image':image}]
   content.append({'type':'text','text':w['standard_prompt']});conversations.append([{'role':'user','content':content}])
  batch=processor.apply_chat_template(conversations,tokenize=True,add_generation_prompt=True,return_dict=True,return_tensors='pt',padding=True).to('cuda',dtype=torch.bfloat16)
  assert batch['input_ids'].shape[0]==2 and batch['image_grid_thw'].shape[0]==16,'Not two eight-frame inputs'
  torch.cuda.synchronize();generation_started=time.perf_counter()
  with torch.inference_mode():out=model.generate(**batch,do_sample=False,repetition_penalty=1.1,no_repeat_ngram_size=32,max_new_tokens=1024)
  torch.cuda.synchronize();generation_seconds=time.perf_counter()-generation_started
  suffix=out[:,batch['input_ids'].shape[1]:];raws=processor.batch_decode(suffix,skip_special_tokens=True)
  responses=[]
  for stream,w,ids,raw in zip(['A','B'],pair,suffix.tolist(),raws,strict=True):
   count=next((i+1 for i,t in enumerate(ids) if t in end_ids),len(ids));data=parsed_json(raw.strip())
   responses.append({'stream':stream,'window_index':w['index'],'source_start':w['start'],'source_end':w['end'],
    'actual_output_tokens':count,'schema_valid':schema_ok(data,'standard'),'parsed':data,'raw_output':raw.strip(),'hit_token_limit':count>=1024})
  elapsed=time.perf_counter()-started
  result={'batch_size':2,'frames_per_stream':8,'processing_seconds':elapsed,'generation_seconds':generation_seconds,
   'output_tokens':sum(r['actual_output_tokens'] for r in responses),'generation_steps':int(suffix.shape[1]),
   'aggregate_output_tokens_per_second':sum(r['actual_output_tokens'] for r in responses)/generation_seconds,
   'responses':responses,'all_valid':all(r['schema_valid'] for r in responses),
   'peak_allocated_bytes':torch.cuda.max_memory_allocated(),'peak_reserved_bytes':torch.cuda.max_memory_reserved(),
   'completed_at':datetime.now(timezone.utc).isoformat()}
 result['sampled_device_peak_bytes']=memory.peak
 return result

warm=infer(manifest['windows'][:2]);(ROOT/'batch2-warmup.json').write_text(json.dumps(warm,indent=2))
rows=[];origin=time.perf_counter()
for i,w in enumerate(manifest['windows']):
 target=i*10;delay=origin+target-time.perf_counter()
 if delay>0:time.sleep(delay)
 began=time.perf_counter()-origin
 row=infer([w,manifest['windows'][(i+1)%len(manifest['windows'])]])
 finished=time.perf_counter()-origin;row.update(batch_index=i,arrival_seconds=target,queue_wait_seconds=max(0,began-target),completion_lag_seconds=finished-target,deadline_met=finished<=target+10)
 with (ROOT/'batch2.jsonl').open('a') as f:f.write(json.dumps(row)+'\n');f.flush();os.fsync(f.fileno())
 rows.append(row)
 print(json.dumps({k:row[k] for k in ['batch_index','processing_seconds','aggregate_output_tokens_per_second','all_valid','completion_lag_seconds','deadline_met']}),flush=True)
q=lambda xs:sorted(xs)[math.ceil(.95*len(xs))-1]
summary={'workload':'inherited scoring prompt, batch size 2','scope':'Two logical feeds from one recording, offset by one ten-second source window; same model weights shared. Not the full per-person reporting pipeline.',
 'batches':len(rows),'window_responses':2*len(rows),'valid_responses':sum(r['schema_valid'] for x in rows for r in x['responses']),
 'mean_pair_processing_seconds':statistics.mean(r['processing_seconds'] for r in rows),'p95_pair_processing_seconds':q([r['processing_seconds'] for r in rows]),
 'median_aggregate_output_tokens_per_second':statistics.median(r['aggregate_output_tokens_per_second'] for r in rows),
 'peak_allocated_gib':max(r['peak_allocated_bytes'] for r in rows)/2**30,'peak_reserved_gib':max(r['peak_reserved_bytes'] for r in rows)/2**30,
 'sampled_device_peak_gib':max(r['sampled_device_peak_bytes'] for r in rows)/2**30,
 'pairs_within_10_seconds':sum(r['deadline_met'] for r in rows),'max_pair_completion_lag_seconds':max(r['completion_lag_seconds'] for r in rows),
 'max_queue_wait_seconds':max(r['queue_wait_seconds'] for r in rows),'two_feed_utilization_fraction':statistics.mean(r['processing_seconds'] for r in rows)/10,
 'token_limit_responses':sum(r['hit_token_limit'] for x in rows for r in x['responses'])}
(ROOT/'batch2-summary.json').write_text(json.dumps(summary,indent=2));print(json.dumps({'state':'completed','summary':summary}),flush=True)
