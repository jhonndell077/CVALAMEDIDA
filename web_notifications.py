"""Private Web Push subscriptions and short-lived encrypted job credentials."""
import base64
import hashlib
import json
import os
import account_writes
from urllib.parse import urlparse
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from google.api_core.exceptions import PreconditionFailed

CONFIG_ID = 'web-notification-keys'


def configuration(store):
    config, generation = store.read(CONFIG_ID)
    if config:
        return config
    key = ec.generate_private_key(ec.SECP256R1())
    config = {
        'public_key': base64.urlsafe_b64encode(key.public_key().public_bytes(
            serialization.Encoding.X962, serialization.PublicFormat.UncompressedPoint)).decode().rstrip('='),
        'private_key': base64.urlsafe_b64encode(key.private_bytes(serialization.Encoding.DER,
            serialization.PrivateFormat.PKCS8, serialization.NoEncryption())).decode(),
        'credential_key': base64.b64encode(os.urandom(32)).decode(),
    }
    try:
        store.write(CONFIG_ID, config, generation)
    except PreconditionFailed:
        config, _ = store.read(CONFIG_ID)
    return config


def protect(store, headers, identifier):
    if not headers:
        return None
    nonce = os.urandom(12)
    key = base64.b64decode(configuration(store)['credential_key'])
    encrypted = AESGCM(key).encrypt(nonce, json.dumps(headers).encode(), identifier.encode())
    return base64.b64encode(nonce + encrypted).decode()


def unprotect(store, encrypted, identifier):
    if not encrypted:
        return {}
    data = base64.b64decode(encrypted)
    key = base64.b64decode(configuration(store)['credential_key'])
    return json.loads(AESGCM(key).decrypt(data[:12], data[12:], identifier.encode()))


def valid_subscription(subscription):
    if not isinstance(subscription, dict):
        return False
    endpoint = subscription.get('endpoint', '')
    if not isinstance(endpoint, str) or len(endpoint) > 2048:
        return False
    url = urlparse(endpoint)
    allowed = ('fcm.googleapis.com', 'push.services.mozilla.com', 'web.push.apple.com', 'notify.windows.com')
    host = url.hostname or ''
    keys = subscription.get('keys')
    return (url.scheme == 'https' and url.port in {None, 443} and not url.username
            and any(host == suffix or host.endswith('.' + suffix) for suffix in allowed)
            and isinstance(keys, dict) and all(isinstance(keys.get(k), str) and
                10 <= len(keys[k]) <= 200 for k in ('p256dh', 'auth')))


def subscription_key(uid=''):
    return 'web-notification-subscriptions' + ('-' + hashlib.sha256(uid.encode()).hexdigest() if uid else '')

def subscribe(store, subscription, uid=''):
    record, generation = store.read(subscription_key(uid))
    subscriptions = (record or {}).get('subscriptions', {})
    key = hashlib.sha256(subscription['endpoint'].encode()).hexdigest()
    subscriptions[key] = subscription
    store.write(subscription_key(uid), {'subscriptions': dict(list(subscriptions.items())[-10:])}, generation)


def notify(store, identifier, job):
    # Only confirmed successful completion produces a push notification.
    # Failed or partial work remains visible in the application's process panel.
    if job.get('state') != 'done' or job.get('progress') != 100:
        return
    record, _ = store.read(subscription_key(job.get('owner_uid', '')))
    subscriptions = (record or {}).get('subscriptions', {})
    if not subscriptions:
        return
    from pywebpush import webpush, WebPushException
    config = configuration(store)
    data = json.dumps({'title': 'CV a la medida', 'body':
        'Tu proceso llegó al 100%. Abre la app para ver el resultado.',
        'job_id': identifier, 'state': 'done', 'progress': 100})
    expired = []
    for key, subscription in subscriptions.items():
        try:
            with account_writes.effect(store, job.get('owner_uid')):
                webpush(subscription_info=subscription, data=data, vapid_private_key=config['private_key'],
                        vapid_claims={'sub': 'mailto:jhonndell077@gmail.com'}, timeout=10, ttl=86400)
        except WebPushException as error:
            if error.response is not None and error.response.status_code in {404, 410}:
                expired.append(key)
        except Exception:
            continue  # Notifications must not invalidate a completed result.
    if expired:
        current, generation = store.read(subscription_key(job.get('owner_uid', '')))
        for key in expired:
            current.get('subscriptions', {}).pop(key, None)
        store.write(subscription_key(job.get('owner_uid', '')), current, generation)
