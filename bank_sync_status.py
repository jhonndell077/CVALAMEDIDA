"""Explicit bank completeness; document text never becomes diagnostic evidence."""
BLOCKING_CODES = frozenset({'bank_identity_conflict', 'bank_identity_unverified', 'bank_document_unreadable', 'bank_review_required'})
NOTICE_CODES = frozenset({'bank_date_preserved', 'bank_document_note'})
EVENT_CODES = BLOCKING_CODES | NOTICE_CODES | frozenset({'bank_sync_pending', 'bank_sync_notice'})


def summarize(status):
    warnings = status.get('warnings') or []
    blockers, notices = [], []
    for warning in warnings:
        code = warning.get('code') if isinstance(warning, dict) else None
        if code in NOTICE_CODES and warning.get('severity') == 'notice':
            notices.append(code)
        else:
            # Untyped historical warnings remain reviewable, never guessed from text.
            blockers.append(code if code in BLOCKING_CODES else 'bank_review_required')
    for document in status.get('documents') or []:
        if document.get('active') is not False and document.get('status') == 'revision':
            if not any(isinstance(w, dict) and w.get('file_id') == document.get('file_id') for w in warnings):
                blockers.append('bank_document_unreadable')
    pending = status.get('pending') or 0
    return dict(state='pending' if pending else 'blocked' if blockers else 'ready',
                pending=pending, blockingCount=len(blockers), noticeCount=len(notices),
                reasons=sorted(set(blockers + notices)))


def with_summary(status):
    return {**status, 'sync': summarize(status)}


def event(status):
    summary = summarize(status)
    if summary['blockingCount']:
        return 'warning', 'bank_review_required'
    if summary['pending']:
        return None
    return 'success', 'bank_sync_notice' if summary['noticeCount'] else None
