"""Shared, deterministic mail composition. No credentials or transport retries."""
from datetime import datetime, timezone
from email.message import EmailMessage
from email.policy import SMTP
from email.headerregistry import Address
from email.utils import format_datetime
from html import escape
import hashlib
import re
import time

GMAIL_SEND = 'https://www.googleapis.com/auth/gmail.send'
MAX_PDF = 15 * 1024 * 1024


def header(value):
    if not isinstance(value, str) or not value.strip() or any(ord(c) < 32 or ord(c) == 127 for c in value):
        raise ValueError('El encabezado del correo no es válido.')
    return value.strip()


def mailbox(value):
    value = header(value)
    if len(value) > 254 or not re.fullmatch(r'[^\s@<>,;"\\]+@[^\s@<>,;"\\]+\.[^\s@<>,;"\\]+', value):
        raise ValueError('El correo no es válido.')
    Address(addr_spec=value)
    return value


def default_text(position, name='', contact='', phone=''):
    return (f'Saludos:\n\nMe interesa postularme a la vacante de {position}.\n\n'
            'Adjunto mi currículum en PDF para su consideración. Quedo disponible para ampliar cualquier información.'
            f'\n\nAtentamente,\n{name}' + (f'\n{phone}' if phone else '') + (f'\n{mailbox(contact)}' if contact else ''))


def validate_pdf(content):
    import pymupdf as fitz
    if not isinstance(content, bytes) or not content.startswith(b'%PDF-') or len(content) > MAX_PDF:
        raise ValueError('El PDF no es válido o supera el límite de 15 MB.')
    try:
        with fitz.open(stream=content, filetype='pdf') as document:
            if document.needs_pass or not document.page_count:
                raise ValueError('PDF protegido o sin páginas.')
            for index in range(1, document.xref_length()):
                obj = document.xref_object(index)
                if re.search(r'/(JavaScript|JS|Launch|OpenAction|AA|EmbeddedFiles|RichMedia)\b', obj):
                    raise ValueError('PDF con contenido activo.')
            for page in document:
                if not page.get_text().strip() and not page.get_images() and not page.get_drawings():
                    raise ValueError('PDF con página vacía.')
                rendered = page.get_pixmap(matrix=fitz.Matrix(.2, .2), alpha=False)
                if not rendered.samples or min(rendered.samples) >= 250:
                    raise ValueError('PDF con página visualmente vacía.')
    except Exception as error:
        raise ValueError('No se pudo validar un PDF legible y sin contenido activo.') from error
    return hashlib.sha256(content).hexdigest()


def compose(sender, recipient, position, name, attempt, content, filename, text=None, subject=None):
    sender, recipient = mailbox(sender), mailbox(recipient)
    position = header(position)
    name = header(name) if name else ''
    if not re.fullmatch(r'[a-f0-9-]{36}', attempt):
        raise ValueError('Identificador de envío inválido.')
    digest = validate_pdf(content)
    message = EmailMessage(policy=SMTP.clone(max_line_length=998))
    message['From'] = Address(display_name=name, addr_spec=sender)
    message['To'] = recipient
    message['Subject'] = header(subject) if subject else f'Postulación a {position}' + (f' — {name}' if name else '')
    message['Date'] = format_datetime(datetime.now(timezone.utc))
    message['Message-ID'] = f'<{attempt}@cvalamedida.web.app>'
    text = text if text is not None else default_text(position, name, sender)
    if not isinstance(text, str) or not text.strip() or len(text) > 5000:
        raise ValueError('Revisa el mensaje antes de enviar.')
    message.set_content(text)
    message.add_alternative('<html><body>' + ''.join('<p>' + escape(p).replace('\n', '<br>') + '</p>' for p in text.split('\n\n')) + '</body></html>', subtype='html')
    message.add_attachment(content, maintype='application', subtype='pdf', filename=header(filename))
    if len(message.as_bytes()) > 25 * 1024 * 1024:
        raise ValueError('El mensaje MIME supera el límite efectivo de envío.')
    return message, digest


def require_scopes(scopes, require_read=False, require_send=True):
    scopes = set(scopes.split()) if isinstance(scopes, str) else set(scopes)
    drive = 'https://www.googleapis.com/auth/drive'
    needed = {'https://www.googleapis.com/auth/drive.file'}
    if require_read:
        needed.add('https://www.googleapis.com/auth/drive.readonly')
    if require_send and GMAIL_SEND not in scopes:
        raise ValueError('Falta Gmail autorizado para enviar. Vuelve a autorizar Google y concede Gmail.')
    if drive not in scopes and not needed.issubset(scopes):
        raise ValueError('Faltan permisos de Drive. Vuelve a autorizar Google.')


def reserve_rate(store, owner, recipient, attempt):
    """Conservative rolling limits; CAS never retries a provider operation."""
    from google.api_core.exceptions import PreconditionFailed
    key = 'mail-rate-' + hashlib.sha256(owner.encode()).hexdigest()
    state, generation = store.read(key)
    now = time.time()
    entries = [item for item in (state or {}).get('entries', []) if now - item['at'] < 86400]
    if any(item['attempt'] == attempt for item in entries):
        return
    target = hashlib.sha256(recipient.casefold().encode()).hexdigest()
    if len(entries) >= 20 or any(now - item['at'] < 30 or item['recipient'] == target and now - item['at'] < 300 for item in entries):
        raise ValueError('Límite temporal de envío: espera antes de otra postulación (30 segundos por cuenta, 5 minutos por destinatario, 20 al día).')
    entries.append(dict(at=now, recipient=target, attempt=attempt))
    try:
        store.write(key, {'entries': entries}, generation)
    except PreconditionFailed:
        raise ValueError('Otra postulación está reservando el cupo de esta cuenta. Espera antes de enviar.') from None
