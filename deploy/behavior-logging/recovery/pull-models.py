#!/usr/bin/env python3
"""Run inside the logger image with /models mounted; pull and verify pinned weights."""
import hashlib, json, pathlib, urllib.request
from huggingface_hub import snapshot_download
root=pathlib.Path('/models')
root.mkdir(parents=True,exist_ok=True)
manifest=json.loads(pathlib.Path(__file__).with_name('models.json').read_text())
revisions={}
for model in manifest['huggingface']:
    snapshot_download(repo_id=model['repo'],revision=model['revision'])
    revisions[model['repo']]=model['revision']
for model in manifest['files']:
    path=root/model['filename']
    def digest(p):
        result=hashlib.sha256()
        with p.open('rb') as f:
            for chunk in iter(lambda:f.read(1024*1024),b''):result.update(chunk)
        return result.hexdigest()
    if path.exists() and digest(path)==model['sha256']:continue
    temporary=path.with_suffix(path.suffix+'.download')
    try:
        urllib.request.urlretrieve(model['url'],temporary)
        if digest(temporary)!=model['sha256']:
            raise RuntimeError('Checkpoint hash mismatch: '+model['filename'])
        temporary.replace(path)
    finally:
        temporary.unlink(missing_ok=True)
(root/'checkpoints.json').write_text(json.dumps(revisions,indent=2)+'\n')
print('Pinned model cache downloaded and verified.')
