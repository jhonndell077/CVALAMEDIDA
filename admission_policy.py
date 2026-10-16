"""Pure UTC work quotas; persistence and generation checks belong to JobStore."""
from __future__ import annotations

import copy
import hashlib
import math
import os
from datetime import datetime, timedelta, timezone


class QuotaExceeded(Exception):
    def __init__(self, period, retry_after):
        self.period = period
        self.retry_after = retry_after


def limits():
    values = []
    for key, default in (('CV_DAILY_JOB_LIMIT', '10'), ('CV_MONTHLY_JOB_LIMIT', '50')):
        value = os.environ.get(key, default)
        if not value.isascii() or not value.isdecimal() or not 0 <= int(value) <= 10000:
            raise ValueError('La política de admisión no tiene límites válidos.')
        values.append(int(value))
    return values


def reserve(queue, identifier, timestamp):
    """Return new usage, or None for an already counted identifier this month."""
    now = datetime.fromtimestamp(timestamp, timezone.utc)
    day, month = now.strftime('%Y-%m-%d'), now.strftime('%Y-%m')
    usage = copy.deepcopy(queue.get('usage', {}))
    if usage.get('month') != month:
        usage = {'month': month, 'monthly': 0, 'receipts': {}}
    if usage.get('day') != day:
        usage.update(day=day, daily=0)
    receipt = hashlib.sha256(identifier.encode()).hexdigest()
    if receipt in usage.get('receipts', {}):
        return None
    daily, monthly = limits()
    tomorrow = (now + timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0)
    next_month = now.replace(year=now.year + (now.month == 12), month=now.month % 12 + 1,
                             day=1, hour=0, minute=0, second=0, microsecond=0)
    for period, used, maximum, reset in (
            ('month', usage.get('monthly', 0), monthly, next_month),
            ('day', usage.get('daily', 0), daily, tomorrow)):
        if used >= maximum:
            raise QuotaExceeded(period, max(1, math.ceil(reset.timestamp() - timestamp)))
    usage['daily'] = usage.get('daily', 0) + 1
    usage['monthly'] = usage.get('monthly', 0) + 1
    usage.setdefault('receipts', {})[receipt] = timestamp
    return usage
