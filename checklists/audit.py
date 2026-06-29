from datetime import date, datetime, time
from decimal import Decimal

from django.db import models

from .models import ActivityLog


SENSITIVE_FIELD_NAMES = {
    'password',
    'senha',
    'temporary_password',
    'generated_password',
    'token',
    'secret',
    'evidence_text',
    'file',
}


def safe_value(value):
    if value is None or isinstance(value, (bool, int, float, str)):
        return value
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, (date, time)):
        return value.isoformat()
    if isinstance(value, models.Model):
        return {'id': value.pk, 'label': str(value)}
    return str(value)


def snapshot_instance(instance, fields):
    data = {}
    for field_name in fields:
        if field_name in SENSITIVE_FIELD_NAMES:
            continue
        value = getattr(instance, field_name, None)
        data[field_name] = safe_value(value)
    return data


def changed_values(previous, current):
    previous_changes = {}
    current_changes = {}
    for key in sorted(set(previous) | set(current)):
        if previous.get(key) != current.get(key):
            previous_changes[key] = previous.get(key)
            current_changes[key] = current.get(key)
    return previous_changes, current_changes


def log_activity(
    *,
    actor,
    action,
    obj=None,
    position=None,
    object_type='',
    object_id='',
    object_label='',
    details='',
    previous_values=None,
    new_values=None,
):
    if obj is not None:
        object_type = object_type or obj.__class__.__name__
        object_id = object_id or str(obj.pk)
        object_label = object_label or str(obj)
        if position is None and hasattr(obj, 'position'):
            position = obj.position

    return ActivityLog.objects.create(
        actor=actor,
        position=position,
        action=action,
        object_type=object_type,
        object_id=str(object_id or ''),
        object_label=object_label[:300] if object_label else '',
        details=details,
        previous_values=previous_values or {},
        new_values=new_values or {},
    )
