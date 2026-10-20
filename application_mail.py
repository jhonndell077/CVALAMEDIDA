"""Shared, side-effect-free PDF and MIME boundary for web and Telegram."""
import base64
import hashlib
import html
import re
import time
import unicodedata
from email.message import EmailMessage
from email.headerregistry import Address
from email.policy import SMTP
from email.utils import format_datetime
from datetime import datetime, timezone

GMAIL_SCOPE = 'https://www.googleapis.com/auth/gmail.send'
MAX_PDF_BYTES = 15 * 1024 * 1024
MAX_MIME_BYTES = 24 * 1024 * 1024


def require_scope(scopes):
    if GMAIL_SCOPE not in set(str(scopes or '').split()):
        raise ValueError('Falta autorizar el permiso de envío de Gmail. Vuelve a conectar Google.')


def verify_grant(token):
    """Check actual grant without putting credentials in a URL or logs."""
    import requests
    try:
        response = requests.post('https://oauth2.googleapis.com/tokeninfo',
            headers={'Authorization': 'Bearer ' + token, 'Content-Type': 'application/x-www-form-urlencoded'}, timeout=25)
        if not response.ok:
            raise ValueError('No se pudo comprobar el permiso de Gmail. Vuelve a autorizar Google.')
        require_scope(response.json().get('scope'))
    except ValueError:
        raise
    except Exception:
        raise ValueError('No se pudo comprobar el permiso de Gmail; no se inició el envío.') from None


def reserve_rate(store, owner, recipient, position, now=None):
    """CAS rate reservation shared by both channels; collisions fail closed."""
    now = time.time() if now is None else now
    owner_key = hashlib.sha256(owner.casefold().encode()).hexdigest()
    key = 'mail-rate-' + owner_key
    record, version = store.read(key)
    events = [event for event in (record or {}).get('events', []) if event['at'] > now - 3600]
    target = hashlib.sha256((recipient.casefold() + ':' + position.casefold()).encode()).hexdigest()
    if len(events) >= 20 or any(event['target'] == target for event in events):
        raise ValueError('Límite preventivo: espera antes de volver a postular al mismo correo y puesto (una hora), o de superar 20 envíos por hora.')
    if events and max(event['at'] for event in events) > now - 10:
        raise ValueError('Espera diez segundos entre postulaciones para evitar ráfagas.')
    events.append({'at': now, 'target': target})
    try:
        store.write(key, {'events': events}, version)
    except Exception:
        raise ValueError('Hay otra postulación en proceso; no se inició este envío.') from None


def header(value, limit=254):
    if not isinstance(value, str) or not value.strip() or len(value) > limit or any(ord(c) < 32 or ord(c) == 127 for c in value):
        raise ValueError('Encabezado de correo inválido.')
    return value.strip()


def email(value):
    value = header(value)
    if not re.fullmatch(r'[^\s@<>;,]+@[^\s@<>;,]+\.[^\s@<>;,]+', value):
        raise ValueError('Correo de postulación inválido.')
    Address(addr_spec=value)
    return value


def contacts(values):
    result, seen = [], set()
    for value in values:
        try:
            address = email(value.strip())
        except (ValueError, AttributeError):
            continue
        if address.casefold() not in seen:
            result.append(address)
            seen.add(address.casefold())
    return result[:4]


def filename(name, position):
    value = unicodedata.normalize('NFKD', name + '_' + position).encode('ascii', 'ignore').decode()
    return re.sub(r'[^A-Za-z0-9_-]+', '_', value).strip('_')[:160] + '.pdf'


def default_text(position, name):
    return (f'Saludos:\n\nMe interesa postularme a la vacante de {position}. '
            'Adjunto mi currículum en PDF para su consideración. Quedo disponible para ampliar cualquier información.\n\n'
            f'Atentamente,\n{name}')


def validate_pdf(content):
    import fitz
    if not isinstance(content, bytes) or not content.startswith(b'%PDF-') or len(content) > MAX_PDF_BYTES:
        raise ValueError('El archivo debe ser un PDF válido de hasta 15 MiB.')
    try:
        with fitz.open(stream=content, filetype='pdf') as doc:
            if doc.needs_pass or not doc.page_count or doc.is_repaired:
                raise ValueError('El PDF está protegido, vacío o dañado.')
            for page in doc:
                if not page.get_text().strip():
                    raise ValueError('El PDF contiene una página sin texto legible.')
                # Render every page; extraction alone does not validate rendering.
                page.get_pixmap(matrix=fitz.Matrix(.2, .2))
            for xref in range(1, doc.xref_length()):
                for key in ('JS', 'JavaScript', 'OpenAction', 'AA', 'EmbeddedFiles'):
                    if doc.xref_get_key(xref, key)[0] != 'null':
                        raise ValueError('El PDF contiene acciones o contenido activo.')
                if doc.xref_get_key(xref, 'S')[1] in ('/JavaScript', '/Launch'):
                    raise ValueError('El PDF contiene acciones activas.')
    except ValueError:
        raise
    except Exception:
        raise ValueError('No se pudo comprobar el PDF.') from None
    return hashlib.sha256(content).hexdigest()


def compose(sender, recipient, name, position, application_id, pdf, text=None):
    sender, recipient = email(sender), email(recipient)
    name, position = header(name, 200), header(position, 200)
    if not re.fullmatch(r'[a-f0-9-]{36}', application_id):
        raise ValueError('Identificador de postulación inválido.')
    digest = validate_pdf(pdf)
    text = text if text is not None else default_text(position, name)
    if not isinstance(text, str) or not text.strip() or len(text) > 5000 or '\x00' in text:
        raise ValueError('Mensaje de postulación inválido.')
    subject = f'Postulación a {position} — {name}'
    mail = EmailMessage(policy=SMTP.clone(max_line_length=998))
    mail['From'] = Address(display_name=name, addr_spec=sender)
    mail['To'] = recipient
    mail['Subject'] = subject
    mail['Date'] = format_datetime(datetime.now(timezone.utc))
    mail['Message-ID'] = f'<{application_id}@cvalamedida.web.app>'
    mail.set_content(text)
    mail.add_alternative('<html><body><p>' + html.escape(text).replace('\n', '<br>') + '</p></body></html>', subtype='html')
    name_pdf = filename(name, position)
    mail.add_attachment(pdf, maintype='application', subtype='pdf', filename=name_pdf)
    raw = mail.as_bytes()
    if len(raw) > MAX_MIME_BYTES:
        raise ValueError('El correo supera el tamaño MIME permitido por la aplicación.')
    return {'raw': base64.urlsafe_b64encode(raw).decode('ascii')}, {
        'pdf_sha256': digest, 'pdf_size': len(pdf), 'filename': name_pdf,
        'subject': subject, 'rfc_message_id': f'{application_id}@cvalamedida.web.app'}
