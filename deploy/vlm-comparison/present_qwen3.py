"""Create the requested compact summary and a reproducible benchmark figure."""
import json
from pathlib import Path
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import numpy as np

ROOT=Path('/evaluation')
s=json.loads((ROOT/'summary.json').read_text());results=s['results'];keys=['qwen3-vl-2b','qwen3-vl-4b']
labels=['Qwen3-VL-2B','Qwen3-VL-4B'];colors=['#0072B2','#D55E00']
a=[results[k]['accuracy'] for k in keys];p=[results[k]['performance'] for k in keys]
fmt=lambda v: 'N/A' if v is None else f'{v:.2f}'
pct=lambda v: 'N/A' if v is None else f'{v*100:.1f}%'
rows=[('Event F1 (window-level micro)',*[f"{x['event_micro_f1']:.3f}" for x in a]),
 ('Action exact-set accuracy (31 windows)',*[pct(x['action_exact_set_accuracy']) for x in a]),
 ('Visible frame-state accuracy (151 frames)',*[pct(x['visible_frame_state_accuracy']) for x in a]),
 ('State-change accuracy (19 visible state changes)',*[pct(x['state_transition_accuracy']) for x in a]),
 ('Exact five-frame order accuracy (37 sequences)',*[pct(x['exact_five_frame_order_accuracy']) for x in a]),
 ('Pairwise order accuracy (370 frame pairs)',*[pct(x['pairwise_order_accuracy']) for x in a])]
for workload,title in [('standard','Standard prompt'),('temporal','Action/order prompt')]:
 rows += [(title+' - P95 completed JSON (s)',*[fmt(x[workload]['p95_valid_json_seconds']) for x in p]),
  (title+' - P95 all attempts (s)',*[fmt(x[workload]['p95_all_requests_seconds']) for x in p]),
  (title+' - JSON structure-valid rate',*[pct(x[workload]['json_completion_rate']) for x in p]),
  (title+' - peak allocated VRAM (GiB)',*[fmt(x[workload]['peak_allocated_gib']) for x in p]),
  (title+' - peak reserved VRAM (GiB)',*[fmt(x[workload]['peak_reserved_gib']) for x in p]),
  (title+' - median generation tokens/s',*[fmt(x[workload]['median_generated_tokens_per_second']) for x in p])]
text=['Qwen3-VL-2B vs Qwen3-VL-4B — 2026-11-12','',
 'RTX 4080 16 GB; bfloat16; same three source videos and prompts.','Accuracy is provisional: single-rater visual references, not human-adjudicated.','',
 f"{'Metric':<54}{labels[0]:>16}{labels[1]:>16}",'-'*86]
for row in rows:text.append(f'{row[0]:<54}{row[1]:>16}{row[2]:>16}')
text += ['', 'Coverage and interpretation',
 '- JSON completion measures structural output validity; it does not imply all requested scores or correct activity labels were supplied.',
 '- 42 standard windows/model and 40 five-frame action/order windows/model. Standard prompt outputs are rerun from scratch.',
 '- Performance uses 40 five-frame requests/model/workload; two partial final windows are excluded.',
 '- Event accuracy: 38 camera-only windows, 149 known class-window labels. Two browser-navigation windows are excluded.',
 '- Event references contain 25 driving positives and no confirmed positive recklessness, hurt or taking-items examples. Three ambiguous taking-items labels are excluded.',
 '- Event F1 pools the four activity classes; reckless/reckless-driving synonyms and underscores are normalized consistently. Unparseable responses supply no event predictions; formatting failures therefore reduce operational recall.',
 '- The inherited prompt labels routine driving as an anomalous activity. Event F1 measures the prompt/model combination, not isolated visual perception.',
 '- Actions use exact sets for windows with a visible focus actor. State-change accuracy requires both adjacent state labels correct on a visible changed pair; it uses known source chronology so ordering is scored separately.',
 '- Exact ordering requires all five shuffled image IDs in chronological order. Clock/player overlays are masked; one initial popup window is excluded.',
 '- One action word was removed from the Japan actor locator and all affected temporal cases were rerun for both models. Reference labels and eligibility were never changed after seeing outputs.',
 '- P95 is nearest-rank. Completed-JSON P95 includes only schema-valid responses; all-attempt P95 and completion rates expose failures.',
 '- Timing starts with five decoded RGB frames ready and ends after preprocessing, GPU generation, decode and schema validation. Model load, video decode and one warmup/workload are excluded.',
 '- Peak allocated/reserved VRAM includes resident model weights, but excludes other processes. Device-wide peaks and the separate DHS baseline are retained in summary.json.',
 '- Five-frame VLM measurements are not the full live 16-frame YOLO/ReID/SigLIP/VLM pipeline.',
 '- These three correlated street recordings are a small test set; do not infer general injury/theft/recklessness detection performance.',
 '', 'Live deployment: Qwen3-VL-2B remains the live VLM. Both Qwen3 checkpoints are retained; Qwen2.5, SmolVLM2 and MiniCPM-V checkpoints were removed.',
 '', 'Evidence: protocol-v2.json, results/*/*.jsonl, event-class-metrics.csv, accuracy-cases.csv, comparison.csv, summary.json.',
 'Validation status: Share with caveats (provisional references and limited positive-class coverage).']
(ROOT/'benchmark-summary.txt').write_text('\n'.join(text)+'\n')

plt.rcParams.update({'font.family':'DejaVu Sans','font.size':10,'axes.spines.top':False,'axes.spines.right':False})
fig=plt.figure(figsize=(15,9),layout='constrained');grid=fig.add_gridspec(2,2,width_ratios=[1.25,1]);left=fig.add_subplot(grid[:,0]);lat=fig.add_subplot(grid[0,1]);mem=fig.add_subplot(grid[1,1])
metrics=[('Event F1 · 38 windows','event_micro_f1'),('Action sets · 31 windows','action_exact_set_accuracy'),('Visible states · 151 frames','visible_frame_state_accuracy'),('State changes · 19 pairs','state_transition_accuracy'),('Exact ordering · 37 sequences','exact_five_frame_order_accuracy'),('Pairwise ordering · 370 pairs','pairwise_order_accuracy'),('JSON structure valid · 40 calls',None)]
y=np.arange(len(metrics));height=.34
for i in range(2):
 values=[(a[i][key] if key else p[i]['standard']['json_completion_rate'])*100 for _,key in metrics]
 left.barh(y+(i-.5)*height,values,height=height,color=colors[i],label=labels[i])
 for yy,v in zip(y+(i-.5)*height,values):
  left.text(v-1 if v>85 else v+1,yy,f'{v:.1f}%',ha='right' if v>85 else 'left',va='center',color='white' if v>85 else '#222',fontsize=9)
left.set(yticks=y,yticklabels=[m[0] for m in metrics],xlim=(0,100),xlabel='Percent (%)');left.invert_yaxis();left.set_title('Accuracy against provisional references',loc='left',weight='bold');left.grid(axis='x',alpha=.18);left.set_axisbelow(True);left.legend(loc='upper right',bbox_to_anchor=(1,.98))
lat_metrics=[('Standard · completed JSON','standard','p95_valid_json_seconds'),('Standard · all attempts','standard','p95_all_requests_seconds'),('Action/order · completed JSON','temporal','p95_valid_json_seconds'),('Action/order · all attempts','temporal','p95_all_requests_seconds')]
y2=np.arange(4)
max_latency=max(p[i][w][k] or 0 for _,w,k in lat_metrics for i in range(2))
for i in range(2):
 values=[p[i][w][k] or 0 for _,w,k in lat_metrics]
 lat.barh(y2+(i-.5)*height,values,height=height,color=colors[i])
 for yy,v in zip(y2+(i-.5)*height,values):lat.text(v+max_latency*.018,yy,f'{v:.2f}s',va='center',fontsize=9)
lat.set(yticks=y2,yticklabels=[m[0] for m in lat_metrics],xlim=(0,max_latency*1.23),xlabel='P95 latency (seconds)');lat.invert_yaxis();lat.set_title('P95 response latency · lower is faster',loc='left',weight='bold');lat.grid(axis='x',alpha=.18);lat.set_axisbelow(True)
for i in range(2):
 values=[p[i][w]['peak_allocated_gib'] for w in ['standard','temporal']]
 mem.barh(np.arange(2)+(i-.5)*height,values,height=height,color=colors[i])
 for yy,v in zip(np.arange(2)+(i-.5)*height,values):mem.text(v+.12,yy,f'{v:.2f} GiB',va='center',fontsize=9)
max_memory=max(p[i][w]['peak_allocated_gib'] for i in range(2) for w in ['standard','temporal'])
mem.set(yticks=np.arange(2),yticklabels=['Standard prompt','Action/order prompt'],xlim=(0,max_memory*1.25),xlabel='Peak allocated VRAM (GiB), including weights');mem.invert_yaxis();mem.set_title('Peak GPU allocation · including weights',loc='left',weight='bold');mem.grid(axis='x',alpha=.18);mem.set_axisbelow(True)
fig.suptitle('Qwen3-VL 2B vs 4B · RTX 4080 · five-frame workloads',fontsize=17,weight='bold')
fig.supxlabel('Provisional labels · 3 street recordings · no confirmed positive injury, recklessness or taking-item examples',fontsize=10)
fig.savefig(ROOT/'comparison.png',dpi=160,facecolor='white');plt.close(fig)
print('Summary and chart written.')
