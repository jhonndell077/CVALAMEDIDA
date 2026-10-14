"""Keep manual edits authoritative when document evidence is reconstructed."""
import copy
from profile_deletions import identity
from profile_records import consolidate, SECTIONS


def prepare(base, previous, updated):
    result=copy.deepcopy(updated)
    for key,value in base.items():
        if key.startswith('_'): result[key]=copy.deepcopy(value)
    edits=result.setdefault('_manual_edits',[])
    for section in SECTIONS:
        new=updated[section]
        for index,old in enumerate(previous[section]):
            if old in new: continue
            match=next((item for item in new if isinstance(old,dict) and isinstance(item,dict) and old.get('id') and item.get('id')==old['id']),None)
            if match is None and len(new)==len(previous[section]): match=new[index]
            edits.append({'section':section,'identity':identity(old),'value':copy.deepcopy(match)})
    overrides=result.setdefault('_candidate_edits',{})
    for key,value in updated['candidate'].items():
        if value!=previous['candidate'].get(key): overrides[key]=copy.deepcopy(value)
    return result


def apply(profile):
    result=copy.deepcopy(profile)
    result['candidate'].update(result.get('_candidate_edits',{}))
    for edit in result.get('_manual_edits',[]):
        records=result[edit['section']]
        for index in range(len(records)-1,-1,-1):
            if identity(records[index])==edit['identity']:
                if edit['value'] is None: records.pop(index)
                else: records[index]=copy.deepcopy(edit['value'])
    return consolidate(result)
