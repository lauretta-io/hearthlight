"""Validate the capacity probe and export its requested timing summary."""
from pathlib import Path
from hashlib import sha256
import csv
import json
import math
import statistics

ROOT=Path('/home/lauretta/hearthlight/var/qwen4b-8f-10s-20261112')
main=json.loads((ROOT/'summary.json').read_text());batch=json.loads((ROOT/'batch2-summary.json').read_text())
rows={k:[json.loads(s) for s in (ROOT/(k+'.jsonl')).read_text().splitlines()] for k in ['standard','scene_person','batch2']}
assert len(rows['standard'])==6 and len(rows['scene_person'])==12 and len(rows['batch2'])==6
for name in ['standard','scene_person']:
 records=rows[name];stats=main['workloads'][name]
 mean=math.fsum(r['processing_seconds'] for r in records)/len(records)
 assert abs(mean-stats['mean_processing_seconds'])<1e-10
 assert all(r['frame_count']==8 and r['schema_valid'] and not r['hit_token_limit'] for r in records)
 assert all(r['peak_allocated_bytes']<=r['peak_reserved_bytes'] for r in records)
 assert abs(stats['two_feed_utilization_fraction']-2*mean/10)<1e-10
 for r in records:
  assert abs(r['generated_tokens']/r['generation_seconds']-r['generation_tokens_per_second'])<1e-10
for r in rows['scene_person']:
 assert r['arrival_seconds']==r['window_index']*10
 assert abs((r['finished_seconds']-r['arrival_seconds'])-r['completion_lag_seconds'])<1e-9
 assert r['deadline_met']==(r['completion_lag_seconds']<=10)
for r in rows['batch2']:
 assert r['batch_size']==2 and r['frames_per_stream']==8 and len(r['responses'])==2
 assert all(s['schema_valid'] and not s['hit_token_limit'] for s in r['responses'])
 assert r['output_tokens']==sum(s['actual_output_tokens'] for s in r['responses'])
 assert all(s['actual_output_tokens']<=r['generation_steps'] for s in r['responses'])
 assert r['deadline_met']==(r['completion_lag_seconds']<=10)
assert abs(math.fsum(r['processing_seconds'] for r in rows['batch2'])/6-batch['mean_pair_processing_seconds'])<1e-10
assert sum(r['deadline_met'] for r in rows['batch2'])==batch['pairs_within_10_seconds']

profiles=[]
for name,title in [('standard','Scoring prompt, single request'),('scene_person','Full scene/person prompt, single request')]:
 d=main['workloads'][name]
 profiles.append({'profile':name,'description':title,'unit':'one 8-frame request','measured_requests':d['requests'],
  'mean_seconds':d['mean_processing_seconds'],'p95_seconds':d['p95_processing_seconds'],'max_seconds':d['max_processing_seconds'],
  'output_tokens_per_second':d['median_generation_tokens_per_second'],'token_rate_scope':'single-request median; generation includes prefill',
  'mean_output_tokens':d['mean_generated_tokens'],'peak_allocated_gib':d['peak_allocated_gib'],
  'sampled_device_peak_gib':d['sampled_device_peak_gib'],'valid_responses':d['valid_responses']})
profiles.insert(1,{'profile':'batch2','description':'Scoring prompt, batch size 2','unit':'two 8-frame requests together','measured_requests':12,
 'mean_seconds':batch['mean_pair_processing_seconds'],'p95_seconds':batch['p95_pair_processing_seconds'],
 'max_seconds':max(r['processing_seconds'] for r in rows['batch2']),
 'output_tokens_per_second':batch['median_aggregate_output_tokens_per_second'],'token_rate_scope':'aggregate across both responses; excludes EOS padding',
 'mean_output_tokens':statistics.mean(r['output_tokens'] for r in rows['batch2']),
 'peak_allocated_gib':batch['peak_allocated_gib'],'sampled_device_peak_gib':batch['sampled_device_peak_gib'],'valid_responses':12})
final={'model':main['model_id'],'revision':main['revision'],'source':json.loads((ROOT/'manifest.json').read_text())['video'],
 'configuration':{'frames_per_feed':8,'window_seconds':10,'sample_fps':.8,'width_pixels':640,'dtype':'bfloat16','attention':'sdpa'},
 'profiles':profiles,'two_feed_batch_test':batch,'detailed_serial_test':main['workloads']['scene_person'],
 'verdict':'Rough two-feed cadence is feasible for short scoring-format reports with shared batch size 2 in this one-minute probe. The current full scene/person reporting workload does not keep pace.',
 'limitations':main['limitations']+['Batch size 2 covers only scoring-format reports, not full individual-person reporting.',
  'The probe validates response structure and speed, not behavior/scoring accuracy or full prompt compliance.',
  'Keeping pace is one analysis every ten seconds per feed, with processing delay after each ten-second window closes.',
  'Live deployment would need shared batching and asynchronous capture; this probe did not change the live deployment.'],
 'validation':'All recorded timings, token-rate arithmetic, response counts, allocated/reserved bounds and deadline calculations checked.'}
(ROOT/'final-summary.json').write_text(json.dumps(final,indent=2))
with (ROOT/'comparison.csv').open('w',newline='') as f:
 writer=csv.DictWriter(f,fieldnames=list(profiles[0]));writer.writeheader();writer.writerows(profiles)
with (ROOT/'request-timings.csv').open('w',newline='') as f:
 fields=['workload','stream','window_index','frame_count','track_count','processing_seconds','generation_seconds','generated_tokens','generation_tokens_per_second','input_tokens','visual_tokens','schema_valid','peak_allocated_bytes','queue_wait_seconds','completion_lag_seconds','deadline_met']
 writer=csv.DictWriter(f,fieldnames=fields,extrasaction='ignore');writer.writeheader();writer.writerows(rows['standard']+rows['scene_person'])
with (ROOT/'batch-timings.csv').open('w',newline='') as f:
 fields=['batch_index','batch_size','frames_per_stream','processing_seconds','generation_seconds','output_tokens','generation_steps','aggregate_output_tokens_per_second','all_valid','peak_allocated_bytes','queue_wait_seconds','completion_lag_seconds','deadline_met']
 writer=csv.DictWriter(f,fieldnames=fields,extrasaction='ignore');writer.writeheader();writer.writerows(rows['batch2'])
text=['Qwen3-VL-4B: 8 frames per 10-second window — 2026-11-12','',
 'RTX 4080 16 GB; bfloat16; 640-pixel input width; one resident model.',
 'One minute of the Japanese street recording, camera-only frames. Ordinary pedestrian/street-cleaning activity; not an empty-room test.','',
 f"{'Workload':<43}{'Mean':>10}{'P95 / max':>12}{'Output tok/s':>15}{'VRAM GiB':>12}"]
for r in profiles:text.append(f"{r['description']:<43}{r['mean_seconds']:>9.2f}s{r['p95_seconds']:>11.2f}s{r['output_tokens_per_second']:>15.1f}{r['peak_allocated_gib']:>12.2f}")
text += ['', 'Units matter: single rows time one request. The batch row times BOTH video responses together; its token rate is aggregated across both.',
 'P95 is nearest-rank; with these small samples it equals the slowest measured request or batch.',
 '', 'Two-feed capacity',
 f"- Serial scoring: {main['workloads']['standard']['mean_processing_seconds']*2:.2f}s of work per ten-second cycle, slightly over budget.",
 f"- Batch size 2 scoring: {batch['mean_pair_processing_seconds']:.2f}s mean per pair; {batch['pairs_within_10_seconds']}/6 pairs completed before the next ten-second deadline.",
 f"- Maximum queue wait: {batch['max_queue_wait_seconds']:.2f}s. Worst pair completion lag: {batch['max_pair_completion_lag_seconds']:.2f}s after window closure.",
 f"- Mean busy fraction for two batched feeds: {batch['two_feed_utilization_fraction']*100:.1f}%. This is a short probe, not a sustained guarantee.",
 f"- Detailed scene/person reports: {main['workloads']['scene_person']['mean_processing_seconds']:.2f}s mean each; {main['workloads']['scene_person']['deadlines_met']}/12 met the next-window deadline.",
 f"- Detailed-report queue reached {main['workloads']['scene_person']['max_queue_wait_seconds']:.2f}s; processing the two one-minute logical feeds took {main['workloads']['scene_person']['replay_finished_seconds']:.2f}s after their first windows became available.",
 '', 'Why report length matters',
 f"- Short scoring-format responses averaged {main['workloads']['standard']['mean_generated_tokens']:.0f} generated tokens.",
 f"- Full scene/person responses averaged {main['workloads']['scene_person']['mean_generated_tokens']:.0f} tokens for 13–23 detector/IoU tracklets; those are not necessarily distinct people.",
 '- No token-limit hits or runtime errors were observed. Eight frames used 1,760 visual tokens; full scene/person input remained below 5,000 total tokens.',
 '', 'Scope and deployment',
 '- Batched test uses two phase-offset copies of the SAME recording, not two independent cameras.',
 '- VRAM above is peak PyTorch allocation, including model weights; sampled whole-device peak for the batched test was '+f"{batch['sampled_device_peak_gib']:.2f} GiB, including the other GPU workload.",
 '- Timings include image read, preprocessing, transfer, generation, decode and validation. The detailed mode also includes YOLO/IoU tracking and box annotation.',
 '- TransReID and SigLIP are excluded; full pipeline deployment needs additional headroom.',
 '- Source frames were already available. Model cold load and the ten-second capture interval are excluded; both streams need asynchronous capture for a live deployment.',
 '- JSON structure checks do not establish correct scores, factual behaviors or full scoring-prompt compliance.',
 '- Current live deployment remains unchanged: Qwen3-VL-2B logging was restored after the probe.',
 '', 'Practical conclusion: one shared 4B model with batch size 2 can roughly keep pace for brief outputs. Fresh detailed descriptions for every track are too slow at this cadence. Compact scene/changed-person updates are the sensible optimization target, rather than repeating full reports.',
 '', 'Raw evidence: manifest.json, model.json, standard.jsonl, scene_person.jsonl, batch2.jsonl, summary.json and batch2-summary.json.']
(ROOT/'benchmark-summary.txt').write_text('\n'.join(text)+'\n')
print('\n'.join(text[:19]));print('Validation passed.')
