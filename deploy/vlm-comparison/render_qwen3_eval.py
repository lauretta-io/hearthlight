"""Render the rerun's actual standard-prompt output at five-second boundaries."""
import argparse
import json
from pathlib import Path
import subprocess
import textwrap
from render import annotation, timestamp

ROOT=Path('/home/lauretta/hearthlight/var/qwen3-evaluation-20261112')
SOURCE=Path('/home/lauretta/hearthlight/var/vlm-comparison')
manifest=json.loads((SOURCE/'input-manifest.json').read_text())
output=ROOT/'annotated';output.mkdir(exist_ok=True)
parser=argparse.ArgumentParser();parser.add_argument('--model',choices=['qwen3-vl-2b','qwen3-vl-4b']);args=parser.parse_args()
for model in ([args.model] if args.model else ['qwen3-vl-2b','qwen3-vl-4b']):
 rows=[json.loads(s) for s in (ROOT/'results'/model/'standard.jsonl').read_text().splitlines()]
 for video in manifest['videos']:
  selected={r['start']:r for r in rows if r['video']==video['key']}
  assert set(selected)=={w['start'] for w in video['windows']},'Incomplete standard-prompt video results'
  width=video['width'];height=video['height']+360
  ass=ROOT/'results'/model/(video['key']+'.ass')
  contents=f'''[Script Info]
ScriptType: v4.00+
PlayResX: {width}
PlayResY: {height}
WrapStyle: 2

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Default,DejaVu Sans Mono,26,&H00FFFFFF,&H00FFFFFF,&H00000000,&H00000000,0,0,0,0,100,100,0,0,1,0,0,7,20,20,15,1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
'''
  for start,row in sorted(selected.items()):
   prepared={**row,'parsed':row.get('parsed') if row['schema_valid'] else None,
     'raw_output':row.get('raw_output',row.get('error','No response')),'hit_token_limit':row.get('hit_token_limit',False)}
   text=annotation(prepared,manifest,width)
   seconds=f"{row['elapsed_seconds']:.2f}s" if 'elapsed_seconds' in row else 'failed'
   memory=f"{row['peak_allocated_bytes']/2**30:.2f} GiB" if 'peak_allocated_bytes' in row else 'not recorded'
   perf=f"Latency: {seconds} | peak allocated VRAM: {memory} | schema-valid JSON: {'yes' if row['schema_valid'] else 'no'}"
   lines=text.split(r'\N');lines.insert(1,perf);text=r'\N'.join(lines[:10])
   contents+=f"Dialogue: 0,{timestamp(start)},{timestamp(row['end'])},Default,,0,0,0,,{text}\n"
  ass.write_text(contents)
  path=output/f"{video['name']} - {model} - 2026-11-12 annotated.mp4"
  temporary=path.with_suffix('.tmp.mp4')
  subprocess.run(['ffmpeg','-hide_banner','-loglevel','error','-threads','2','-i',str(SOURCE/'inputs'/(video['key']+'.mov')),
    '-map','0:v:0','-map','0:a?','-vf',f'pad=iw:ih+360:0:360:black,ass={ass}',
    '-filter_threads','1','-r','30','-c:v','libx264','-preset','veryfast','-crf','22','-pix_fmt','yuv420p',
    '-threads','4','-c:a','aac','-b:a','128k','-movflags','+faststart','-t',str(video['duration']),'-y',str(temporary)],check=True)
  probe=json.loads(subprocess.check_output(['ffprobe','-v','error','-show_format','-show_streams','-of','json',str(temporary)]))
  assert abs(float(probe['format']['duration'])-video['duration'])<.15
  stream=next(s for s in probe['streams'] if s['codec_type']=='video')
  assert (stream['width'],stream['height'])==(width,height)
  temporary.replace(path)
  print(json.dumps({'model':model,'video':video['key'],'windows':len(selected),'path':str(path),'bytes':path.stat().st_size}),flush=True)
