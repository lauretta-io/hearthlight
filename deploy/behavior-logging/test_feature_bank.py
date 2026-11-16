from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch
import unittest
import numpy as np
from person_reid import PersonGallery,unit_vector

class BankTests(unittest.TestCase):
 def setUp(self):
  self.temp=TemporaryDirectory();self.addCleanup(self.temp.cleanup)
  self.path=Path(self.temp.name)/'gallery.sqlite3';self.gallery=PersonGallery(self.path,'test');self.addCleanup(self.gallery.db.close)
 def person(self,name,vector,birth):
  vector=unit_vector(vector)
  with self.gallery.db:
   self.gallery.db.execute('INSERT INTO people VALUES (?,?,?,?)',(name,'test',vector.tobytes(),1000))
   self.gallery.db.execute('INSERT INTO identity_births VALUES (?,?,?)',(name,'test',birth))
  return vector
 def test_bank_bounds_quality_diversity_and_restart(self):
  vector=self.person('old',[1,0],1)
  with self.gallery.db:
   for i in range(20):self.gallery.bank.observe('old',unit_vector([1,i/20]),.8,1000+i,str(i))
   self.gallery.bank.observe('old',vector,.1,2000,'bad-crop')
  rows=self.gallery.bank.vectors({'old'});self.assertEqual(len(rows),8);self.assertNotIn('bad-crop',[r[4] for r in rows]);self.assertGreater(max(1-float(a[1]@b[1]) for a in rows for b in rows),.1)
  other=PersonGallery(self.path,'test');self.addCleanup(other.db.close);self.assertEqual(len(other.bank.vectors({'old'})),8)
 def test_non_overlapping_track_fragments_can_share_an_id(self):
  left=np.array([1,0],np.float32);person,=self.gallery.assign([left])
  tracks=[[(0,None),(1,None)],[(3,None),(4,None)]]
  self.assertEqual(self.gallery.assign([left,left],tracks=tracks),[person,person])
  self.assertEqual(self.gallery.assign([left,left],tracks=[[(0,None)],[(0,None)]]),[None,None])
 def test_relaxed_match_requires_two_prototypes_and_does_not_teach(self):
  old=self.person('old',[1,0],1);self.person('different',[0,-1],2)
  vector=unit_vector([.79,.61])
  with self.gallery.db:
   self.gallery.bank.observe('old',old,.8,1000,'a')
  self.assertIsNone(self.gallery.bank.relaxed_candidate(vector,{'old','different'}))
  with self.gallery.db:self.gallery.bank.observe('old',unit_vector([1,.01]),.8,1001,'b')
  with patch('feature_bank.reciprocal_distances',side_effect=lambda x,n:np.clip(1-x[:n]@x[n:].T,0,2)):
   self.assertEqual(self.gallery.bank.relaxed_candidate(vector,{'old','different'}),'old')
   with patch('person_reid.time',return_value=1002):self.assertEqual(self.gallery.assign([vector]),['old'])
  self.assertEqual(len(self.gallery.bank.vectors({'old'})),2)
 def seed_merge(self):
  self.person('old',[1,0],1);self.person('young',[1,.1],2);self.person('other',[0,-1],3)
  with self.gallery.db:
   for person in ['old','young']:
    for i in range(3):self.gallery.bank.observe(person,unit_vector([1,.01*i+(.05 if person=='young' else 0)]),.8,1000+i,f'{person}:{i}')
   self.gallery.bank.observe('other',unit_vector([0,-1]),.8,1000,'negative')
 def test_merge_needs_two_windows_is_durable_and_idempotent(self):
  self.seed_merge()
  with patch('feature_bank.reciprocal_distances',side_effect=lambda x,n:np.clip(1-x[:n]@x[n:].T,0,2)):
   with self.gallery.db:
    self.assertEqual(self.gallery.bank.merge_window(1002,'window-a'),[])
    self.assertEqual(self.gallery.bank.merge_window(1002,'window-a'),[])
    merged=self.gallery.bank.merge_window(1003,'window-b')
   self.assertEqual(len(merged),1);self.assertEqual(merged[0]['winner'],'old');self.assertEqual(self.gallery.bank.resolve('young'),'old')
   with self.gallery.db:self.assertEqual(self.gallery.bank.merge_window(1004,'window-c'),[])
  self.assertEqual(self.gallery.db.execute('SELECT COUNT(*) FROM identity_merges').fetchone()[0],1)
  self.assertEqual(self.gallery.db.execute("SELECT COUNT(*) FROM identity_births WHERE person_id='young'").fetchone()[0],1)
  other=PersonGallery(self.path,'test');self.addCleanup(other.db.close);self.assertEqual(other.bank.resolve('young'),'old')
 def test_co_visible_identities_never_merge(self):
  self.seed_merge()
  with self.gallery.db:self.gallery.bank.record_conflicts([[(0,None)],[(0,None)]],['old','young'])
  with patch('feature_bank.reciprocal_distances',side_effect=lambda x,n:np.clip(1-x[:n]@x[n:].T,0,2)):
   with self.gallery.db:
    self.assertEqual(self.gallery.bank.merge_window(1002,'a'),[]);self.assertEqual(self.gallery.bank.merge_window(1003,'b'),[])
 def test_alias_cycle_is_rejected(self):
  self.gallery.db.execute("INSERT INTO person_aliases VALUES ('a','b',1)");self.gallery.db.execute("INSERT INTO person_aliases VALUES ('b','a',1)")
  with self.assertRaises(ValueError):self.gallery.bank.resolve('a')
