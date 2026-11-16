"""Explicit proposed starts/ends; the state reducer confirms actual transitions."""
KEYS=('new_interactions','ended_interactions','new_possessions','ended_possessions')
import json
import re
from object_semantics import is_fixed_fixture
from interaction_format import normalize_object_kind
RELEASES={'put_down','give'}


def change_inputs(report,track):
    explicit=any(key in report for key in KEYS)
    issues=[]
    values={key:report.get(key,[]) for key in KEYS}
    if explicit:
        for key in KEYS:
            if key not in report or not isinstance(values[key],list) or len(values[key])>8:
                issues.append('invalid_'+key);values[key]=[]
    else:
        events=report.get('events',[])
        if isinstance(events,list):
            for event in events:
                values['ended_possessions' if isinstance(event,dict) and event.get('action') in RELEASES else 'new_possessions'].append(event)
        else:issues.append('invalid_activity_events')
        values['new_interactions']=report.get('interactions',[])
        if not isinstance(values['new_interactions'],list):issues.append('invalid_interactions');values['new_interactions']=[]
    prior={row.get('reference_key'):row for row in track.get('prior_state',[]) if row.get('target_kind')=='object' and row.get('reference_key')}
    for key,rows in values.items():
        valid=[]
        for value in rows[:8]:
            if not isinstance(value,dict):issues.append('invalid_'+key);continue
            row=dict(value);reference=row.get('reference_key')
            actor_id=row.get('actor_track_id')
            if actor_id is not None:
                if isinstance(actor_id,str) and actor_id.isdecimal():actor_id=int(actor_id)
                if type(actor_id) is not int or actor_id!=track.get('track_id'):
                    issues.append('change_actor_track_mismatch');continue
                if row.get('actor')!='unclear':row['actor']='target'
            if reference is not None:
                if not isinstance(reference,str) or reference not in prior:
                    issues.append('unrecognized_change_reference');continue
                row['item']=prior[reference]['item'];row['appearance']=prior[reference]['appearance']
            if key=='ended_possessions':
                if is_fixed_fixture(row.get('item')):
                    issues.append('fixed_fixture_cannot_end_possession');continue
                if row.get('action') in {'no_longer_visible','not_visible'} and row.get('certainty')=='unclear':row['action']='unclear'
                if row.get('action') not in RELEASES|{'unclear'}:
                    issues.append('invalid_possession_end_action');continue
            elif key=='new_possessions' and row.get('action') in RELEASES:
                issues.append('release_must_be_in_ended_possessions');continue
            valid.append(row)
        values[key]=valid
    if explicit:
        endings=[]
        for row in values['ended_interactions']:
            evidence=str(row.get('evidence','')).lower()
            ending=bool(re.search(r"\b(away|withdraw|withdrew|stop|stops|stopped|cease|ceased|ended|ends|finish|finished|release|released|separat|disengag)\w*\b|no longer|(?:hand|fingers?) (?:leaves?|left) (?:the )?(?:shelf|table|keyboard|surface)|hand.{0,30}(off|clear)|lift.{0,20}(off|clear)",evidence))
            continuing=bool(re.search(r"\b(is|are) (using|typing|touching|operating)|hand.{0,40}\b(on|touching|contact)|continues? (to )?(use|touch|typ)",evidence))
            if not ending and continuing:
                values['new_interactions'].append(row)
                issues.append('ongoing_contact_misfiled_as_end')
            else:
                if not ending and row.get('certainty')=='clear':
                    row={**row,'certainty':'unclear'}
                    issues.append('end_evidence_incomplete')
                endings.append(row)
        values['ended_interactions']=endings
    fields=('target_kind' ,'interaction_type','item','appearance','actor','certainty','start_frame','end_frame','evidence')
    def identity(row):
        row=normalize_object_kind(row)
        return json.dumps([row.get(field) for field in fields],sort_keys=True)
    values['new_interactions']=list({identity(row):row for row in values['new_interactions']}.values())
    starts={identity(row) for row in values['new_interactions']}
    endings=[]
    for row in values['ended_interactions']:
        if identity(row) in starts:
            issues.append('duplicated_start_end_evidence')
        else:endings.append(row)
    values['ended_interactions']=endings
    return values,issues


def empty_changes():
    return {key:[] for key in KEYS}
