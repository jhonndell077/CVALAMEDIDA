"""Keep manual edits authoritative when document evidence is reconstructed."""
import copy
from profile_deletions import identity, matching_indices, ambiguity_warning
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
            edits.append({'section':section,'identity':identity(old),'previous':copy.deepcopy(old),'value':copy.deepcopy(match)})
    overrides=result.setdefault('_candidate_edits',{})
    for key,value in updated['candidate'].items():
        if value!=previous['candidate'].get(key): overrides[key]=copy.deepcopy(value)
    return result


def apply(profile, warnings=None):
    result=copy.deepcopy(profile)
    result['candidate'].update(result.get('_candidate_edits',{}))
    for edit in result.get('_manual_edits',[]):
        records=result[edit['section']]
        matches=matching_indices(records,edit['identity'],edit.get('previous'))
        if len(matches)>1:
            ambiguity_warning(warnings,edit['section'],'edición')
        if len(matches)==1:
            for index in matches:
                if edit['value'] is None: records.pop(index)
                else:
                    replacement=copy.deepcopy(edit['value'])
                    original=edit.get('previous')
                    current=records[index]
                    if isinstance(replacement,dict) and isinstance(original,dict) and isinstance(current,dict):
                        # Consolidation may already have combined another record.
                        # Replace this record's old list entries, retaining all
                        # complementary entries from the other record.
                        for key,desired in replacement.items():
                            if not isinstance(desired,list) or not isinstance(current.get(key),list): continue
                            prior=original.get(key,[])
                            prior_ids={item.get('id') for item in prior if isinstance(item,dict) and item.get('id')}
                            prior_values={identity(item) for item in prior}
                            extra=[item for item in current[key] if identity(item) not in prior_values
                                and not (isinstance(item,dict) and item.get('id') in prior_ids)]
                            replacement[key]=desired+copy.deepcopy(extra)
                    records[index]=replacement
    return consolidate(result)
