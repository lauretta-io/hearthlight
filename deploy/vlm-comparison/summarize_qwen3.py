"""Score frozen provisional references; never relabel in response to model output."""
from collections import Counter
from hashlib import sha256
import csv
import json
import math
from pathlib import Path
import statistics

ROOT=Path('/home/lauretta/hearthlight/var/qwen3-evaluation-20261112')
ACTIVITIES=['recklessness','driving','hurt','taking items']
STATES={'absent','upright','bent','crouched','moving','stationary','unclear'}
ACTIONS={'walking','running','bending','crouching','standing','handling_object','driving'}

def ratio(a,b): return a/b if b else None

def percentile(values,p=.95):
    return sorted(values)[math.ceil(len(values)*p)-1] if values else None

def f1(c): return ratio(2*c['tp'],2*c['tp']+c['fp']+c['fn'])

def predictions(data):
    value=data.get('visible_activities') if isinstance(data,dict) else None
    if not isinstance(value,str): return set()
    tokens={s.lower().strip().strip('.').replace('_',' ') for s in value.replace(';',',').split(',')}
    labels={a for a in ACTIVITIES if a in tokens}
    if 'reckless' in tokens: labels.add('recklessness')
    if 'reckless driving' in tokens: labels.update(['recklessness','driving'])
    return labels

def frame_states(data):
    rows=data.get('frame_states') if isinstance(data,dict) else None
    out={};seen=set()
    for s in rows if isinstance(rows,list) else []:
        if not isinstance(s,dict) or type(s.get('image_id')) is not int: continue
        i=s['image_id']
        if i in seen: out.pop(i,None);continue
        seen.add(i)
        if i in range(5) and isinstance(s.get('state'),str) and s.get('state') in STATES: out[i]=s['state']
    return out

def perf(rows):
    full=[r for r in rows if r['frame_count']==5]
    valid=[r for r in full if r['schema_valid'] and 'elapsed_seconds' in r]
    timed=[r for r in full if 'elapsed_seconds' in r]
    rates=[r['generated_tokens']/r['generation_seconds'] for r in valid if r.get('generation_seconds',0)>0]
    return {'five_frame_requests':len(full),'valid_json':len(valid),'json_completion_rate':ratio(len(valid),len(full)),
      'p95_valid_json_seconds':percentile([r['elapsed_seconds'] for r in valid]),
      'p95_all_requests_seconds':percentile([r['elapsed_seconds'] for r in timed]),
      'median_valid_json_seconds':statistics.median([r['elapsed_seconds'] for r in valid]) if valid else None,
      'median_generated_tokens_per_second':statistics.median(rates) if rates else None,
      'peak_allocated_gib':max((r.get('peak_allocated_bytes',0)/2**30 for r in full),default=0),
      'peak_reserved_gib':max((r.get('peak_reserved_bytes',0)/2**30 for r in full),default=0),
      'sampled_device_peak_gib':max((r.get('sampled_device_peak_bytes',0)/2**30 for r in full),default=0),
      'token_limit_responses':sum(r.get('hit_token_limit',False) for r in full),'runtime_errors':sum('error' in r for r in full)}

def main():
    p=ROOT/'protocol-v2.json';protocol=json.loads(p.read_text());digest=sha256(p.read_bytes()).hexdigest()
    assert digest==(ROOT/'protocol-v2.sha256').read_text().strip()
    references={(w['video'],w['start']):w for w in protocol['windows']}
    results={};cases=[];class_rows=[];flat=[]
    for model in protocol['models']:
        directory=ROOT/'results'/model
        workloads={}
        for workload in ['standard','temporal']:
            rows=[json.loads(s) for s in (directory/f'{workload}.jsonl').read_text().splitlines()]
            keyed={(r['video'],r['start']):r for r in rows}
            assert len(keyed)==len(rows),'Duplicate result windows'
            expected={key for key,w in references.items() if workload=='standard' or w['five_frames']}
            assert set(keyed)==expected,(model,workload,'Missing or extra windows')
            for key,row in keyed.items():
                expected_digest = digest if workload=='temporal' and row['video']=='video-091517' else protocol['parent_protocol_sha256']
                assert row['protocol_sha256']==expected_digest
                prompt=references[key]['standard_prompt'] if workload=='standard' else references[key]['temporal_prompt']
                assert row['prompt_sha256']==sha256(prompt.encode()).hexdigest(), 'Unrepaired prompt or incomparable case'

            workloads[workload]=keyed
        confusion={a:Counter(tp=0,fp=0,fn=0,tn=0,unknown=0) for a in ACTIVITIES}
        totals=Counter()
        for key,w in references.items():
            base=workloads['standard'][key];pred=predictions(base.get('parsed'))
            if w['event_accuracy_eligible']:
                totals['event_windows']+=1
                for activity,truth in w['reference']['events'].items():
                    if truth is None: confusion[activity]['unknown']+=1;continue
                    guessed=activity in pred
                    outcome='tp' if truth and guessed else 'fn' if truth else 'fp' if guessed else 'tn'
                    confusion[activity][outcome]+=1
                    cases.append({'model':model,'workload':'standard','video':key[0],'start':key[1],
                      'metric':'event','reference':activity+':'+str(truth),'prediction':str(guessed),'correct':truth==guessed})
            if not w['five_frames']: continue
            row=workloads['temporal'][key];data=row.get('parsed') or {};states=frame_states(data)
            chronological=[states.get(w['shuffle'].index(i)) for i in range(5)]
            actions=data.get('actions');pred_actions=set(actions) if isinstance(actions,list) and all(isinstance(a,str) and a in ACTIONS for a in actions) else None
            if w['action_accuracy_eligible']:
                correct=pred_actions==set(w['reference']['actions'])
                totals['action_cases']+=1;totals['action_correct']+=correct
                cases.append({'model':model,'workload':'temporal','video':key[0],'start':key[1],'metric':'action_exact_set',
                  'reference':json.dumps(sorted(w['reference']['actions'])),'prediction':json.dumps(sorted(pred_actions)) if pred_actions is not None else 'invalid','correct':correct})
            truth_states=w['reference']['states_chronological']
            if w['state_accuracy_eligible']:
                for i,truth in enumerate(truth_states):
                    if truth is None: continue
                    totals['states']+=1;totals['states_correct']+=chronological[i]==truth
                    if truth!='absent': totals['visible_states']+=1;totals['visible_states_correct']+=chronological[i]==truth
                for i,(a,b) in enumerate(zip(truth_states,truth_states[1:])):
                    if a is None or b is None: continue
                    correct=chronological[i:i+2]==[a,b]
                    totals['all_pairs']+=1;totals['all_pairs_correct']+=correct
                    if a!=b:
                        totals['changed_pairs']+=1;totals['changed_pairs_correct']+=correct
                        if a!='absent' and b!='absent':
                            totals['visible_changed_pairs']+=1;totals['visible_changed_pairs_correct']+=correct
                            cases.append({'model':model,'workload':'temporal','video':key[0],'start':key[1],'metric':f'transition_{i}_{i+1}',
                              'reference':json.dumps([a,b]),'prediction':json.dumps(chronological[i:i+2]),'correct':correct})
            if w['order_accuracy_eligible']:
                expected=w['correct_order'];order=data.get('order')
                valid=isinstance(order,list) and len(order)==5 and all(type(i) is int for i in order) and sorted(order)==list(range(5))
                totals['order_cases']+=1;totals['order_exact_correct']+=order==expected
                for i in range(5):
                    for j in range(i+1,5):
                        totals['order_pairs']+=1
                        totals['order_pairs_correct']+=bool(valid and order.index(expected[i])<order.index(expected[j]))
                cases.append({'model':model,'workload':'temporal','video':key[0],'start':key[1],'metric':'exact_five_frame_order',
                  'reference':json.dumps(expected),'prediction':json.dumps(order),'correct':order==expected})
        combined=Counter()
        for activity,c in confusion.items():
            combined.update(c)
            class_rows.append({'model':model,'activity':activity,**dict(c),'precision':ratio(c['tp'],c['tp']+c['fp']),
              'recall':ratio(c['tp'],c['tp']+c['fn']),'f1':f1(c),'reference_positives':c['tp']+c['fn']})
        acc={'event_micro_f1':f1(combined),'event_precision':ratio(combined['tp'],combined['tp']+combined['fp']),
          'event_recall':ratio(combined['tp'],combined['tp']+combined['fn']),'event_counts':dict(combined),
          'action_exact_set_accuracy':ratio(totals['action_correct'],totals['action_cases']),
          'visible_frame_state_accuracy':ratio(totals['visible_states_correct'],totals['visible_states']),
          'all_frame_state_accuracy':ratio(totals['states_correct'],totals['states']),
          'state_transition_accuracy':ratio(totals['visible_changed_pairs_correct'],totals['visible_changed_pairs']),
          'transition_accuracy_including_visibility':ratio(totals['changed_pairs_correct'],totals['changed_pairs']),
          'all_adjacent_state_pair_accuracy':ratio(totals['all_pairs_correct'],totals['all_pairs']),
          'exact_five_frame_order_accuracy':ratio(totals['order_exact_correct'],totals['order_cases']),
          'pairwise_order_accuracy':ratio(totals['order_pairs_correct'],totals['order_pairs']),'denominators_and_correct_counts':dict(totals)}
        performance={workload:perf(list(rows.values())) for workload,rows in workloads.items()}
        metadata=json.loads((directory/'model.json').read_text())
        results[model]={'accuracy':acc,'performance':performance,'model':metadata}
        flat.append({'model':model,**{k:v for k,v in acc.items() if type(v) in [int,float] or v is None},
          **{f'{workload}_{k}':v for workload,pf in performance.items() for k,v in pf.items()}})
    summary={'reference_status':protocol['reference_status'],'protocol_sha256':digest,'results':results,
      'limitations':['Single-rater provisional visual labels, not independently human-verified.',
        'Only three related screen recordings; windows are temporally correlated, not independent test videos.',
        'No confirmed positive recklessness, hurt, or taking-items examples; event F1 primarily tests driving and false alarms in other classes.',
        'Action accuracy uses exact action sets for windows with a visible focus actor. State-transition accuracy uses changed adjacent visible-target states, separately from ordering.',
        'Two partial windows are excluded from five-frame performance; two browser-navigation windows are excluded from accuracy; one popup window is excluded from ordering.',
        'P95 uses nearest rank. Both all-request and successful JSON latency are reported; token-limited/invalid outputs are not silently discarded.',
        'VRAM allocated/reserved includes resident model weights; device-wide usage includes the separate DHS service and is reported separately.'],
      'metric_definitions':{'event_micro_f1':'2*TP/(2*TP+FP+FN), pooled four event labels over 38 eligible windows; unknown class-window labels excluded. Underscores normalize to spaces; reckless and reckless driving normalize to recklessness (and driving for the latter).' ,
      'action_exact_set_accuracy':'Exact predicted action-set match over eligible windows with a visible focus actor.',
      'state_transition_accuracy':'Both adjacent predicted states match the reference ordered state pair, on changed pairs with visible targets and known reference states.',
      'exact_five_frame_order_accuracy':'All five shuffled image IDs in the correct chronological order.',
      'pairwise_order_accuracy':'Correct relative order among all 10 pairs per eligible sequence.'}}
    (ROOT/'summary.json').write_text(json.dumps(summary,indent=2))
    for filename,rows in [('comparison.csv',flat),('event-class-metrics.csv',class_rows),('accuracy-cases.csv',cases)]:
        with (ROOT/filename).open('w',newline='') as f:
            writer=csv.DictWriter(f,fieldnames=list(rows[0]));writer.writeheader();writer.writerows(rows)
    print(json.dumps({m:{'accuracy':r['accuracy'],'performance':r['performance']} for m,r in results.items()},indent=2))

if __name__=='__main__': main()
