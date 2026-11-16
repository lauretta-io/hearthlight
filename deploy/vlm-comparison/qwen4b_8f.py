"""4B eight-frame probe and paced two-feed replay; no production DB writes."""
from datetime import datetime, timedelta, timezone
from hashlib import sha256
import json
import math
import os
from pathlib import Path
import statistics
import sys
import time

from PIL import Image
import torch
import transformers
from transformers import AutoModelForImageTextToText, AutoProcessor
from qwen3_evaluate import DevicePeak, parsed_json, schema_ok
sys.path.insert(0,'/behavior')
from tracking import PersonDetector, link_detections
from scene import SCENE_PROMPT, build_request, labeled_frames, parse_scene

ROOT=Path('/probe')
manifest=json.loads((ROOT/'manifest.json').read_text())
digest=sha256((ROOT/'manifest.json').read_bytes()).hexdigest()
assert digest==(ROOT/'manifest.sha256').read_text().strip()
torch.set_num_threads(4);torch.manual_seed(0);torch.cuda.set_device(0)
free,total=torch.cuda.mem_get_info();baseline=total-free
loaded=time.perf_counter()
processor=AutoProcessor.from_pretrained(manifest['model_id'],revision=manifest['revision'],cache_dir='/bench/models/huggingface/hub',local_files_only=True,min_pixels=manifest['min_pixels'],max_pixels=manifest['max_pixels'])
model=AutoModelForImageTextToText.from_pretrained(manifest['model_id'],revision=manifest['revision'],cache_dir='/bench/models/huggingface/hub',local_files_only=True,dtype=torch.bfloat16,low_cpu_mem_usage=True,attn_implementation='sdpa').to('cuda').eval()
detector=PersonDetector('cuda',Path('/oldmodels/yolov8n.pt'))
torch.cuda.synchronize()
(ROOT/'model.json').write_text(json.dumps({'model_id':manifest['model_id'],'revision':manifest['revision'],'manifest_sha256':digest,
 'transformers':transformers.__version__,'torch':torch.__version__,'gpu':torch.cuda.get_device_name(),
 'device_total_bytes':total,'pre_model_device_used_bytes':baseline,'cold_load_seconds':time.perf_counter()-loaded,
 'dtype':'bfloat16','attention':'sdpa','detector':'YOLOv8n, conf 0.35, real sampled-frame detections',
 'scope':'Scene/person timing includes YOLO, IoU tracking and annotation; excludes TransReID and SigLIP.'},indent=2))

def infer(window,workload,stream):
 torch.cuda.synchronize();torch.cuda.reset_peak_memory_stats()
 with DevicePeak() as memory:
  started=time.perf_counter()
  images=[Image.open(ROOT/p).convert('RGB') for p in window['frames']]
  read_seconds=time.perf_counter()-started;track_count=0;detection_seconds=0;request=None;tracks=[]
  if workload=='scene_person':
   t=time.perf_counter();tracks=link_detections(detector.detect(images));torch.cuda.synchronize();detection_seconds=time.perf_counter()-t
   track_count=len(tracks)
   base=datetime(2026,11,12,tzinfo=timezone.utc)
   sample={'sample_id':f'probe-{window["index"]}-{stream}','camera_id':'isolated-video-probe','camera_name':'Recorded street video',
    'sample_fps':.8,'sample_started_at':(base+timedelta(seconds=window['frame_times'][0])).isoformat(),
    'sampled_at':(base+timedelta(seconds=window['end'])).isoformat()}
   request=build_request(sample,images,tracks,[None]*len(tracks))
   shown=labeled_frames(images,request)
   prompt=('There are exactly 8 frames, numbered 0 through 7. All frame indices in your answer must be within that range. '+SCENE_PROMPT+'\n\nINPUT_JSON:\n'+json.dumps(request))
   limit=2048
  else:shown=images;prompt=window['standard_prompt'];limit=1024
  vlm_start=time.perf_counter();content=[]
  for i,image in enumerate(shown):content.extend([{'type':'text','text':f'Frame {i}:'},{'type':'image','image':image}])
  content.append({'type':'text','text':prompt})
  batch=processor.apply_chat_template([{'role':'user','content':content}],tokenize=True,add_generation_prompt=True,return_dict=True,return_tensors='pt').to('cuda',dtype=torch.bfloat16)
  torch.cuda.synchronize();generation_start=time.perf_counter()
  # Match the live generation policy for scene/person; match the prior benchmark for standard.
  kwargs={} if workload=='scene_person' else {'repetition_penalty':1.1,'no_repeat_ngram_size':32}
  with torch.inference_mode():output=model.generate(**batch,do_sample=False,max_new_tokens=limit,**kwargs)
  torch.cuda.synchronize();generation_seconds=time.perf_counter()-generation_start
  tokens=output[:,batch['input_ids'].shape[1]:];raw=processor.batch_decode(tokens,skip_special_tokens=True)[0].strip()
  parsed=parsed_json(raw);errors=[]
  if workload=='scene_person':
   try:
    analysis=parse_scene(raw,request,images);errors=analysis['errors'];valid=not errors
   except Exception as error:valid=False;errors=[str(error)]
  else:valid=schema_ok(parsed,'standard')
  vlm_seconds=time.perf_counter()-vlm_start
  elapsed=time.perf_counter()-started
  count=int(tokens.shape[1]);grid=batch.get('image_grid_thw')
  vision_tokens=int(grid.prod(dim=1).sum().item()/4) if grid is not None else None
  row={'workload':workload,'stream':stream,'window_index':window['index'],'source_start':window['start'],'source_end':window['end'],
    'frame_times':window['frame_times'],'frame_count':8,'track_count':track_count,'frame_read_seconds':read_seconds,
    'detection_tracking_seconds':detection_seconds,'vlm_seconds':vlm_seconds,'processing_seconds':elapsed,
    'generation_seconds':generation_seconds,'generated_tokens':count,'generation_tokens_per_second':count/generation_seconds,
    'input_tokens':int(batch['input_ids'].shape[1]),'visual_tokens':vision_tokens,'max_new_tokens':limit,'hit_token_limit':count>=limit,
    'schema_valid':valid,'errors':errors,'parsed':parsed,'raw_output':raw,
    'peak_allocated_bytes':torch.cuda.max_memory_allocated(),'peak_reserved_bytes':torch.cuda.max_memory_reserved(),
    'manifest_sha256':digest,'prompt_sha256':sha256(prompt.encode()).hexdigest(),'completed_at':datetime.now(timezone.utc).isoformat()}
 row['sampled_device_peak_bytes']=memory.peak
 return row


def save(row,path):
 with path.open('a') as f:f.write(json.dumps(row)+'\n');f.flush();os.fsync(f.fileno())
 print(json.dumps({k:row.get(k) for k in ['workload','stream','window_index','track_count','processing_seconds','generated_tokens','generation_tokens_per_second','schema_valid','completion_lag_seconds','deadline_met']}),flush=True)

rows=[]
for workload in ['standard','scene_person']:
 torch.cuda.empty_cache()
 warm=infer(manifest['windows'][0],workload,'warmup');(ROOT/f'{workload}-warmup.json').write_text(json.dumps(warm,indent=2))
 if workload=='standard':
  for w in manifest['windows']:
   row=infer(w,workload,'single');rows.append(row);save(row,ROOT/'standard.jsonl')
 else:
  origin=time.perf_counter()
  for w in manifest['windows']:
   for stream in ['A','B']:
    arrival=w['index']*10
    delay=origin+arrival-time.perf_counter()
    if delay>0:time.sleep(delay)
    began=time.perf_counter()-origin
    row=infer(w,workload,stream);finished=time.perf_counter()-origin
    row.update(arrival_seconds=arrival,processing_started_seconds=began,finished_seconds=finished,
      queue_wait_seconds=max(0,began-arrival),completion_lag_seconds=finished-arrival,deadline_met=finished<=arrival+10)
    rows.append(row);save(row,ROOT/'scene_person.jsonl')

q=lambda values:sorted(values)[math.ceil(.95*len(values))-1]
summary={'model_id':manifest['model_id'],'revision':manifest['revision'],'manifest_sha256':digest,
 'sampling':'8 frames per 10-second window, 640px wide, 1.25 seconds apart; first minute of the quieter Japanese street recording, before browser navigation.',
 'limitations':['Six distinct windows only; this is a small capacity probe, not a long-duration load test.',
 'Two logical feeds replay the SAME recording; different scene content may change response length and latency.',
 'The street scene has ordinary pedestrian movement and street cleaning; it is not an empty-room workload.',
 'Scene/person includes YOLO/IoU processing but not TransReID or SigLIP; full deployment needs headroom for those stages.',
 'Output token budgets and prompts differ between the inherited scoring and live scene/person workloads.'],
 'workloads':{}}
for workload in ['standard','scene_person']:
 group=[r for r in rows if r['workload']==workload];service=[r['processing_seconds'] for r in group]
 stats={'requests':len(group),'valid_responses':sum(r['schema_valid'] for r in group),
  'mean_processing_seconds':statistics.mean(service),'median_processing_seconds':statistics.median(service),'p95_processing_seconds':q(service),'max_processing_seconds':max(service),
  'mean_generated_tokens':statistics.mean(r['generated_tokens'] for r in group),
  'median_generation_tokens_per_second':statistics.median(r['generation_tokens_per_second'] for r in group),
  'aggregate_generation_tokens_per_second':sum(r['generated_tokens'] for r in group)/sum(r['generation_seconds'] for r in group),
  'peak_allocated_gib':max(r['peak_allocated_bytes'] for r in group)/2**30,'peak_reserved_gib':max(r['peak_reserved_bytes'] for r in group)/2**30,
  'sampled_device_peak_gib':max(r['sampled_device_peak_bytes'] for r in group)/2**30,
  'input_tokens_range':[min(r['input_tokens'] for r in group),max(r['input_tokens'] for r in group)],
  'visual_tokens_range':[min(r['visual_tokens'] for r in group),max(r['visual_tokens'] for r in group)],
  'track_count_range':[min(r['track_count'] for r in group),max(r['track_count'] for r in group)],
  'token_limit_responses':sum(r['hit_token_limit'] for r in group),
  'estimated_sustainable_feeds_at_10s_cadence':10/statistics.mean(service),
  'two_feed_utilization_fraction':2*statistics.mean(service)/10}
 if workload=='scene_person':
  stats.update(deadlines_met=sum(r['deadline_met'] for r in group),deadline_requests=len(group),
   max_completion_lag_seconds=max(r['completion_lag_seconds'] for r in group),p95_completion_lag_seconds=q([r['completion_lag_seconds'] for r in group]),
   max_queue_wait_seconds=max(r['queue_wait_seconds'] for r in group),
   replay_finished_seconds=max(r['finished_seconds'] for r in group),input_video_seconds_per_feed=60)
 summary['workloads'][workload]=stats
(ROOT/'summary.json').write_text(json.dumps(summary,indent=2));print(json.dumps({'state':'completed','summary':summary}),flush=True)
