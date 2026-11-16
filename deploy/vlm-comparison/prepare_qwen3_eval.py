"""Freeze provisional visual references and a paired Qwen3 evaluation protocol."""
from pathlib import Path
from datetime import datetime, timezone
from hashlib import sha256
import json
import random

ROOT = Path('/home/lauretta/hearthlight/var/vlm-comparison')
OUT = Path('/home/lauretta/hearthlight/var/qwen3-evaluation-20261112')
OUT.mkdir(exist_ok=True)
source = json.loads((ROOT/'input-manifest.json').read_text())
# Single-rater visual review of the actual source frames, before reading new
# model outputs. These are provisional labels, not human-adjudicated truth.
C, B, U, M, A = 'crouched', 'bent', 'upright', 'moving', 'absent'
a_states = [[C]*5,[C]*5,[C]*5,[B,B,C,C,C],[C,C,B,U,B],
            [B,U,B,B,None],[A]*5,[A]*5,[A]*5,[A,M,M,M,B],
            [B,U,B,C,C],[C]*5,[C,C,B,U,M],[M]]
a_actions = [['crouching','handling_object']]*3 + [
    ['bending','crouching','handling_object'],
    ['crouching','bending','standing','handling_object'],
    ['bending','standing','handling_object'], [],[],[],
    ['walking','bending','handling_object'],
    ['bending','standing','crouching','handling_object'],
    ['crouching','handling_object'],
    ['crouching','bending','standing','walking'],['walking']]
b_states = [[U]*5,[U]*5,[U]*5,[U,U,U,U,B],[B]*5,[B]*5,[B]*5,
            [B,B,B,U,U],[U]*5,[U,B,B,B,B],[U,B,B,B,U],[B,B,U,U,U],
            [U]*4+[None],[None]*5]
b_actions = [['standing','handling_object']]*3 + [
    ['standing','walking','bending','handling_object'],
    ['bending','handling_object'],['bending','handling_object'],
    ['bending','handling_object'],['bending','standing','handling_object'],
    ['standing','handling_object'],['standing','bending','handling_object'],
    ['standing','bending','handling_object'],['standing','bending','handling_object'],
    ['standing','handling_object'],[]]
c_states = [[M]*5 for _ in range(8)] + [[M,M,M,None,None]] + [[A]*5 for _ in range(4)] + [[A]*3]
c_actions = [['driving'] for _ in range(9)] + [[] for _ in range(5)]
actors = {
 'video-091312': 'the man in a gray T-shirt and shorts beside the bicycle in the right foreground',
 'video-091517': 'the man in a navy shirt and beige trousers handling a long hose or tool near the lower right/center of the road',
 'video-091736': 'the large blue utility truck with a metal mesh cargo enclosure and amber warning lights',
}
TEMPORAL = '''The five images are SHUFFLED, not chronological. Image IDs are their presentation positions 0,1,2,3,4.
Reconstruct the most plausible earliest-to-latest order using visible physical motion. Ignore remaining screen overlays.
Focus actor: {actor}.
For EACH presented image give the focus actor's visible state. Allowed states:
- absent: focus actor not visibly identifiable (including out of view or fully occluded)
- upright: person standing upright, not walking/running
- bent: person bent forward at the waist
- crouched: person squatting or sitting low with deeply bent knees
- moving: person walking/running, or a vehicle visibly translating across the sequence
- stationary: a vehicle that stays in place
- unclear: state cannot be determined.
Also list every action visibly performed by the FOCUS ACTOR anywhere in the sequence, using ONLY:
walking, running, bending, crouching, standing, handling_object, driving.
A vehicle's presence or flashing lights alone do not establish driving. Do not attribute other actors' actions to the focus actor.
Respond ONLY with JSON of this form, with all five distinct image IDs covered:
{{"order":[0,1,2,3,4],"frame_states":[{{"image_id":0,"state":"upright"}},{{"image_id":1,"state":"upright"}},{{"image_id":2,"state":"upright"}},{{"image_id":3,"state":"upright"}},{{"image_id":4,"state":"upright"}}],"actions":["standing"]}}'''
rows=[]
for vi,v in enumerate(source['videos']):
 for wi,w in enumerate(v['windows']):
  states=[a_states,b_states,c_states][vi][wi]
  actions=[a_actions,b_actions,c_actions][vi][wi]
  camera_only=not (vi==1 and w['start']>=60)
  driving=(True if vi==0 else w['start'] in [30,35,40] if vi==1 else w['start']<=40)
  events={'recklessness':False,'driving':driving,'hurt':False,'taking items':None if vi==0 and w['start'] in [20,25,50] else False}
  permutation=list(range(5))
  rng=random.Random(int(sha256(f"qwen3-eval:{v['key']}:{w['start']}".encode()).hexdigest()[:16],16));rng.shuffle(permutation)
  if permutation==list(range(5)):permutation=permutation[1:]+permutation[:1]
  full=len(w['frames'])==5
  rows.append({'video':v['key'], 'start':w['start'],'end':w['end'],'frames':w['frames'],
    'frame_times':w['frame_times'],'standard_prompt':w['prompt'],'standard_prompt_sha256':w['prompt_sha256'],
    'focus_actor':actors[v['key']], 'temporal_prompt':TEMPORAL.format(actor=actors[v['key']]),
    'shuffle':permutation,'correct_order':sorted(range(5),key=lambda i:permutation[i]),
    'five_frames':full,'camera_only':camera_only,
    'event_accuracy_eligible':full and camera_only,
    'state_accuracy_eligible':full and camera_only,
    'action_accuracy_eligible':full and camera_only and any(s not in [A,None] for s in states),
    'order_accuracy_eligible':full and camera_only and not (vi==0 and w['start']==0),
    'reference':{'events':events,'states_chronological':states,'actions':actions},
    'notes':('Browser navigation/mixed camera and web page; excluded from accuracy.' if not camera_only else
      'Partial final window; excluded from five-frame metrics.' if not full else
      'Initial player popup; excluded from ordering accuracy.' if vi==0 and w['start']==0 else
      'Bike manipulation does not clearly establish taking a loose item; that event label is unknown.' if events['taking items'] is None else '')})
protocol={
 'created_at':datetime.now(timezone.utc).isoformat(),'reference_status':'provisional_assistant_visual_review_not_human_verified',
 'source_manifest_sha256':sha256((ROOT/'input-manifest.json').read_bytes()).hexdigest(),
 'reference_method':'Single-rater visual inspection of all source-frame contact sheets, plus detailed actor crops, frozen before inspecting new benchmark outputs.',
 'event_definitions':{'recklessness':'Clearly visible unsafe/reckless conduct; normal proximity or routine road crossing alone does not qualify.',
 'driving':'A motor vehicle visibly translates between frames; a parked vehicle or flashing lights alone does not qualify.',
 'hurt':'Visible injury/fall/impact evidence; bending, crouching, or repair work alone does not qualify.',
 'taking items':'Clear pickup/removal/carrying away of a loose item; repair/manipulation alone is insufficient. Ambiguous bicycle handling is unknown.'},
 'image_policy':{'standard':'Original saved frames, unchanged standard Hearthlight prompt. Final partial windows are run but excluded from five-frame metrics.',
 'temporal':'Original frames in deterministic shuffled order; top 32 pixels and bottom 48 pixels masked for clocks/player bars; Japan weather widget masked. No frame times supplied.'},
 'performance_policy':{'timing':'Five decoded RGB frames ready through preprocessing, H2D transfer, generation, decode and schema validation. CUDA synchronized. Excludes model load and video decode.',
 'warmups':1,'standard_max_new_tokens':1024,'temporal_max_new_tokens':512,'dtype':'bfloat16','attention':'sdpa',
 'peak_vram':'PyTorch peak allocated and reserved bytes, including resident weights; sampled device-wide peak and baseline also retained.',
 'percentile':'Nearest-rank P95 on successful schema-valid five-frame requests; invalid responses reported separately; all-call P95 also retained.'},
 'models':{'qwen3-vl-2b':{'id':'Qwen/Qwen3-VL-2B-Instruct','revision':'89644892e4d85e24eaac8bacfd4f463576704203','cache':'/oldmodels/huggingface/hub'},
 'qwen3-vl-4b':{'id':'Qwen/Qwen3-VL-4B-Instruct','revision':json.loads((ROOT/'models/manifest.json').read_text())['Qwen/Qwen3-VL-4B-Instruct']['revision'],'cache':'/bench/models/huggingface/hub'}},
 'windows':rows}
p=OUT/'protocol.json';assert not p.exists(),'Protocol already frozen; do not overwrite after viewing model outputs.'
p.write_text(json.dumps(protocol,indent=2));(OUT/'protocol.sha256').write_text(sha256(p.read_bytes()).hexdigest()+'\n')
print(json.dumps({'windows':len(rows),'five_frame_windows':sum(r['five_frames'] for r in rows),'event_accuracy_windows':sum(r['event_accuracy_eligible'] for r in rows),'order_accuracy_windows':sum(r['order_accuracy_eligible'] for r in rows),'protocol_sha256':sha256(p.read_bytes()).hexdigest()}))
