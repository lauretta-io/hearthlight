"""Eight evenly spaced samples in each ten-second camera window."""
from pathlib import Path
from datetime import datetime, timezone
from hashlib import sha256
import json
import subprocess

SOURCE=Path('/home/lauretta/hearthlight/var/vlm-comparison')
OUT=Path('/home/lauretta/hearthlight/var/qwen4b-8f-10s-20261112')
OUT.mkdir(exist_ok=True);(OUT/'frames').mkdir(exist_ok=True)
original=json.loads((SOURCE/'input-manifest.json').read_text())
video=next(v for v in original['videos'] if v['key']=='video-091517')
base=video['windows'][0]['prompt']
items=base.split('ANOMALOUS ITEMS:\n',1)[1].split('\n\nANOMALOUS ACTIVITIES:',1)[0]
activities=base.split('ANOMALOUS ACTIVITIES:\n',1)[1].split('\n\nInstructions:',1)[0]
windows=[]
for index in range(6):
 start=4+10*index;end=start+10
 times=[start+(i+.5)*1.25 for i in range(8)]
 frames=[]
 for i,t in enumerate(times):
  p=OUT/'frames'/f'window-{index:02d}-frame-{i:02d}.jpg'
  if not p.exists():
   subprocess.run(['ffmpeg','-hide_banner','-loglevel','error','-ss',f'{t:.6f}','-i',str(SOURCE/'inputs'/'video-091517.mov'),
    '-frames:v','1','-vf','scale=640:-2','-q:v','2','-y',str(p)],check=True)
  frames.append(str(p.relative_to(OUT)))
 prompt=original['template'].format(frames_count=8,input_details='\n'.join(f'Frame {i}: source video time {t:.3f} seconds' for i,t in enumerate(times)),
  anomaly_object_list=items,anomaly_activity_list=activities).replace('Each frame is 1 second apart.','Each frame is 1.25 seconds apart; eight samples represent one ten-second window.')
 windows.append({'index':index,'start':start,'end':end,'frame_times':times,'frames':frames,'standard_prompt':prompt})
manifest={'created_at':datetime.now(timezone.utc).isoformat(),'model_id':'Qwen/Qwen3-VL-4B-Instruct',
 'revision':'ebb281ec70b05090aa6165b016eac8ec08e71b17','video':{'key':video['key'],'name':video['name'],'file_id':video['file_id']},
 'source_interval':[4,64],'source_selection':'Quieter of the supplied recordings, with normal pedestrians and street cleaning; not an empty scene. Avoids player controls and browser navigation.',
 'sample_fps':.8,'frames_per_request':8,'window_seconds':10,'image_width':640,'sample_policy':'Eight bin-centered samples, 1.25 seconds apart, in each non-overlapping ten-second window.',
 'workloads':{'standard':'Same inherited scoring prompt; 1024 output-token cap; six one-feed requests.',
 'scene_person':'Unchanged live scene/person prompt and real YOLO/IoU tracks. ReID person IDs are null in this isolated test; 2048 output-token cap. Two synchronized logical feeds replay the same source video, six windows each, requests arriving every ten seconds.'},
 'timing':'Processing includes JPEG read, optional YOLO detection/tracking and annotation, prompt preprocessing, transfer, generation, decoding and validation. Excludes initial model load and ten-second capture interval. Scene/person does not run TransReID or SigLIP.',
 'warmups_per_workload':1,'dtype':'bfloat16','attention':'sdpa','min_pixels':128*32*32,'max_pixels':256*32*32,'windows':windows}
p=OUT/'manifest.json';assert not p.exists(),'Do not overwrite an existing run manifest';p.write_text(json.dumps(manifest,indent=2));(OUT/'manifest.sha256').write_text(sha256(p.read_bytes()).hexdigest()+'\n')
print('Prepared six ten-second windows, eight frames each, at 640px width.')
