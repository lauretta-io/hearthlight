from pathlib import Path
import json
import statistics
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import numpy as np
ROOT=Path('/probe');s=json.loads((ROOT/'final-summary.json').read_text())
std=[json.loads(x) for x in (ROOT/'standard.jsonl').read_text().splitlines()]
full=[json.loads(x) for x in (ROOT/'scene_person.jsonl').read_text().splitlines()]
batch=[json.loads(x) for x in (ROOT/'batch2.jsonl').read_text().splitlines()]
serial_estimates=[std[i]['processing_seconds']+std[(i+1)%6]['processing_seconds'] for i in range(6)]
full_pairs=[sum(r['processing_seconds'] for r in full if r['window_index']==i) for i in range(6)]
mean=[statistics.mean(serial_estimates),statistics.mean(r['processing_seconds'] for r in batch),statistics.mean(full_pairs)]
worst=[max(serial_estimates),max(r['processing_seconds'] for r in batch),max(full_pairs)]
plt.rcParams.update({'font.family':'DejaVu Sans','font.size':11,'axes.spines.top':False,'axes.spines.right':False})
fig,axes=plt.subplots(1,2,figsize=(13,6),layout='constrained')
y=np.arange(3);height=.32
for offset,values,label,color in [(-.16,mean,'Mean','#0072B2'),(.16,worst,'Slowest','#D55E00')]:
 axes[0].barh(y+offset,values,height=height,color=color,label=label)
 for yy,v in zip(y+offset,values):axes[0].text(v+.5,yy,f'{v:.2f}s',va='center',fontsize=10)
axes[0].axvline(10,color='#333',linestyle='--',label='10-second cycle budget')
axes[0].set(yticks=y,yticklabels=['Short scoring, serial\n(estimated pair)','Short scoring, batch 2\n(measured pair)','Full scene/person, serial\n(measured pair)'],xlim=(0,max(worst)*1.18),xlabel='Seconds to process TWO eight-frame requests')
axes[0].invert_yaxis();axes[0].set_title('Work required for two feeds',loc='left',weight='bold');axes[0].legend(loc='upper right',fontsize=9);axes[0].grid(axis='x',alpha=.15);axes[0].set_axisbelow(True)
x=np.arange(1,7);lag=[r['completion_lag_seconds'] for r in batch]
axes[1].plot(x,lag,'o-',color='#0072B2',linewidth=2,label='Both responses complete')
axes[1].axhline(10,color='#D55E00',linestyle='--',label='Next-window deadline')
for xx,v in zip(x,lag):axes[1].annotate(f'{v:.2f}s',(xx,v),xytext=(0,9),textcoords='offset points',ha='center',fontsize=9)
axes[1].set(xlim=(.7,6.3),ylim=(0,max(lag)+2),xticks=x,xlabel='Ten-second window pair',ylabel='Response lag after window closes (seconds)')
axes[1].set_title('Batched scoring: short real-time replay',loc='left',weight='bold');axes[1].grid(alpha=.15);axes[1].legend(loc='lower right',fontsize=9)
fig.suptitle('Qwen3-VL-4B · 8 frames per 10 seconds · RTX 4080',fontsize=16,weight='bold')
fig.supxlabel('Six windows from one recording · two logical feeds · 640px inputs · bf16 · no behavior-accuracy assessment',fontsize=10)
fig.savefig(ROOT/'capacity.png',dpi=150,facecolor='white');plt.close(fig)
