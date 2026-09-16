"""Ming's authored story, using EchoDrama EffectIntent -> StatePatch contracts.

The existing Ming cast/story is adapted by content, never by a media callback.
The engine owns eligibility, clamps, memories, revision and ending selection.
"""
import copy
import json
import uuid


class StoryError(ValueError):
    pass


class RevisionConflict(StoryError):
    pass


class Engine:
    MAX_ACTIONS = 100
    MAX_CHECKPOINT_BYTES = 20000

    def __init__(self, story, characters):
        self.story = story
        self.characters = characters
        self.beats = [(i, b) for i, scene in enumerate(story['scenes']) for b in scene['beats']]
        self.stats = {s['id']: s for s in story['statDefinitions']}

    def create(self):
        return {'id': uuid.uuid4().hex, 'contentVersion': self.story['version'], 'revision': 0,
                'position': 0, 'state': copy.deepcopy(self.story['initialState']),
                'history': [], 'appliedPatchKeys': [], 'status': 'active', 'receipt': None,
                'proposal': None, 'ending': None, 'actionLog': []}

    def canonical_action(self, payload, strict=False):
        if not isinstance(payload,dict): raise StoryError('存档动作格式无效')
        action=payload.get('type')
        fields={'advance':(), 'choose':('optionId',), 'free_input':('text',), 'qte':('outcome',)}
        if not isinstance(action,str) or action not in fields: raise StoryError('未知行动')
        keys={'type',*fields[action]}
        if strict and set(payload)!=keys: raise StoryError('存档只能包含动作，不接受状态数值')
        result={'type':action}
        for key in fields[action]:
            value=payload.get(key)
            if not isinstance(value,str) or not value.strip(): raise StoryError('存档动作参数无效')
            result[key]=value.strip() if key=='text' else value
        return result

    def validate_checkpoint_size(self, checkpoint):
        if len(json.dumps(checkpoint,ensure_ascii=False,separators=(',',':')).encode('utf-8'))>self.MAX_CHECKPOINT_BYTES:
            raise StoryError('动作存档超过 20KB，请另起一局')

    def restore(self, checkpoint):
        if not isinstance(checkpoint,dict) or set(checkpoint)!={'contentVersion','actionLog'}:
            raise StoryError('恢复需要剧本版本与完整动作记录，不接受状态数值')
        version=checkpoint['contentVersion']
        if not isinstance(version,str) or version not in [self.story['version'],*self.story.get('compatibleSaveVersions',[])]:
            raise StoryError('此本机存档属于不兼容的剧本版本，无法恢复')
        actions=checkpoint['actionLog']
        if not isinstance(actions,list): raise StoryError('本机存档缺少完整动作记录')
        if len(actions)>self.MAX_ACTIONS: raise StoryError('动作存档最多允许 100 步')
        self.validate_checkpoint_size(checkpoint)
        # Replay from authored initial state; never accept client state, revision or receipts.
        run=self.create()
        for payload in actions:
            action=self.canonical_action(payload,strict=True)
            run=self.act(run,{**action,'revision':run['revision']})
        return run

    def eligible(self, requires, state):
        for rule in requires or []:
            if 'stat' in rule:
                value = state['stats'].get(rule['stat'], 0)
                if 'min' in rule and value < rule['min']: return False
                if 'max' in rule and value > rule['max']: return False
            if 'flag' in rule and state['flags'].get(rule['flag'], False) != rule.get('equals', True):
                return False
            if 'relationship' in rule:
                value = state['relationships'].get(rule['relationship'], 0)
                if value < rule.get('min', 0): return False
        return True

    def current(self, run):
        return self.beats[min(run['position'], len(self.beats)-1)]

    def public(self, run):
        result = copy.deepcopy(run)
        scene_index, beat = self.current(run)
        scene = self.story['scenes'][scene_index]
        result['sceneIndex'] = scene_index
        result['scene'] = {k: v for k, v in scene.items() if k != 'beats'}
        result['scene']['firstBeatId'] = scene['beats'][0]['id']
        result['beat'] = copy.deepcopy(beat)
        result['beat'].pop('rules', None)
        result['beat'].pop('denyKeywords', None)
        for option in result['beat'].get('options', []):
            option['disabled'] = not self.eligible(option.get('requires'), run['state'])
        callback = beat.get('memoryCallback')
        if callback:
            memory = run['state']['memories'].get(callback['key'])
            if memory:
                text = memory.get('text','') if isinstance(memory,dict) else str(memory)
                result['beat']['text'] = callback.get('prefix','') + text + callback.get('suffix','')
            else:
                result['beat']['text'] = callback.get('fallback',beat['text'])
        result.pop('appliedPatchKeys', None)
        return result

    def patch(self, run, intent, beat, text=None):
        patch_key = f"{beat['id']}:{intent.get('id','resolve')}"
        if patch_key in run['appliedPatchKeys']:
            raise StoryError('这个行动已经结算')
        effects = intent.get('effects', {})
        changes = []
        for category in ['stats', 'relationships']:
            for key, delta in effects.get(category, {}).items():
                before = run['state'][category].get(key,0)
                definition = self.stats.get(key,{}) if category == 'stats' else {}
                after = min(definition.get('max',100), max(definition.get('min',0), before+delta))
                run['state'][category][key] = after
                label = definition.get('label', next((c['name']+'信任' for c in self.characters if c['id']==key),key))
                changes.append({'id':key,'label':label,'delta':after-before,'value':after})
        run['state']['flags'].update(effects.get('flags',{}))
        memory = effects.get('memory')
        if memory:
            remembered={**memory,'beatId':beat['id'],'playerInput':text}
            remembered['text']=str(memory.get('text','')).replace('{input}',text or '')
            run['state']['memories'][memory['key']] = remembered
        run['appliedPatchKeys'].append(patch_key)
        run['receipt'] = {'text':intent.get('consequence',intent.get('text','已记录')),
                          'responseText':intent.get('responseText',intent.get('text','')),
                          'responseSpeaker':intent.get('responseSpeaker','旁白'), 'changes':changes,
                          'effectIntentId':intent.get('id'), 'patchKey':patch_key}
        run['history'].append({'beatId':beat['id'],'sceneId':self.story['scenes'][self.current(run)[0]]['id'],
                               'action':intent.get('label',intent.get('id','行动')),
                               'playerText':text or intent.get('playerText',''),
                               'responseText':intent.get('responseText',intent.get('text','')),
                               'consequence':run['receipt']['text'],'changes':changes})

    def finish_or_advance(self, run):
        if run['position'] >= len(self.beats)-1:
            ending = next((e for e in self.story['endings'] if self.eligible(e.get('requires'), run['state'])), None)
            if ending is None: raise StoryError('结局条件尚未覆盖当前状态')
            run['status'] = 'ending'
            run['ending'] = copy.deepcopy(ending)
            run['ending']['settlement'] = [*run['ending'].get('settlement',[]),
                *[rule['text'] for rule in self.story.get('settlementRules',[])
                  if self.eligible(rule.get('requires'),run['state'])]]
        else:
            run['position'] += 1
        run['proposal'] = None

    def act(self, original, payload):
        if payload.get('revision') != original['revision']:
            raise RevisionConflict('存档已推进，请载入当前进度')
        if original['contentVersion'] != self.story['version'] and original['contentVersion'] not in self.story.get('compatibleSaveVersions',[]):
            raise StoryError('此存档属于其他剧本版本，请开始新一局')
        if original['status'] != 'active': raise StoryError('本局已经结束')
        canonical=self.canonical_action(payload)
        if len(original.get('actionLog',[]))>=self.MAX_ACTIONS: raise StoryError('动作存档最多允许 100 步')
        run = copy.deepcopy(original)
        run['contentVersion'] = self.story['version']
        _, beat = self.current(run)
        action = payload.get('type')
        run['receipt'] = None
        if action == 'free_input':
            if beat['type'] != 'free_input': raise StoryError('此处暂不可自由陈情')
            text = str(payload.get('text','')).strip()
            limit=beat.get('maxLength',600)
            if not text or len(text)>limit: raise StoryError(f'请写下 1 至 {limit} 字的陈情')
            deny = any(word in text for word in beat.get('denyKeywords',[]))
            if deny: raise StoryError(beat.get('denialText','此处不能伪造证据、假传授权或改写已发生的事实。请重新陈情。'))
            candidates = [r for r in beat.get('rules',[]) if self.eligible(r.get('requires'),run['state'])]
            scores = [(sum(len(k) for k in r.get('keywords',[]) if k in text),r) for r in candidates]
            best = max(scores,key=lambda item:item[0]) if scores else (0,None)
            chosen = best[1] if best[0]>0 and not deny else next((r for r in candidates if r['id']==beat['fallbackRuleId']),None)
            if not chosen: raise StoryError('当前没有合法的陈情方向')
            run['proposal'] = {'ruleId':chosen['id'],'label':chosen['label'],
                               'responseText':chosen.get('responseText',''),'text':text,
                               'mode':'authored-rules','requiresConfirmation':True}
        elif action == 'choose':
            options = beat.get('options',[])
            if beat['type']=='free_input':
                proposal = run.get('proposal')
                if not proposal or payload.get('optionId') != proposal['ruleId']:
                    raise StoryError('请先陈情，再确认行动方向')
                options = beat['rules']
            elif beat['type'] != 'choice': raise StoryError('当前不是抉择节点')
            chosen = next((o for o in options if o['id']==payload.get('optionId')),None)
            if not chosen or not self.eligible(chosen.get('requires'),run['state']):
                raise StoryError('此行动的条件尚未满足')
            self.patch(run,chosen,beat,(run.get('proposal') or {}).get('text'))
            self.finish_or_advance(run)
        elif action == 'qte':
            if beat['type']!='qte': raise StoryError('当前没有限时行动')
            outcome = payload.get('outcome')
            if outcome not in ('success','failure'): raise StoryError('无效的行动结果')
            self.patch(run,{'id':'qte.'+outcome,**beat[outcome]},beat)
            self.finish_or_advance(run)
        elif action == 'advance':
            if beat['type'] not in ('narration','dialogue'): raise StoryError('请先完成当前行动')
            self.finish_or_advance(run)
        else: raise StoryError('未知行动')
        run['revision'] += 1
        run.setdefault('actionLog',[]).append(canonical)
        self.validate_checkpoint_size({'contentVersion':run['contentVersion'],'actionLog':run['actionLog']})
        return run
