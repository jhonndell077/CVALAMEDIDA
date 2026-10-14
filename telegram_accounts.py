"""Account-owned Telegram bindings, expiring pairing links and encrypted OAuth."""
import hashlib
import re
import secrets
import time
import user_accounts as users
import web_notifications as encrypted

def key(kind, value):
    return 'telegram-' + kind + '-' + hashlib.sha256(str(value).encode()).hexdigest()

def binding(store, telegram_id):
    mapped, _ = store.read(key('chat', telegram_id))
    if not mapped: return None
    account, _ = store.read(key('account', mapped['uid']))
    if account and account.get('telegram_id') == telegram_id and account.get('binding_id') == mapped.get('binding_id'):
        return account
    return None

def account_binding(store, uid):
    account, _ = store.read(key('account', uid))
    return binding(store, account['telegram_id']) if account and account.get('telegram_id') else None

def legacy(core, config, identity, store):
    if identity['email'].casefold() != core.ORIGINAL_OWNER_EMAIL or not config.get('owner_id'):
        return
    if account_binding(store, identity['uid']): return
    existing = binding(store, config['owner_id'])
    if existing and existing['uid'] != identity['uid']: return
    account, generation = store.read(key('account', identity['uid']))
    if account and account.get('revoked'): return
    linked = {**identity, 'telegram_id':config['owner_id'], 'binding_id':'legacy-' + users.account_key(identity['uid'])}
    mapped, version = store.read(key('chat', config['owner_id']))
    store.write(key('chat', config['owner_id']), linked, version)
    store.write(key('account', identity['uid']), linked, generation)

def create_link(core, identity, store):
    if account_binding(store, identity['uid']): raise core.AppError('Telegram ya está vinculado a esta cuenta.',409)
    token = secrets.token_urlsafe(32)
    record = {**{field:identity.get(field,'') for field in ('uid','email','name')}, 'expires_at':time.time()+600}
    store.write(key('pair',token),record,0)
    prior, generation=store.read(key('pending',identity['uid']))
    store.write(key('pending',identity['uid']), {'pair_key':key('pair',token)},generation)
    return token

def stage_link(core, token, message, store):
    if not re.fullmatch(r'[A-Za-z0-9_-]{43}', token): raise core.AppError('El enlace de vinculación no es válido.',400)
    identifier=key('pair',token)
    pair, generation=store.read(identifier)
    pending, _=store.read(key('pending',(pair or {}).get('uid','')))
    if not pair or pair.get('used') or pair['expires_at'] < time.time() or (pending or {}).get('pair_key') != identifier:
        raise core.AppError('El enlace venció. Genera otro desde la app.',410)
    sender=message['from']; telegram_id=sender['id']
    linked=binding(store,telegram_id)
    if linked and linked['uid'] != pair['uid']: raise core.AppError('Este Telegram ya está vinculado a otra cuenta. Desvincúlalo desde esa cuenta.',409)
    if pair.get('telegram_id') and pair['telegram_id'] != telegram_id:
        raise core.AppError('Este enlace ya está pendiente de confirmación. Genera otro desde la app.',409)
    pair.update(telegram_id=telegram_id, telegram_name=(sender.get('first_name','')+' '+sender.get('last_name','')).strip()[:160],
                telegram_username=sender.get('username','')[:64])
    store.write(identifier,pair,generation)

def pending_link(store, uid):
    pointer,_=store.read(key('pending',uid))
    pair,_=store.read((pointer or {}).get('pair_key','telegram-no-pair'))
    if pair and not pair.get('used') and pair['expires_at']>time.time() and pair.get('uid')==uid:
        return pair
    return None

def confirm_link(core, identity, store):
    pointer,_=store.read(key('pending',identity['uid']))
    identifier=(pointer or {}).get('pair_key','telegram-no-pair')
    pair,version=store.read(identifier)
    if not pair or pair.get('uid')!=identity['uid'] or pair.get('used') or pair['expires_at']<time.time() or not pair.get('telegram_id'):
        raise core.AppError('Abre el enlace en Telegram y pulsa Iniciar antes de confirmar.',409)
    existing=account_binding(store,identity['uid']); mapped=binding(store,pair['telegram_id'])
    if (existing and existing['telegram_id']!=pair['telegram_id']) or (mapped and mapped['uid']!=identity['uid']):
        raise core.AppError('Una de las cuentas ya tiene otra vinculación. Desvincúlala primero.',409)
    linked={**{field:identity.get(field,'') for field in ('uid','email','name')},
            **{field:pair.get(field,'') for field in ('telegram_id','telegram_name','telegram_username')}, 'binding_id':identifier}
    old,chat_version=store.read(key('chat',pair['telegram_id']))
    old,account_version=store.read(key('account',identity['uid']))
    store.write(key('chat',pair['telegram_id']),linked,chat_version)
    store.write(key('account',identity['uid']),linked,account_version)
    pair['used']=True
    store.write(identifier,pair,version)
    return linked

def disconnect(store, uid):
    account,generation=store.read(key('account',uid))
    store.write(key('account',uid),{'uid':uid,'revoked':True},generation)
    auth,version=store.read(key('oauth',uid))
    store.write(key('oauth',uid),{'revoked':True},version)
    pending,version=store.read(key('pending',uid))
    store.write(key('pending',uid),{},version)

def save_oauth(store, uid, refresh, connected=False):
    identifier=key('oauth',uid)
    old,generation=store.read(identifier)
    record={'credentials':encrypted.protect(store,{'refresh_token':refresh},identifier),'drive_connected':connected}
    store.write(identifier,record,generation)

def runtime(core, config, identity, store):
    result={**config}
    # Shared legacy credentials must never become another account's credentials.
    result.pop('drive_refresh_token',None); result['drive_connected']=False
    uid=identity['uid']; saved,_=store.read(key('oauth',uid))
    if saved and saved.get('credentials'):
        result['drive_refresh_token']=encrypted.unprotect(store,saved['credentials'],key('oauth',uid))['refresh_token']
        result['drive_connected']=bool(saved.get('drive_connected'))
    elif not saved and identity['email'].casefold()==core.ORIGINAL_OWNER_EMAIL:
        result['drive_refresh_token']=config.get('drive_refresh_token','')
        result['drive_connected']=bool(config.get('drive_connected'))
    linked=account_binding(store,uid)
    result.update(owner_id=(linked or {}).get('telegram_id',0),owner_uid=uid,owner_email=identity['email'],owner_name=identity.get('name',''),binding_id=(linked or {}).get('binding_id',''))
    return result


def disconnect_callback(linked):
    return 'unlink:' + hashlib.sha256(linked['binding_id'].encode()).hexdigest()[:24]


def disconnect_chat(core, store, telegram_id, callback):
    linked = binding(store, telegram_id)
    if not linked or callback != disconnect_callback(linked):
        raise core.AppError('Esta vinculación ya no está activa. Usa /start para revisar tu cuenta.', 409)
    disconnect(store, linked['uid'])
    return linked.get('email', '')
