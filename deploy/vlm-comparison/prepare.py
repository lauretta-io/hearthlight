"""Prepare common one-FPS inputs and the repository's standard surveillance prompt."""
from concurrent.futures import ThreadPoolExecutor
from hashlib import sha256
import json
from math import ceil
from pathlib import Path
import subprocess

import yaml

ROOT = Path('/home/lauretta/hearthlight')
WORK = ROOT / 'var/vlm-comparison'
FOCUS = ['recklessness', 'driving', 'hurt', 'taking items']
SOURCES = {
    'video-091312': ('1l81gdN0-Ac2stEXiDYZx36b1ehqMRW-M', 'Screen Recording 2026-11-10 at 9.13.12 PM'),
    'video-091517': ('1N0V8h4FBvDabSV6-0Nu0xJBCdx6m_ck6', 'Screen Recording 2026-11-10 at 9.15.17 PM'),
    'video-091736': ('1Dbj7fmVUainUenyillfP14R2NXFW83vS', 'Screen Recording 2026-11-10 at 9.17.36 PM'),
}
template = yaml.safe_load((ROOT / 'shared/prompts/prompt_v2.yaml').read_text())['template']
items = yaml.safe_load((ROOT / 'shared/prompts/anomaly_list.yaml').read_text())['anomaly_object_list']


def prepare(source):
    key, (file_id, name) = source
    path = WORK / 'inputs' / f'{key}.mov'
    metadata = json.loads(subprocess.check_output([
        'ffprobe', '-v', 'error', '-show_format', '-show_streams', '-of', 'json', str(path),
    ]))
    duration = float(metadata['format']['duration'])
    video = next(stream for stream in metadata['streams'] if stream['codec_type'] == 'video')
    frames = WORK / 'frames' / key
    frames.mkdir(parents=True, exist_ok=True)
    if not list(frames.glob('*.jpg')):
        subprocess.run([
        'ffmpeg', '-v', 'error', '-i', str(path), '-an', '-vf',
        'fps=1:round=up,scale=960:-2', '-q:v', '2', '-start_number', '0', '-y',
        str(frames / '%04d.jpg'),
        ], check=True)
    windows = []
    for start in range(0, ceil(duration), 5):
        indices = [index for index in range(start, min(start + 5, ceil(duration)))
                   if (frames / f'{index:04d}.jpg').exists()]
        files = [frames / f'{index:04d}.jpg' for index in indices]
        assert files, (key, start)
        prompt = template.format(
            frames_count=len(files),
            input_details='\n'.join(f'Frame {local}: video time {index:.1f} seconds'
                                    for local, index in enumerate(indices)),
            anomaly_object_list='\n'.join(f'- {item}' for item in items),
            anomaly_activity_list='\n'.join(f'- {activity}' for activity in FOCUS),
        )
        windows.append({'start': start, 'end': min(start + 5, duration),
                        'frames': [str(file.relative_to(WORK)) for file in files],
                        'frame_times': indices, 'prompt': prompt,
                        'prompt_sha256': sha256(prompt.encode()).hexdigest()})
    print(key, len(windows), 'windows', duration, 'seconds', flush=True)
    return {'key': key, 'file_id': file_id, 'name': name, 'duration': duration,
            'width': video['width'], 'height': video['height'], 'windows': windows}


if __name__ == '__main__':
    with ThreadPoolExecutor(max_workers=3) as pool:
        videos = list(pool.map(prepare, SOURCES.items()))
    manifest = {'template': template, 'template_sha256': sha256(template.encode()).hexdigest(),
                'prompt_source': 'shared/prompts/prompt_v2.yaml',
                'focus_activities': FOCUS, 'fps': 1, 'window_seconds': 5,
                'input_long_edge': 960, 'max_new_tokens': 1024, 'videos': videos}
    (WORK / 'input-manifest.json').write_text(json.dumps(manifest, indent=2))
