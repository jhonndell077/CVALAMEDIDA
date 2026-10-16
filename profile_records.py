"""Semantic record identity and lossless consolidation; no network or data writes."""
import copy
import hashlib
import json
import re
import unicodedata
from urllib.parse import urlsplit

SECTIONS = ('projects', 'experiences', 'courses', 'education', 'references', 'skills', 'not_documented')

def normalized(value):
    if not isinstance(value, str): return ''
    value = unicodedata.normalize('NFKD', value.casefold())
    return ' '.join(''.join(c for c in value if not unicodedata.combining(c)).split())

def phone(value):
    digits = re.sub(r'\D', '', str(value or ''))
    return '1'+digits if len(digits)==10 and digits[:3] in ('809','829','849') else digits

def url(value):
    try: parts = urlsplit(value or '')
    except ValueError: return value
    return (parts.netloc.casefold(), parts.path.rstrip('/'), parts.query) if value else None

def compatible(section, a, b):
    if not isinstance(a, dict) or not isinstance(b, dict): return normalized(a)==normalized(b)
    if section == 'references': return normalized(a.get('name'))==normalized(b.get('name')) and phone(a.get('phone'))==phone(b.get('phone'))
    if section in ('skills','not_documented'):
        key = 'label' if section=='skills' else 'text'
        return bool(normalized(a.get(key))) and normalized(a.get(key))==normalized(b.get(key))
    if not normalized(a.get('title')) or normalized(a.get('title'))!=normalized(b.get('title')): return False
    if section == 'projects': return not a.get('url') or not b.get('url') or url(a['url'])==url(b['url'])
    key = 'employer' if section=='experiences' else 'institution'
    if normalized(a.get(key))!=normalized(b.get(key)): return False
    dates = ('start_date','end_date') if section=='experiences' else ('date',)
    return all(not a.get(key) or not b.get(key) or normalized(a[key])==normalized(b[key]) for key in dates)

def find_record(records, section, item):
    matches=[record for record in records if compatible(section,record,item)]
    # Missing dates/URL cannot choose between two different versions or employers.
    return matches[0] if len(matches)==1 else None

def merge_record(target, incoming):
    from profile_deletions import identity, legacy_identity
    aliases = set(target.get('_merged_identities', [])) | set(incoming.get('_merged_identities', []))
    if any(key in incoming for key in ('title','name','label','text')) and identity(target) != identity(incoming):
        aliases.update((identity(target), identity(incoming)))
    if any(key in incoming for key in ('title','name','label','text')) and legacy_identity(target) != legacy_identity(incoming):
        # Legacy exclusions may name either spelling of a consolidated record.
        aliases.update((legacy_identity(target), legacy_identity(incoming)))
    if aliases: target['_merged_identities']=sorted(aliases)
    for key, value in incoming.items():
        if key=='id': continue
        if isinstance(value, list):
            values=target.setdefault(key, [])
            for entry in value:
                textkey='text' if isinstance(entry,dict) and 'text' in entry else 'label' if isinstance(entry,dict) and 'label' in entry else None
                existing=next((old for old in values if normalized(old.get(textkey))==normalized(entry.get(textkey))),None) if textkey else None
                if existing is not None: merge_record(existing,entry)
                elif not any(normalized(old)==normalized(entry) if isinstance(entry,str) and isinstance(old,str) else old==entry for old in values): values.append(copy.deepcopy(entry))
        elif not target.get(key): target[key]=copy.deepcopy(value)
        elif key in ('description','role') and isinstance(value,str):
            paragraphs=target[key].split('\n\n')
            for paragraph in value.split('\n\n'):
                if normalized(paragraph) not in {normalized(p) for p in paragraphs}: paragraphs.append(paragraph)
            target[key]='\n\n'.join(paragraphs)

def consolidate(profile):
    result=copy.deepcopy(profile)
    for section in SECTIONS:
        records=[]
        for item in result.get(section,[]):
            if isinstance(item,dict):
                for key, values in list(item.items()):
                    if isinstance(values,list):
                        item[key]=[]; merge_record(item,{key:values})
            existing=find_record(records,section,item)
            if existing is None: records.append(item)
            elif isinstance(existing,dict): merge_record(existing,item)
        result[section]=records
    candidate=result.get('candidate',{})
    if isinstance(candidate.get('phones'),list):
        seen=set();candidate['phones']=[p for p in candidate['phones'] if not (phone(p) in seen or seen.add(phone(p)))]
    return result

def add_information(profile, section, record):
    signature=hashlib.sha256(json.dumps(record,sort_keys=True,ensure_ascii=False).encode()).hexdigest()
    ledger=profile.setdefault('_information_requests',{})
    previous=ledger.get(record['id'])
    if previous and previous!=signature: raise ValueError('Este registro ya fue guardado con otros datos.')
    same_id=next((r for r in profile[section] if r.get('id')==record['id']),None)
    if same_id and not previous and any(same_id.get(k)!=v for k,v in record.items()):
        raise ValueError('Este registro ya fue guardado con otros datos.')
    existing=find_record(profile[section],section,record)
    if existing is None:
        profile[section].append(copy.deepcopy(record));existing=profile[section][-1]
    else:
        merge_record(existing,record)
        # Legacy and document-derived references have no ID.
        if not existing.get('id'): existing['id'] = record['id']
    ledger[record['id']]=signature
    # Bound request metadata while retaining the most recent retries.
    while len(ledger)>1000: ledger.pop(next(iter(ledger)))
    from profile_deletions import identity
    # A later addition to an edited record must update its saved override too.
    for edit in profile.get('_manual_edits',[]):
        value=edit.get('value')
        if edit.get('section')==section and isinstance(value,dict) and (
            value.get('id')==existing.get('id') or identity(value)==identity(existing)):
            edit['value']=copy.deepcopy(existing)
    if '_deleted_records' in profile:
        from profile_deletions import matching_indices
        def restored(selector):
            if (not isinstance(selector,list) or len(selector)!=2 or selector[0]!=section
                    or not isinstance(selector[1],dict)):
                return False
            matches=matching_indices(profile[section],selector[1].get('identity'))
            return len(matches)==1 and profile[section][matches[0]] is existing
        profile['_deleted_records']=[item for item in profile['_deleted_records'] if not restored(item)]
    return existing['id']
