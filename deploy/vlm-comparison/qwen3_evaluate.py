"""Paired Qwen3 accuracy/performance evaluation with replayable raw responses."""
import argparse
from datetime import datetime, timezone
from hashlib import sha256
import json
import os
from pathlib import Path
import threading
import time

from PIL import Image, ImageDraw
import torch
import transformers
from transformers import AutoModelForImageTextToText, AutoProcessor

ROOT = Path('/bench')
OUT = Path('/evaluation')
STATES = {'absent','upright','bent','crouched','moving','stationary','unclear'}
ACTIONS = {'walking','running','bending','crouching','standing','handling_object','driving'}


def parsed_json(raw):
    for i,c in enumerate(raw):
        if c == '{':
            try:
                data,_ = json.JSONDecoder().raw_decode(raw[i:])
                if isinstance(data,dict): return data
            except ValueError: pass
    return None


def schema_ok(data, workload):
    if not isinstance(data,dict): return False
    if workload == 'standard':
        return (all(isinstance(data.get(k),str) for k in ['scene_summary','think','visible_items','visible_activities'])
          and type(data.get('anomaly_detected')) is bool and type(data.get('confidence')) in [int,float]
          and 0 <= data['confidence'] <= 1)
    order = data.get('order')
    states = data.get('frame_states')
    actions = data.get('actions')
    return (isinstance(order,list) and len(order)==5 and all(type(i) is int for i in order) and sorted(order)==list(range(5))
      and isinstance(states,list) and len(states)==5 and all(isinstance(s,dict) and type(s.get('image_id')) is int and s.get('state') in STATES for s in states)
      and sorted(s['image_id'] for s in states)==list(range(5)) and isinstance(actions,list) and all(a in ACTIONS for a in actions))


class DevicePeak:
    def __init__(self): self.peak=0;self.done=threading.Event()
    def sample(self):
        while not self.done.is_set():
            free,total=torch.cuda.mem_get_info();self.peak=max(self.peak,total-free)
            self.done.wait(.025)
    def __enter__(self): self.thread=threading.Thread(target=self.sample,daemon=True);self.thread.start();return self
    def __exit__(self,*args): self.done.set();self.thread.join()


def images_for(window,workload):
    images=[Image.open(ROOT/file).convert('RGB') for file in window['frames']]
    if workload == 'temporal':
        for image in images:
            draw=ImageDraw.Draw(image);w,h=image.size
            draw.rectangle((0,0,w,32),fill='black');draw.rectangle((0,h-48,w,h),fill='black')
            if window['video']=='video-091517': draw.rectangle((int(.81*w),0,w,int(.38*h)),fill='black')
        images=[images[i] for i in window['shuffle']]
    return images


def infer(model,processor,window,workload):
    images=images_for(window,workload)
    prompt=window['standard_prompt'] if workload=='standard' else window['temporal_prompt']
    content=[]
    for i,image in enumerate(images):
        content += [{'type':'text','text':f'{"Frame" if workload=="standard" else "Image"} {i}:'},{'type':'image','image':image}]
    content.append({'type':'text','text':prompt})
    torch.cuda.synchronize();torch.cuda.reset_peak_memory_stats()
    with DevicePeak() as memory:
        started=time.perf_counter()
        batch=processor.apply_chat_template([{'role':'user','content':content}],tokenize=True,add_generation_prompt=True,
            return_dict=True,return_tensors='pt').to('cuda',dtype=torch.bfloat16)
        torch.cuda.synchronize();generation_start=time.perf_counter()
        limit=1024 if workload=='standard' else 512
        with torch.inference_mode():
            generated=model.generate(**batch,do_sample=False,repetition_penalty=1.1,no_repeat_ngram_size=32,max_new_tokens=limit)
        torch.cuda.synchronize();generation_seconds=time.perf_counter()-generation_start
        token_ids=generated[:,batch['input_ids'].shape[1]:]
        raw=processor.batch_decode(token_ids,skip_special_tokens=True)[0].strip()
        data=parsed_json(raw);valid=schema_ok(data,workload)
        elapsed=time.perf_counter()-started
        result={'workload':workload,'video':window['video'],'start':window['start'],'end':window['end'],
          'frame_count':len(images),'frame_times':window['frame_times'],'shuffle':window['shuffle'] if workload=='temporal' else None,
          'prompt_sha256':sha256(prompt.encode()).hexdigest(),'schema_valid':valid,'raw_output':raw,'parsed':data,
          'elapsed_seconds':elapsed,'generation_seconds':generation_seconds,'generated_tokens':int(token_ids.shape[1]),
          'hit_token_limit':int(token_ids.shape[1])>=limit,
          'peak_allocated_bytes':torch.cuda.max_memory_allocated(),'peak_reserved_bytes':torch.cuda.max_memory_reserved(),
          'completed_at':datetime.now(timezone.utc).isoformat()}
    result['sampled_device_peak_bytes']=memory.peak
    return result


def main(args):
    torch.set_num_threads(4);torch.manual_seed(0);torch.cuda.set_device(0)
    protocol=json.loads((OUT/'protocol.json').read_text())
    digest=sha256((OUT/'protocol.json').read_bytes()).hexdigest()
    assert digest==(OUT/'protocol.sha256').read_text().strip(),'Protocol changed after reference freeze'
    cfg=protocol['models'][args.model]
    destination=OUT/'results'/args.model;destination.mkdir(parents=True,exist_ok=True)
    free,total=torch.cuda.mem_get_info();baseline=total-free
    started=time.monotonic()
    processor=AutoProcessor.from_pretrained(cfg['id'],revision=cfg['revision'],cache_dir=cfg['cache'],local_files_only=True,
      min_pixels=128*32*32,max_pixels=512*512)
    model=AutoModelForImageTextToText.from_pretrained(cfg['id'],revision=cfg['revision'],cache_dir=cfg['cache'],local_files_only=True,
      dtype=torch.bfloat16,low_cpu_mem_usage=True,attn_implementation='sdpa').to('cuda').eval()
    torch.cuda.synchronize()
    metadata={'model':args.model,**cfg,'protocol_sha256':digest,'load_seconds':time.monotonic()-started,
      'transformers':transformers.__version__,'torch':torch.__version__,'cuda':torch.version.cuda,
      'device':torch.cuda.get_device_name(),'device_total_bytes':total,'other_process_device_baseline_bytes':baseline,
      'parameters':sum(p.numel() for p in model.parameters()),'dtype':'bfloat16','attention':'sdpa',
      'model_resident_allocated_bytes':torch.cuda.memory_allocated(),'run_started_at':datetime.now(timezone.utc).isoformat()}
    (destination/'model.json').write_text(json.dumps(metadata,indent=2))
    for workload in ['standard','temporal']:
        windows=[w for w in protocol['windows'] if workload=='standard' or w['five_frames']]
        path=destination/f'{workload}.jsonl'
        done={(r['video'],r['start']) for r in map(json.loads,path.read_text().splitlines())} if path.exists() else set()
        torch.cuda.empty_cache()
        warmup=infer(model,processor,next(w for w in windows if w['five_frames']),workload)
        (destination/f'{workload}-warmup.json').write_text(json.dumps(warmup,indent=2))
        count=0
        for window in windows:
            if (window['video'],window['start']) in done: continue
            try: row=infer(model,processor,window,workload)
            except Exception as error:
                row={'workload':workload,'video':window['video'],'start':window['start'],'end':window['end'],
                     'frame_count':len(window['frames']),'schema_valid':False,'error':str(error),'completed_at':datetime.now(timezone.utc).isoformat()}
                torch.cuda.empty_cache()
            row.update(model=args.model,model_id=cfg['id'],revision=cfg['revision'],protocol_sha256=digest)
            with path.open('a') as output: output.write(json.dumps(row)+'\n');output.flush();os.fsync(output.fileno())
            count+=1
            print(json.dumps({'model':args.model,'workload':workload,'completed':count,'total':len(windows),
              'video':row['video'],'start':row['start'],'valid':row['schema_valid'],'seconds':row.get('elapsed_seconds'),
              'peak_allocated_GiB':row.get('peak_allocated_bytes',0)/2**30,'error':row.get('error')}),flush=True)
    print(json.dumps({'model':args.model,'state':'completed'}),flush=True)

if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--model',required=True,choices=['qwen3-vl-2b','qwen3-vl-4b']);main(parser.parse_args())
