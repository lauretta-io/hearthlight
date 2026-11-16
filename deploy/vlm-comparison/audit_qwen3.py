"""Independent set- and source-index-based checks of reported benchmark metrics."""
from pathlib import Path
import json
import re
import numpy as np

root=Path('/evaluation');s=json.loads((root/'summary.json').read_text());p=json.loads((root/'protocol-v2.json').read_text())
windows={(w['video'],w['start']):w for w in p['windows']};checks=[]
for model,result in s['results'].items():
 standard=[json.loads(x) for x in (root/'results'/model/'standard.jsonl').read_text().splitlines()]
 temporal=[json.loads(x) for x in (root/'results'/model/'temporal.jsonl').read_text().splitlines()]
 truth=set();guesses=set();known=set()
 for row in standard:
  key=(row['video'],row['start']);w=windows[key]
  if not w['event_accuracy_eligible']:continue
  tokens=re.split('[,;]',str((row.get('parsed') or {}).get('visible_activities','')).lower().replace('_',' '))
  tokens={x.strip().rstrip('.') for x in tokens};tokens |= {'recklessness'} if tokens&{'reckless','reckless driving'} else set()
  if 'reckless driving' in tokens:tokens.add('driving')
  for label,actual in w['reference']['events'].items():
   item=(*key,label)
   if actual is None:continue
   known.add(item)
   if actual:truth.add(item)
   if label in tokens:guesses.add(item)
 tp=len(truth&guesses);fp=len(guesses-truth);fn=len(truth-guesses)
 assert (tp,fp,fn)==tuple(result['accuracy']['event_counts'][k] for k in ['tp','fp','fn'])
 assert abs(2*tp/(2*tp+fp+fn)-result['accuracy']['event_micro_f1'])<1e-12
 assert len(truth)==25 and len(known)==149
 exact=0;pair_correct=0;orders=0;transitions=0;trans_correct=0;unchanged_baseline_pairs=0;action_correct=0;action_total=0;visible_correct=0;visible_total=0
 for row in temporal:
  w=windows[(row['video'],row['start'])];data=row.get('parsed') or {};order=data.get('order')
  valid=isinstance(order,list) and len(order)==5 and all(type(i) is int for i in order) and set(order)==set(range(5))
  if w['order_accuracy_eligible']:
   orders+=1;source_order=[w['shuffle'][i] for i in order] if valid else []
   exact+=source_order==list(range(5))
   for a in range(5):
    for b in range(a+1,5):
     pair_correct+=bool(valid and source_order.index(a)<source_order.index(b))
     unchanged_baseline_pairs+=w['shuffle'].index(a)<w['shuffle'].index(b)
  if w['action_accuracy_eligible']:
   action_total+=1
   vocabulary=['walking','running','bending','crouching','standing','handling_object','driving']
   expected=sum(1<<vocabulary.index(x) for x in w['reference']['actions'])
   supplied=data.get('actions');mask=0;legal=isinstance(supplied,list)
   for action in supplied if isinstance(supplied,list) else []:
    if action not in vocabulary:legal=False;continue
    mask |= 1<<vocabulary.index(action)
   action_correct+=bool(legal and mask==expected)
  if w['state_accuracy_eligible']:
   state_rows=data.get('frame_states',[]);states={};counts={}
   for frame in state_rows:
    i=frame.get('image_id');counts[i]=counts.get(i,0)+1
    if frame.get('state') in ['absent','upright','bent','crouched','moving','stationary','unclear']:states[i]=frame['state']
   for i in list(states):
    if counts[i]!=1:del states[i]
   lookup={source:presented for presented,source in enumerate(w['shuffle'])}
   refs=w['reference']['states_chronological']
   for index,ref in enumerate(refs):
    if ref is not None and ref!='absent':
     visible_total+=1;visible_correct+=states.get(lookup[index])==ref
   for index in range(4):
    a,b=refs[index:index+2]
    if a is None or b is None or a==b or 'absent' in [a,b]:continue
    transitions+=1;trans_correct+=(states.get(lookup[index]),states.get(lookup[index+1]))==(a,b)
 assert action_total==31 and visible_total==151
 assert action_correct==result['accuracy']['denominators_and_correct_counts']['action_correct']
 assert visible_correct==result['accuracy']['denominators_and_correct_counts']['visible_states_correct']
 assert orders==37 and transitions==19
 assert exact==result['accuracy']['denominators_and_correct_counts']['order_exact_correct']
 assert pair_correct==result['accuracy']['denominators_and_correct_counts']['order_pairs_correct']
 assert trans_correct==result['accuracy']['denominators_and_correct_counts']['visible_changed_pairs_correct']
 for workload,rows in [('standard',standard),('temporal',temporal)]:
  full=[x for x in rows if x['frame_count']==5];valid=[x for x in full if x['schema_valid']]
  measured=result['performance'][workload]
  assert len(full)==40
  q=float(np.percentile([x['elapsed_seconds'] for x in valid],95,method='inverted_cdf'))
  assert abs(q-measured['p95_valid_json_seconds'])<1e-10
  assert abs(np.percentile([x['elapsed_seconds'] for x in full],95,method='inverted_cdf')-measured['p95_all_requests_seconds'])<1e-10
  assert all(x['peak_allocated_bytes']<=x['peak_reserved_bytes'] for x in full)
 checks.append({'model':model,'status':'passed','event_confusion':{'tp':tp,'fp':fp,'fn':fn},'known_event_labels':len(known),
  'source_index_order_cases':orders,'exact_order_correct':exact,'pairwise_correct':pair_correct,
  'unchanged_input_order_baseline_pairs':unchanged_baseline_pairs,'action_exact_matches':action_correct,'visible_frame_state_matches':visible_correct,'visible_state_changes':transitions,'state_changes_correct':trans_correct,
  'latency_check':'NumPy inverted_cdf agrees with independent nearest-rank calculation','memory_check':'allocated <= reserved on every request'})
(root/'validation.json').write_text(json.dumps({'status':'share_with_caveats','checks':checks,'references':'provisional_not_human_verified'},indent=2))
print(json.dumps(checks,indent=2))
