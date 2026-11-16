"""Replay existing, originally attributed tracklet features into a bounded bank.
Raw activity/video records and timestamps are preserved. Each real source sample
is one reconciliation window; repeated invocation does not create duplicate features.
"""
import argparse,json,sqlite3,time
from datetime import datetime
from pathlib import Path
import numpy as np
from person_reid import PersonGallery

def backfill(gallery_path,folder,model_key='transreid-market1501'):
    folder=Path(folder)
    people={r['humanReadableId']:r['externalId'] for r in json.loads((folder/'person-map.json').read_text())}
    records=json.loads((folder/'track-records.json').read_text())
    manifest={(r['scene_id'],r['track_id']):r for r in json.loads((folder/'track-manifest.json').read_text())}
    features=np.load(folder/'track-features.npz')['features']
    gallery=PersonGallery(Path(gallery_path),model_key)
    applied=0;merges=[]
    try:
        for i in sorted(range(len(records)),key=lambda i:records[i]['sample_started_at']):
            row=records[i];person=gallery.bank.resolve(people[row['label']])
            if not gallery.db.execute('SELECT 1 FROM people WHERE person_id=? AND model_key=?',(person,model_key)).fetchone():continue
            original=manifest[(row['scene_id'],row['track_id'])]
            quality=sum(min(1,(d['box_xyxy'][2]-d['box_xyxy'][0])/64)*min(1,(d['box_xyxy'][3]-d['box_xyxy'][1])/128) for d in original['detections'])/len(original['detections'])
            observed=datetime.fromisoformat(row['sample_started_at']).timestamp()
            key=f"{row['scene_id']}:{row['track_id']-1}"
            with gallery.db:
                gallery.bank.observe(person,features[i],quality,observed,key)
                merged=gallery.bank.merge_window(time.time(),row['scene_id'],active_ids={person})
                merges.extend(merged)
            applied+=1
        return {'tracklets_processed':applied,'merges':merges,'groups':{label:gallery.bank.resolve(people[label]) for label in ['per_27','per_29','per_30']}}
    finally:gallery.db.close()

if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--gallery',required=True);parser.add_argument('--folder',required=True)
    args=parser.parse_args();print(json.dumps(backfill(args.gallery,args.folder)))
