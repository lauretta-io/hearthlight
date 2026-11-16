"""Render each model's actual output above the source footage at five-second boundaries."""
import argparse
import json
from pathlib import Path
import re
import subprocess
import textwrap

ROOT = Path('/home/lauretta/hearthlight/var/vlm-comparison')


def timestamp(seconds):
    centiseconds = round(seconds * 100)
    hours, remainder = divmod(centiseconds, 360000)
    minutes, remainder = divmod(remainder, 6000)
    whole, decimal = divmod(remainder, 100)
    return f'{hours}:{minutes:02d}:{whole:02d}.{decimal:02d}'


def text_value(value):
    if isinstance(value, list):
        return ', '.join(map(str, value)) or 'none'
    return 'not supplied' if value is None else str(value or 'none')


def annotation(row, manifest, width):
    data = row['parsed']
    if data is None:
        data = {}
        for key in ('scene_summary', 'think', 'visible_items', 'visible_activities',
                    'confidence', 'anomaly_detected', 'anomaly_category'):
            match = re.search('"' + key + r'"\s*:\s*', row['raw_output'])
            if match:
                try:
                    data[key], _ = json.JSONDecoder().raw_decode(row['raw_output'][match.end():])
                except ValueError:
                    pass
    header = f"{row['model_id']} | {row['start']:05.1f}-{row['end']:05.1f}s | {len(row['frame_times'])} frames at 1 FPS"
    if not data:
        lines = [header, 'Format warning: model did not complete the requested JSON.', row['raw_output'][:600]]
    else:
        scores = data.get('think', '')
        if isinstance(scores, list):
            scores = {entry.get('item') or entry.get('activity') or entry.get('label'): entry.get('score')
                      for entry in scores if isinstance(entry, dict)}
        focus = []
        for activity in manifest['focus_activities']:
            if isinstance(scores, dict):
                score = scores.get(activity)
            else:
                match = re.search(r'\b' + re.escape(activity) + r'\s*[\"\']?\s*[:=]\s*(10|[0-9])(?:\.\d+)?', str(scores), re.I)
                score = match.group(1) if match else None
            focus.append(f"{activity}: {score}/10" if score is not None else f"{activity}: not scored")
        lines = [header,
                 'Detected activities: ' + text_value(data.get('visible_activities')),
                 ' | '.join(focus),
                 'Visible items: ' + text_value(data.get('visible_items')),
                 'Model anomaly confidence: ' + str(data.get('confidence', 'not supplied')),
                 'Scene summary: ' + str(data.get('scene_summary') or 'not supplied')]
    if row['parsed'] is None and data:
        lines.insert(1, 'Format warning: incomplete JSON; showing complete fields from the model response.')
    if row['hit_token_limit']:
        lines.insert(1, 'Model response reached the generation limit.')
    # Keep the complete raw response in JSONL. The readable panel has a bounded height.
    wrapped = []
    for line in lines:
        clean = str(line).replace('\\', '/').replace('{', '(').replace('}', ')').replace('\n', ' ')
        wrapped.extend(textwrap.wrap(clean, width=max(80, width // 16), break_long_words=False) or [''])
    if len(wrapped) > 9:
        wrapped = wrapped[:9]
        wrapped[-1] = wrapped[-1][:110] + ' ...'
    return r'\N'.join(wrapped)


def render(model, only_video=None):
    manifest = json.loads((ROOT/'input-manifest.json').read_text())
    folder = ROOT/'results'/model
    outputs = ROOT/'annotated'
    outputs.mkdir(exist_ok=True)
    for video in manifest['videos']:
        if only_video and video['key'] != only_video:
            continue
        path = folder/(video['key']+'.jsonl')
        rows = {row['start']:row for row in map(json.loads,path.read_text().splitlines()) if row['status']=='ok'}
        assert set(rows) == {window['start'] for window in video['windows']}, 'Incomplete windows'
        width = video['width']
        height = video['height'] + 320
        subtitles = folder/(video['key']+'.ass')
        header = f'''[Script Info]
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
        for start in sorted(rows):
            row = rows[start]
            text = annotation(row, manifest, width)
            header += f"Dialogue: 0,{timestamp(start)},{timestamp(row['end'])},Default,,0,0,0,,{text}\n"
        subtitles.write_text(header)
        output = outputs/f"{video['name']} - {model} - annotated.mp4"
        temporary = output.with_suffix('.tmp.mp4')
        subprocess.run([
            'ffmpeg','-hide_banner','-loglevel','error','-threads','2','-i',str(ROOT/'inputs'/(video['key']+'.mov')),
            '-map','0:v:0','-map','0:a?', '-vf', f"pad=iw:ih+320:0:320:black,ass={subtitles}",
            '-r','30','-c:v','libx264','-preset','fast','-crf','22','-pix_fmt','yuv420p',
            '-threads','4','-c:a','aac','-b:a','128k','-movflags','+faststart',
            '-t',str(video['duration']),'-y',str(temporary),
        ],check=True)
        metadata=json.loads(subprocess.check_output([
            'ffprobe','-v','error','-show_format','-show_streams','-of','json',str(temporary)]))
        assert abs(float(metadata['format']['duration'])-video['duration']) < 0.15
        stream=next(s for s in metadata['streams'] if s['codec_type']=='video')
        assert stream['width']==width and stream['height']==height
        temporary.replace(output)
        print(json.dumps({'video':video['key'],'model':model,'windows':len(rows),
                          'path':str(output),'bytes':output.stat().st_size}),flush=True)


if __name__ == '__main__':
    parser=argparse.ArgumentParser()
    parser.add_argument('--model',required=True)
    parser.add_argument('--video')
    args=parser.parse_args()
    render(args.model,args.video)
