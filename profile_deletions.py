"""Persistent exclusions applied after merging document evidence."""
import copy
import hashlib
import json

SECTIONS = {'experiences', 'skills', 'education', 'courses', 'projects', 'references', 'not_documented'}
PERSONAL = {'name', 'national_id', 'address', 'residence', 'email'}


def legacy_identity(value):
    """Read old persisted selectors without changing their historical meaning."""
    if isinstance(value, dict):
        keys = ('title', 'employer') if 'employer' in value else ('title', 'institution') if 'institution' in value else ('title',) if 'title' in value else ('label',) if 'label' in value else ('text',) if 'text' in value else ('name', 'phone')
        value = {key: value.get(key, '') for key in keys}
    raw = json.dumps(value, ensure_ascii=False, sort_keys=True).casefold()
    return hashlib.sha256(raw.encode()).hexdigest()


def identity(value):
    """Semantic identity survives regenerated IDs and distinguishes real records."""
    from profile_records import normalized, phone, url
    if isinstance(value, dict):
        if 'employer' in value:
            keys = ('title', 'employer', 'start_date', 'end_date')
        elif 'institution' in value:
            keys = ('title', 'institution', 'date')
        elif 'title' in value:
            keys = ('title', 'url')
        elif 'label' in value:
            keys = ('label',)
        elif 'text' in value:
            keys = ('text',)
        else:
            keys = ('name', 'phone')
        value = {key: url(value.get(key)) if key == 'url' else phone(value.get(key)) if key == 'phone'
                 else normalized(value.get(key)) for key in keys}
    elif isinstance(value, str):
        value = normalized(value)
    raw = json.dumps(value, ensure_ascii=False, sort_keys=True)
    return 'v2:' + hashlib.sha256(raw.encode()).hexdigest()


def matching_indices(records, token, previous=None):
    """Legacy selectors only apply when exactly one record can be identified."""
    if not isinstance(token, str):
        return []
    matches = [index for index, record in enumerate(records)
               if identity(record) == token or not token.startswith('v2:') and legacy_identity(record) == token
               or isinstance(record, dict) and token in record.get('_merged_identities', [])]
    if previous is not None and not token.startswith('v2:'):
        # Old edits contain the complete old value, unlike old deletion markers.
        precise = [index for index in matches if identity(records[index]) == identity(previous)]
        if precise:
            matches = precise
    return matches


def ambiguity_warning(warnings, section, action):
    if warnings is not None:
        warning = {'file_id': '', 'name': 'Banco de datos', 'section': section,
                   'message': f'Hay una {action} guardada con identidad ambigua. '
                   'Se conservaron los registros; revisa las ediciones y exclusiones del banco antes de generar un CV.'}
        if warning not in warnings:
            warnings.append(warning)


def deletion_for(profile, path, expected):
    if not isinstance(path, list) or not path:
        raise ValueError('Selecciona un registro válido.')
    if any(type(part) not in (str, int) for part in path):
        raise ValueError('Selecciona un registro válido.')
    section = path[0]
    valid = (len(path) == 2 and section in SECTIONS and type(path[1]) is int
             or len(path) == 2 and section == 'candidate' and path[1] in PERSONAL
             or len(path) == 3 and path[:2] == ['candidate', 'phones'] and type(path[2]) is int
             or len(path) == 4 and section == 'experiences' and type(path[1]) is int and path[2] == 'responsibilities' and type(path[3]) is int)
    if not valid:
        raise ValueError('No se puede eliminar ese campo individualmente. Elimina el registro completo.')
    current = profile
    selector = []
    try:
        for part in path:
            if type(part) is int:
                if part < 0:
                    raise IndexError()
                current = current[part]
                selector.append({'identity': identity(current)})
            else:
                current = current[part]
                selector.append(part)
    except (KeyError, IndexError, TypeError):
        raise ValueError('El banco cambió. Recarga los datos e inténtalo de nuevo.')
    if current != expected:
        raise ValueError('El banco cambió. Recarga los datos e inténtalo de nuevo.')
    return selector


def apply_deletions(profile, warnings=None):
    result = copy.deepcopy(profile)
    def remove(node, path, section):
        part = path[0]
        if isinstance(part, dict) and isinstance(node, list):
            matches = matching_indices(node, part.get('identity'))
            if len(matches) > 1:
                ambiguity_warning(warnings, section, 'exclusión')
            elif len(matches) == 1:
                index = matches[0]
                if len(path) == 1:
                    node.pop(index)
                else:
                    remove(node[index], path[1:], section)
        elif isinstance(part, str) and isinstance(node, dict) and part in node:
            if len(path) == 1:
                node[part] = ''
            else:
                remove(node[part], path[1:], section)
    for selector in result.get('_deleted_records', []):
        if isinstance(selector, list) and selector:
            remove(result, selector, selector[0])
    return result
