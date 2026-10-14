"""Persistent exclusions applied after merging document evidence."""
import copy
import hashlib
import json

SECTIONS = {'experiences', 'skills', 'education', 'courses', 'projects', 'references', 'not_documented'}
PERSONAL = {'name', 'national_id', 'address', 'residence', 'email'}


def identity(value):
    if isinstance(value, dict):
        keys = ('title', 'employer') if 'employer' in value else ('title', 'institution') if 'institution' in value else ('title',) if 'title' in value else ('label',) if 'label' in value else ('text',) if 'text' in value else ('name', 'phone')
        value = {key: value.get(key, '') for key in keys}
    raw = json.dumps(value, ensure_ascii=False, sort_keys=True).casefold()
    return hashlib.sha256(raw.encode()).hexdigest()


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


def apply_deletions(profile):
    result = copy.deepcopy(profile)
    def remove(node, path):
        part = path[0]
        if isinstance(part, dict) and isinstance(node, list):
            for index in range(len(node) - 1, -1, -1):
                aliases = node[index].get('_merged_identities', []) if isinstance(node[index], dict) else []
                if identity(node[index]) == part.get('identity') or part.get('identity') in aliases:
                    if len(path) == 1:
                        node.pop(index)
                    else:
                        remove(node[index], path[1:])
        elif isinstance(part, str) and isinstance(node, dict) and part in node:
            if len(path) == 1:
                node[part] = ''
            else:
                remove(node[part], path[1:])
    for selector in result.get('_deleted_records', []):
        if isinstance(selector, list) and selector:
            remove(result, selector)
    return result
