"""Bounded, diverse appearance prototypes and auditable retrospective aliases."""
import json
import sqlite3
import zlib
from hashlib import sha256
import numpy as np
from rerank import reciprocal_distances

class FeatureBank:
    def __init__(self, db, limit=8, relaxed_threshold=.76, model_key=None):
        self.db, self.limit, self.relaxed_threshold = db, limit, relaxed_threshold
        self.model_key=model_key
        db.executescript('''
          CREATE TABLE IF NOT EXISTS person_features (
            id TEXT PRIMARY KEY,person_id TEXT NOT NULL,embedding BLOB NOT NULL,
            quality REAL NOT NULL,seen_at REAL NOT NULL,track_key TEXT NOT NULL);
          CREATE INDEX IF NOT EXISTS person_features_identity ON person_features(person_id);
          CREATE TABLE IF NOT EXISTS person_aliases (
            alias_id TEXT PRIMARY KEY,person_id TEXT NOT NULL,merged_at REAL NOT NULL);
          CREATE TABLE IF NOT EXISTS identity_merges (
            merge_id TEXT PRIMARY KEY,loser_id TEXT NOT NULL,winner_id TEXT NOT NULL,
            merged_at REAL NOT NULL,evidence TEXT NOT NULL);
          CREATE TABLE IF NOT EXISTS identity_merge_backups (merge_id TEXT PRIMARY KEY,payload BLOB NOT NULL);
          CREATE TABLE IF NOT EXISTS identity_conflicts (
            left_id TEXT NOT NULL,right_id TEXT NOT NULL,PRIMARY KEY(left_id,right_id));
          CREATE TABLE IF NOT EXISTS merge_candidates (
            pair_key TEXT PRIMARY KEY,window_key TEXT NOT NULL,confirmations INTEGER NOT NULL);
        ''')
        if 'last_seen' not in {r[1] for r in db.execute('PRAGMA table_info(merge_candidates)')}:
            db.execute('ALTER TABLE merge_candidates ADD COLUMN last_seen REAL NOT NULL DEFAULT 0')
        db.execute('CREATE TABLE IF NOT EXISTS feature_bank_meta(key TEXT PRIMARY KEY,value TEXT NOT NULL)')
        with db:
            marker='conflicts:'+str(self.model_key)
            if not db.execute('SELECT 1 FROM feature_bank_meta WHERE key=?',(marker,)).fetchone():
                grouped={}
                for payload, in db.execute('SELECT t.payload FROM track_observations t JOIN people p ON p.person_id=t.person_id WHERE (? IS NULL OR p.model_key=?)',(self.model_key,self.model_key)).fetchall():
                    row=json.loads(payload);grouped.setdefault(row['sample_id'],[]).append(row)
                for records in grouped.values():
                    self.record_conflicts([[(d['frame_index'],d['box_xyxy']) for d in r['detections']] for r in records],[r['person_id'] for r in records])
                db.execute('INSERT INTO feature_bank_meta VALUES (?,?)',(marker,'done'))
            for person,blob,seen in db.execute('SELECT person_id,embedding,last_seen FROM people').fetchall():
                if not db.execute('SELECT 1 FROM person_features WHERE person_id=?',(person,)).fetchone():
                    self.observe(person,np.frombuffer(blob,np.float32),.5,seen,'legacy:'+person)

    def resolve(self, person):
        seen=set()
        while person and person not in seen:
            seen.add(person)
            row=self.db.execute('SELECT person_id FROM person_aliases WHERE alias_id=?',(person,)).fetchone()
            if not row:return person
            person=row[0]
        raise ValueError('identity_alias_cycle')

    def group(self, person):
        root=self.resolve(person)
        return [root]+[r[0] for r in self.db.execute('SELECT alias_id FROM person_aliases') if self.resolve(r[0])==root]

    def observe(self, person, vector, quality, now, track_key):
        if quality < .3 or not np.isfinite(vector).all():return
        person=self.resolve(person)
        key=sha256(f'{person}:{track_key}'.encode()).hexdigest()
        if not self.db.execute('SELECT 1 FROM person_features WHERE person_id=? AND track_key=?',(person,track_key)).fetchone():
            self.db.execute('INSERT OR IGNORE INTO person_features VALUES (?,?,?,?,?,?)',
                            (key,person,np.asarray(vector,np.float32).tobytes(),float(quality),now,track_key))
        rows=self.db.execute('SELECT id,embedding,quality,seen_at FROM person_features WHERE person_id=? ORDER BY quality DESC,seen_at DESC,id',(person,)).fetchall()
        # Keep the best crop, then prefer useful diversity over repeated same-view crops.
        chosen=[];remaining=list(rows)
        while remaining and len(chosen)<self.limit:
            if not chosen:best=remaining[0]
            else:
                best=max(remaining,key=lambda r:.65*min(1-float(np.frombuffer(r[1],np.float32)@np.frombuffer(c[1],np.float32)) for c in chosen)+.35*r[2])
            chosen.append(best);remaining.remove(best)
        for row in remaining:self.db.execute('DELETE FROM person_features WHERE id=?',(row[0],))

    def vectors(self, allowed=None):
        rows=self.db.execute('SELECT person_id,embedding,quality,seen_at,track_key FROM person_features ORDER BY quality DESC,seen_at DESC').fetchall()
        return [(p,np.frombuffer(b,np.float32),q,t,k) for p,b,q,t,k in rows if (allowed is None or p in allowed)]

    def relaxed_candidate(self, vector, allowed):
        rows=self.vectors(allowed)
        if not rows:return None
        scores={p:max(float(vector@v) for x,v,_,_,_ in rows if x==p) for p in {r[0] for r in rows}}
        ranked=sorted(scores,key=scores.get,reverse=True);winner=ranked[0]
        hits=[r for r in rows if r[0]==winner and not r[4].startswith('legacy:') and float(vector@r[1])>=self.relaxed_threshold]
        if len({r[4] for r in hits})<2:return None
        if len(ranked)>1 and scores[winner]-scores[ranked[1]]<.05:return None
        context=rows[:96]
        distances=reciprocal_distances(np.stack([vector,*[r[1] for r in context]]),1)[0]
        refined={p:min(float(distances[i]) for i,r in enumerate(context) if r[0]==p) for p in {r[0] for r in context}}
        best=sorted(refined,key=refined.get)
        if best[0]!=winner or refined[winner]>.45:return None
        if len(best)>1 and refined[best[1]]-refined[winner]<.04:return None
        return winner

    def record_conflicts(self, tracks, persons):
        for i,a in enumerate(persons):
            if not a:continue
            fa={d[0] for d in tracks[i]}
            for j in range(i):
                b=persons[j]
                if b and a!=b and fa.intersection(d[0] for d in tracks[j]):
                    left,right=sorted((self.resolve(a),self.resolve(b)))
                    if left!=right:self.db.execute('INSERT OR IGNORE INTO identity_conflicts VALUES (?,?)',(left,right))

    def conflict(self,a,b):
        return any({self.resolve(x),self.resolve(y)}=={a,b} for x,y in self.db.execute('SELECT left_id,right_id FROM identity_conflicts'))

    def merge_window(self, now, window_key, window_seconds=600, ttl_seconds=86400, active_ids=None):
        if active_ids is not None and not active_ids:return []
        people={p:(t,birth) for p,t,birth in self.db.execute('''SELECT p.person_id,p.last_seen,COALESCE(b.created_at,p.last_seen)
                  FROM people p LEFT JOIN identity_births b ON b.person_id=p.person_id WHERE p.last_seen>=? AND (? IS NULL OR p.model_key=?) ORDER BY p.last_seen DESC LIMIT 16''',(now-ttl_seconds,self.model_key,self.model_key))}
        rows=[r for r in self.vectors(set(people)) if r[2]>=.3][:96]
        if len(rows)<4:return []
        # The same reciprocal-neighbor context is used for both sides of each proposal.
        x=np.stack([r[1] for r in rows]);cos=x@x.T;distance=np.zeros_like(cos)
        for i in range(len(rows)):
            others=[j for j in range(len(rows)) if j!=i]
            distance[i,others]=reciprocal_distances(x[[i,*others]],1)[0]
        proposals=[]
        ids=sorted({r[0] for r in rows})
        scores={}
        for ai,a in enumerate(ids):
            ia=[i for i,r in enumerate(rows) if r[0]==a]
            for b in ids[:ai]:
                ib=[i for i,r in enumerate(rows) if r[0]==b]
                if (active_ids is None and max(people[a][0],people[b][0])<now-window_seconds) or self.conflict(a,b):continue
                edges=sorted([(float(cos[i,j]),i,j) for i in ia for j in ib if not rows[i][4].startswith('legacy:') and not rows[j][4].startswith('legacy:')],reverse=True)
                useda=set();usedb=set();support=[]
                for similarity,i,j in edges:
                    if similarity<self.relaxed_threshold:break
                    if i not in useda and j not in usedb:
                        support.append((similarity,float(distance[i,j])));useda.add(i);usedb.add(j)
                if len(support)<2:continue
                strength=float(np.mean([s for s,_ in support[:3]]));refined=float(np.mean([d for _,d in support[:2]]))
                if strength>=self.relaxed_threshold and refined<=.45:scores[(a,b)]=(strength,refined,len(support))
        # Require mutual best identity matches and separation from every other proposal.
        for (a,b),(strength,refined,count) in scores.items():
            for other in ids:
                if other in (a,b):continue
                for own in (a,b):
                    rivals_score=float(cos[np.ix_([i for i,r in enumerate(rows) if r[0]==own],[i for i,r in enumerate(rows) if r[0]==other])].max())
                    if rivals_score>strength-.04:break
                else:continue
                break
            else:other=None
            if other is not None:continue
            rivals=[s[0] for (u,v),s in scores.items() if (a in (u,v) or b in (u,v)) and {u,v}!={a,b}]
            if rivals and strength-max(rivals)<.04:continue
            if active_ids is not None and not {a,b}.intersection(active_ids):continue
            pair=':'.join(sorted((a,b)));prior=self.db.execute('SELECT window_key,confirmations,last_seen FROM merge_candidates WHERE pair_key=?',(pair,)).fetchone()
            confirmations=(prior[1]+int(prior[0]!=window_key)) if prior and now-prior[2]<=window_seconds else 1
            self.db.execute('INSERT INTO merge_candidates VALUES (?,?,?,?) ON CONFLICT(pair_key) DO UPDATE SET window_key=excluded.window_key,confirmations=excluded.confirmations,last_seen=excluded.last_seen',(pair,window_key,confirmations,now))
            if confirmations<2:continue
            winner,loser=sorted((a,b),key=lambda p:(people[p][1],p))
            evidence={'method':'multi_prototype_reciprocal_window','prototype_pairs':count,'cosine':strength,'rerank_distance':refined,'confirmations':confirmations,'window_seconds':window_seconds,'threshold':self.relaxed_threshold}
            self.merge(loser,winner,now,evidence)
            proposals.append({'loser':loser,'winner':winner,**evidence})
            break # Recompute graph after each merge; avoid chaining from a stale graph.
        return proposals

    def merge(self, loser, winner, now, evidence):
        loser,winner=self.resolve(loser),self.resolve(winner)
        if loser==winner:return
        if self.conflict(loser,winner):raise ValueError('co_visible_identities_cannot_merge')
        key=sha256(f'{loser}:{winner}'.encode()).hexdigest()
        backup={'people':[(p,m,b.hex(),t) for p,m,b,t in self.db.execute('SELECT * FROM people WHERE person_id IN (?,?)',(loser,winner))],
                'features':[(p,v.tobytes().hex(),q,t,k) for p,v,q,t,k in self.vectors({loser,winner})],
                'aliases':self.db.execute('SELECT * FROM person_aliases WHERE person_id IN (?,?)',(loser,winner)).fetchall()}
        self.db.execute('INSERT OR IGNORE INTO identity_merge_backups VALUES (?,?)',(key,zlib.compress(json.dumps(backup).encode())))
        self.db.execute('INSERT OR IGNORE INTO identity_merges VALUES (?,?,?,?,?)',(key,loser,winner,now,json.dumps(evidence)))
        self.db.execute('INSERT OR REPLACE INTO person_aliases VALUES (?,?,?)',(loser,winner,now))
        self.db.execute('UPDATE person_aliases SET person_id=? WHERE person_id=?',(winner,loser))
        self.db.execute('UPDATE person_features SET person_id=? WHERE person_id=?',(winner,loser))
        self.db.execute('UPDATE recent_observations SET person_id=? WHERE person_id=?',(winner,loser))
        self.db.execute('UPDATE people SET last_seen=MAX(last_seen,COALESCE((SELECT last_seen FROM people WHERE person_id=?),last_seen)) WHERE person_id=?',(loser,winner))
        self.db.execute('DELETE FROM people WHERE person_id=?',(loser,))
        rows=self.vectors({winner})
        if rows:self.observe(winner,rows[0][1],rows[0][2],now,rows[0][4]) # Reapply the bank bound.
