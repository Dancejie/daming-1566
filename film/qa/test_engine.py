"""Meaningful contract checks on all authored branches; no network or user saves."""
import copy
import json
import sys
import unittest
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'backend'))
from engine import Engine,StoryError,RevisionConflict


def engine():
    chars=json.loads((ROOT/'content/characters.json').read_text())
    if isinstance(chars,dict):chars=chars['characters']
    return Engine(json.loads((ROOT/'content/story.json').read_text()),chars)


class ContractTests(unittest.TestCase):
    def setUp(self):self.e=engine()
    def act(self,run,**kw):return self.e.act(run,{'revision':run['revision'],**kw})
    def seek(self,kind):
        run=self.e.create()
        for _ in range(100):
            _,beat=self.e.current(run)
            if beat['type']==kind:return run
            if beat['type']=='choice':run=self.act(run,type='choose',optionId=next(o['id'] for o in beat['options'] if self.e.eligible(o.get('requires'),run['state'])))
            else:run=self.act(run,type='advance')
        self.fail('Missing '+kind)
    def test_choices_cannot_be_skipped(self):
        run=self.seek('choice')
        with self.assertRaises(StoryError):self.act(run,type='advance')
        with self.assertRaises(StoryError):self.act(run,type='choose',optionId='invented')
    def test_revision_conflict(self):
        run=self.e.create()
        with self.assertRaises(RevisionConflict):self.e.act(run,{'revision':-1,'type':'advance'})
    def test_media_is_presentation_only(self):
        run=self.e.create();before=copy.deepcopy(run)
        for _ in range(5):self.e.public(run)
        self.assertEqual(run,before)
        with self.assertRaises(StoryError):self.act(run,type='media_finished')
    def test_free_input_requires_explicit_confirmation(self):
        run=self.e.create()
        run['position']=next(i for i,(_,b) in enumerate(self.e.beats) if b['type']=='free_input')
        before=copy.deepcopy(run['state'])
        preview=self.act(run,type='free_input',text='请先核实账册的证据，再决定是否上疏。')
        self.assertEqual(preview['state'],before)
        self.assertEqual(preview['position'],run['position'])
        self.assertTrue(preview['proposal']['requiresConfirmation'])
        with self.assertRaises(StoryError):self.act(run,type='choose',optionId='invented')
        committed=self.act(preview,type='choose',optionId=preview['proposal']['ruleId'])
        self.assertEqual(committed['position'],preview['position']+1)
        self.assertEqual(len(committed['history']),1)
    def test_actual_delta_is_clamped(self):
        run=self.e.create();_,beat=self.e.current(run)
        key=next(iter(self.e.stats));run['state']['stats'][key]=99
        self.e.patch(run,{'id':'qa.clamp','effects':{'stats':{key:20}},'consequence':'test'},beat)
        self.assertEqual(run['state']['stats'][key],100)
        self.assertEqual(run['receipt']['changes'][0]['delta'],1)
        with self.assertRaises(StoryError):self.e.patch(run,{'id':'qa.clamp'},beat)
    def test_rejected_input_and_exact_memory(self):
        run=self.e.create();run['position']=next(i for i,(_,b) in enumerate(self.e.beats) if b['type']=='free_input')
        before=copy.deepcopy(run)
        with self.assertRaises(StoryError):self.act(run,type='free_input',text='请伪造圣旨再核验原账')
        self.assertEqual(run,before)
        text='原账留下，我担经手的责任。'
        preview=self.act(run,type='free_input',text=text)
        result=self.act(preview,type='choose',optionId=preview['proposal']['ruleId'])
        self.assertEqual(result['state']['memories']['courtReply']['text'],text)
    def test_compatible_saves_preserve_state(self):
        for version in self.e.story.get('compatibleSaveVersions',[]):
            run=self.e.create();run['contentVersion']=version
            result=self.act(run,type='advance')
            self.assertEqual(result['contentVersion'],self.e.story['version'])
            self.assertEqual(result['state'],run['state'])
    def test_declined_grain_not_granted_in_settlement(self):
        run=self.e.create();run['position']=len(self.e.beats)-1
        run['state']['flags'].update(finalRoute='sealed',grainRoute='official-pending')
        self.e.finish_or_advance(run)
        text=''.join(run['ending']['settlement'])
        self.assertIn('未接',text)
        self.assertNotIn('逐袋核收',text)
    def test_all_authored_endings_reachable_and_bounded(self):
        frontier=[self.e.create()];seen_endings={};largest=0
        # Merge equivalent states at each beat, retaining one real route as evidence.
        for position in range(len(self.e.beats)+1):
            next_runs={}
            for run in frontier:
                if run['status']=='ending':
                    seen_endings.setdefault(run['ending']['id'],run['history']);continue
                _,beat=self.e.current(run)
                if beat['type']=='choice':
                    candidates=[{'type':'choose','optionId':o['id']} for o in beat['options'] if self.e.eligible(o.get('requires'),run['state'])]
                elif beat['type']=='free_input':
                    candidates=[{'type':'free_input','text':(r.get('keywords') or ['复核'])[0],'_rule':r['id']} for r in beat['rules'] if self.e.eligible(r.get('requires'),run['state'])]
                elif beat['type']=='qte':candidates=[{'type':'qte','outcome':outcome} for outcome in ('success','failure')]
                else:candidates=[{'type':'advance'}]
                self.assertTrue(candidates,beat['id']+' has no eligible action')
                for candidate in candidates:
                    wanted=candidate.pop('_rule',None)
                    result=self.act(run,**candidate)
                    if wanted:
                        # Rules are independently legal candidate IDs; intent recognition is tested separately.
                        result['proposal']['ruleId']=wanted
                        result=self.act(result,type='choose',optionId=wanted)
                    for key,value in result['state']['stats'].items():
                        self.assertGreaterEqual(value,self.e.stats[key]['min']);self.assertLessEqual(value,self.e.stats[key]['max'])
                    if result['status']=='ending':seen_endings.setdefault(result['ending']['id'],result['history'])
                    else:
                        fingerprint=json.dumps([result['position'],result['state']['stats'],result['state']['flags'],result['state']['relationships']],sort_keys=True)
                        next_runs.setdefault(fingerprint,result)
            frontier=list(next_runs.values());largest=max(largest,len(frontier))
            if not frontier:break
        expected={e['id'] for e in self.e.story['endings']}
        self.assertEqual(set(seen_endings),expected)
        report={'reachableEndings':list(seen_endings),'largestFrontier':largest,
                'exampleRoutes':{key:[x['action'] for x in hist] for key,hist in seen_endings.items()}}
        (ROOT/'qa/ending-reachability.json').write_text(json.dumps(report,ensure_ascii=False,indent=2))


if __name__=='__main__':unittest.main(verbosity=2)
