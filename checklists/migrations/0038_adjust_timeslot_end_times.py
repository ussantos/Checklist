from datetime import date, datetime, timedelta

from django.db import migrations


def adjust_timeslot_end_times(apps, schema_editor):
    TimeSlot = apps.get_model('checklists', 'TimeSlot')

    TimeSlot.objects.filter(active=False).delete()

    for slot in TimeSlot.objects.filter(active=True).order_by('weekday', 'start_time', 'end_time', 'id'):
        end_time = slot.end_time
        if not end_time or end_time.minute != 0 or end_time.second != 0 or end_time.microsecond != 0:
            continue

        target_end_time = (
            datetime.combine(date(2000, 1, 1), end_time) - timedelta(minutes=1)
        ).time()
        duplicate = TimeSlot.objects.filter(
            weekday=slot.weekday,
            start_time=slot.start_time,
            end_time=target_end_time,
        ).exclude(pk=slot.pk).first()
        if duplicate:
            slot.delete()
            continue

        slot.end_time = target_end_time
        slot.save(update_fields=['end_time', 'updated_at'])


class Migration(migrations.Migration):

    dependencies = [
        ('checklists', '0037_commercialopportunity_automation_key'),
    ]

    operations = [
        migrations.RunPython(adjust_timeslot_end_times, migrations.RunPython.noop),
    ]
