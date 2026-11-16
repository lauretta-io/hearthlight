"""Explicit proposed starts/ends; the state reducer confirms actual transitions."""
KEYS=('new_interactions','ended_interactions','new_possessions','ended_possessions')
from object_semantics import is_fixed_fixture
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
    return values,issues


def empty_changes():
    return {key:[] for key in KEYS}
