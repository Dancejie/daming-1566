"""Original chapter: causal branches, memory, edition isolation and media gates."""
import copy,importlib.util,json,sys,tempfile,threading,unittest,urllib.request,urllib.error
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT));sys.path.insert(0,str(ROOT/'film/backend'))
from engine import Engine,StoryError
spec=importlib.util.spec_from_file_location('published',ROOT/'server.py');pub=importlib.util.module_from_spec(spec);spec.loader.exec_module(pub)
class OriginalTests(unittest.TestCase):
 @classmethod
 def setUpClass(cls):
  cls.tmp=tempfile.TemporaryDirectory(prefix='ming-original-tests-')
  pub.film.DB=Path(cls.tmp.name)/'old.sqlite3';pub.original.DB=Path(cls.tmp.name)/'new.sqlite3'
  pub.film.initialize();pub.original.initialize()
  cls.http=pub.ThreadingHTTPServer(('127.0.0.1',0),pub.PublishedHandler)
  cls.t=threading.Thread(target=cls.http.serve_forever,daemon=True);cls.t.start();cls.base=f'http://127.0.0.1:{cls.http.server_port}'
  cls.story=json.loads((ROOT/'original/content/story.json').read_text());cls.chars=json.loads((ROOT/'original/content/characters.json').read_text())['characters'];cls.e=Engine(cls.story,cls.chars)
 @classmethod
 def tearDownClass(cls):cls.http.shutdown();cls.http.server_close();cls.t.join();cls.tmp.cleanup()
 def api(self,path,body=None):
  req=urllib.request.Request(self.base+path,data=json.dumps(body).encode() if body is not None else None,headers={'Content-Type':'application/json'})
  try:r=urllib.request.urlopen(req,timeout=10)
  except urllib.error.HTTPError as ex:r=ex
  with r:return r.status,r.read()
 def walk(self,route):
  r=self.e.create();text='这件事还得慢慢说明'
  while r['status']=='active':
   b=self.e.public(r)['beat'];typ=b['type']
   if typ=='choice':a={'type':'choose','optionId':next((o['id'] for o in b['options'] if o['id']=='ending.'+route),b['options'][0]['id'])}
   elif typ=='qte':a={'type':'qte','outcome':'failure' if route=='formal' else 'success'}
   elif typ=='free_input':
    before=copy.deepcopy(r['state']);r=self.e.act(r,{'type':'free_input','text':text,'revision':r['revision']});self.assertEqual(r['state'],before);self.assertEqual(r['proposal']['ruleId'],'reply.clarify');a={'type':'choose','optionId':r['proposal']['ruleId']}
   else:a={'type':'advance'}
   r=self.e.act(r,{**a,'revision':r['revision']})
  return r,text
 def test_all_four_outcomes_preserve_canon_and_restore(self):
  for route,shot in [('food','R09'),('audit','R10'),('execution','R11'),('formal','R12')]:
   r,text=self.walk(route);self.assertEqual(r['ending']['id'],route);self.assertEqual(r['ending']['shotId'],shot)
   self.assertEqual(r['state']['memories']['ownPrinciple']['text'],text)
   self.assertEqual(r['state']['relationships']['hairui'],0);self.assertEqual(r['state']['relationships']['huzongxian'],0)
   restored=self.e.restore({'contentVersion':r['contentVersion'],'actionLog':r['actionLog']});self.assertEqual(restored['state'],r['state']);self.assertEqual(restored['ending'],r['ending'])
   self.assertLess(len(r['actionLog']),100)
 def test_old_save_is_rejected_by_new_edition(self):
  with self.assertRaises(StoryError):self.e.restore({'contentVersion':'1.1.0','actionLog':[]})
 def test_only_committed_route_owns_result_video(self):
  common={b['shotId'] for s in self.story['scenes'] for b in s['beats'] if b.get('shotId')}
  self.assertEqual(common,{f'R{i:02}' for i in range(1,9)})
  self.assertFalse(common & {e['shotId'] for e in self.story['endings']})
 def test_editions_use_different_databases_and_contracts(self):
  code,raw=self.api('/original/api/runs',{});self.assertEqual(code,201);new=json.loads(raw)
  code,raw=self.api('/api/runs',{});self.assertEqual(code,201);old=json.loads(raw)
  self.assertEqual(new['contentVersion'],'2.0.0');self.assertEqual(old['contentVersion'],'1.1.0')
  self.assertEqual(self.api('/original/api/runs/'+old['id'])[0],404)
  self.assertEqual(self.api('/api/runs/'+new['id'])[0],404)
  code,raw=self.api('/original/api/bootstrap');self.assertEqual(json.loads(raw)['story']['id'],'ming1566-original-opening')
 def test_static_and_private_routes(self):
  for path in ['/original/','/storm/','/classic/','/original/style.css','/original/app.js','/assets/characters/xujie/xujie_base.png','/original/assets/anchors/xiyuan-fiscal-room-v2.png']:
   self.assertEqual(self.api(path)[0],200,path)
  for path in ['/original/private/runs.sqlite3','/original/content/story.json','/original/production/media-plan.json','/original/%2e%2e/server.py','/server.py']:
   self.assertEqual(self.api(path)[0],404,path)
 def test_new_health_and_root_entry(self):
  code,raw=self.api('/api/health');health=json.loads(raw);self.assertEqual(health['contentVersion'],'2.0.0')
  with urllib.request.urlopen(self.base+'/') as r:self.assertTrue(r.url.endswith('/original/'))
if __name__=='__main__':unittest.main()
