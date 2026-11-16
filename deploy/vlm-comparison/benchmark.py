"""Run reproducible model inference on common five-second video windows."""
import argparse
from datetime import datetime, timezone
from hashlib import sha256
import json
import os
from pathlib import Path
import time

from PIL import Image
import torch
from transformers import AutoModelForImageTextToText, AutoProcessor
import transformers

ROOT = Path('/bench')
MODELS = {
    'qwen2.5-vl-3b': 'Qwen/Qwen2.5-VL-3B-Instruct',
    'qwen3-vl-2b': 'Qwen/Qwen3-VL-2B-Instruct',
    'minicpm-v-4.6': 'openbmb/MiniCPM-V-4.6',
    'smolvlm2-2.2b': 'HuggingFaceTB/SmolVLM2-2.2B-Instruct',
}


def parse_response(raw):
    for index, character in enumerate(raw):
        if character == '{':
            try:
                result, _ = json.JSONDecoder().raw_decode(raw[index:])
            except ValueError:
                continue
            if isinstance(result, dict) and 'scene_summary' in result:
                return result
    return None


def run(args):
    torch.set_num_threads(4)
    torch.manual_seed(0)
    inputs = json.loads((ROOT / 'input-manifest.json').read_text())
    model_id = MODELS[args.model]
    if args.model == 'smolvlm2-2.2b':
        revision = '482adb537c021c86670beed01cd58990d01e72e4'
        cache = '/oldmodels/huggingface/hub'
    elif args.model in ('qwen2.5-vl-3b', 'qwen3-vl-2b'):
        revision = json.loads(Path('/oldmodels/checkpoints.json').read_text())[model_id]
        cache = '/oldmodels/huggingface/hub'
    else:
        catalog = json.loads((ROOT / 'models/manifest.json').read_text())
        revision = catalog[model_id]['revision']
        cache = str(ROOT / 'models/huggingface/hub')
    processor = AutoProcessor.from_pretrained(model_id, revision=revision, cache_dir=cache,
                                             local_files_only=True,
                                             min_pixels=128 * 32 * 32, max_pixels=512 * 512)
    model = AutoModelForImageTextToText.from_pretrained(
        model_id, revision=revision, cache_dir=cache, local_files_only=True,
        dtype=torch.bfloat16, low_cpu_mem_usage=True, attn_implementation='sdpa',
    ).to('cuda').eval()
    results = ROOT / 'results' / args.model
    results.mkdir(parents=True, exist_ok=True)
    metadata = {'model_id': model_id, 'revision': revision, 'transformers': transformers.__version__,
                'torch': torch.__version__, 'parameters': sum(p.numel() for p in model.parameters()),
                'dtype': 'bfloat16', 'max_new_tokens': inputs['max_new_tokens'],
                'repetition_penalty': 1.1, 'no_repeat_ngram_size': 32,
                'input_manifest_sha256': sha256((ROOT/'input-manifest.json').read_bytes()).hexdigest(),
                'processor': processor.to_dict() if hasattr(processor, 'to_dict') else repr(processor)}
    (results / 'model.json').write_text(json.dumps(metadata, indent=2, default=str))
    count = 0
    for video in inputs['videos']:
        log_path = results / (video['key'] + '.jsonl')
        completed = {}
        if log_path.exists():
            completed = {row['start']: row for row in map(json.loads, log_path.read_text().splitlines())
                         if row.get('status') == 'ok'}
        for window in video['windows']:
            if window['start'] in completed:
                continue
            images = [Image.open(ROOT / file).convert('RGB') for file in window['frames']]
            content = []
            for index, image in enumerate(images):
                content.extend([{'type': 'text', 'text': f'Frame {index}:'},
                                {'type': 'image', 'image': image}])
            content.append({'type': 'text', 'text': window['prompt']})
            messages = [{'role': 'user', 'content': content}]
            extra = {'downsample_mode': '16x', 'max_slice_nums': 1} if args.model == 'minicpm-v-4.6' else {}
            started = time.monotonic()
            batch = processor.apply_chat_template(
                messages, tokenize=True, add_generation_prompt=True,
                return_dict=True, return_tensors='pt', **extra,
            ).to('cuda', dtype=torch.bfloat16)
            generate_extra = {'downsample_mode': '16x'} if args.model == 'minicpm-v-4.6' else {}
            with torch.inference_mode():
                generated = model.generate(**batch, do_sample=False, repetition_penalty=1.1,
                                           no_repeat_ngram_size=32,
                                           max_new_tokens=inputs['max_new_tokens'], **generate_extra)
            token_ids = generated[:, batch['input_ids'].shape[1]:]
            raw = processor.batch_decode(token_ids, skip_special_tokens=True)[0].strip()
            row = {'status': 'ok', 'model': args.model, 'model_id': model_id,
                   'revision': revision, 'video': video['key'], 'start': window['start'],
                   'end': window['end'], 'frame_times': window['frame_times'],
                   'prompt_sha256': window['prompt_sha256'], 'raw_output': raw,
                   'parsed': parse_response(raw), 'generated_tokens': token_ids.shape[1],
                   'hit_token_limit': token_ids.shape[1] >= inputs['max_new_tokens'],
                   'elapsed_seconds': round(time.monotonic() - started, 3),
                   'completed_at': datetime.now(timezone.utc).isoformat()}
            with log_path.open('a') as output:
                output.write(json.dumps(row) + '\n')
                output.flush()
                os.fsync(output.fileno())
            print(json.dumps({key: row[key] for key in ('model','video','start','end','elapsed_seconds','generated_tokens')}
                             | {'parsed': row['parsed'] is not None}), flush=True)
            count += 1
            if args.limit and count >= args.limit:
                return
    print(json.dumps({'model': args.model, 'state': 'completed'}), flush=True)


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--model', choices=MODELS, required=True)
    parser.add_argument('--limit', type=int, default=0)
    run(parser.parse_args())
