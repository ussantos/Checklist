from datetime import date, time

from django.core.exceptions import ValidationError
from django.test import TestCase

from .models import Course, Lesson, PedagogicalStudent, Room, SchoolHoliday, TimeSlot


class PedagogicalSchedulingRulesTests(TestCase):
    def setUp(self):
        self.day = date(2026, 7, 7)
        self.start = time(14, 0)
        self.end = time(16, 0)
        self.course = Course.objects.create(name='Techbot', value='500.00', kit_quantity=1, active=True)
        self.room = Room.objects.create(name='Sala Maker', capacity=2, active=True)
        self.student = PedagogicalStudent.objects.create(name='Aluno Um', responsible_name='Responsável Um', whatsapp='21999990001')
        self.other_student = PedagogicalStudent.objects.create(name='Aluno Dois', responsible_name='Responsável Dois', whatsapp='21999990002')

    def _lesson(self, **kwargs):
        data = {
            'lesson_type': Lesson.TYPE_REGULAR,
            'student': self.student,
            'course': self.course,
            'room': self.room,
            'date': self.day,
            'start_time': self.start,
            'end_time': self.end,
            'status': Lesson.STATUS_SCHEDULED,
        }
        data.update(kwargs)
        return Lesson(**data)

    def test_blocks_when_course_kits_are_exhausted(self):
        self._lesson().save()
        lesson = self._lesson(student=self.other_student)
        with self.assertRaises(ValidationError) as ctx:
            lesson.save()
        self.assertIn('course', ctx.exception.message_dict)

    def test_trial_lessons_count_for_course_kits(self):
        self._lesson(
            lesson_type=Lesson.TYPE_TRIAL,
            student=None,
            student_name_snapshot='Interessado Teste',
        ).save()
        lesson = self._lesson(student=self.other_student)
        with self.assertRaises(ValidationError) as ctx:
            lesson.save()
        self.assertIn('course', ctx.exception.message_dict)

    def test_blocks_when_room_capacity_is_full(self):
        self.course.kit_quantity = 5
        self.course.save(update_fields=['kit_quantity'])
        self.room.capacity = 1
        self.room.save(update_fields=['capacity'])
        self._lesson().save()
        lesson = self._lesson(student=self.other_student)
        with self.assertRaises(ValidationError) as ctx:
            lesson.save()
        self.assertIn('room', ctx.exception.message_dict)

    def test_warns_when_slot_has_three_or_more_lessons(self):
        self.course.kit_quantity = 5
        self.course.save(update_fields=['kit_quantity'])
        self.room.capacity = 5
        self.room.save(update_fields=['capacity'])
        third_student = PedagogicalStudent.objects.create(name='Aluno Três')
        self._lesson().save()
        self._lesson(student=self.other_student).save()
        lesson = self._lesson(student=third_student)
        self.assertIn('Atenção', lesson.assistant_warning_message())

    def test_blocks_holiday_or_recess_dates(self):
        SchoolHoliday.objects.create(
            start_date=self.day,
            end_date=self.day,
            kind=SchoolHoliday.KIND_RECESS,
            description='Recesso teste',
            active=True,
        )
        lesson = self._lesson()
        with self.assertRaises(ValidationError) as ctx:
            lesson.save()
        self.assertIn('date', ctx.exception.message_dict)

    def test_blocks_same_student_in_same_slot(self):
        self.course.kit_quantity = 5
        self.course.save(update_fields=['kit_quantity'])
        self.room.capacity = 5
        self.room.save(update_fields=['capacity'])
        self._lesson().save()
        lesson = self._lesson(room=Room.objects.create(name='Sala 2', capacity=5, active=True))
        with self.assertRaises(ValidationError) as ctx:
            lesson.save()
        self.assertIn('student', ctx.exception.message_dict)

    def test_blocks_lessons_longer_than_two_hours(self):
        lesson = self._lesson(end_time=time(16, 30))
        with self.assertRaises(ValidationError) as ctx:
            lesson.save()
        self.assertIn('end_time', ctx.exception.message_dict)

    def test_blocks_lesson_ending_during_lunch(self):
        lesson = self._lesson(start_time=time(10, 30), end_time=time(12, 30))
        with self.assertRaises(ValidationError) as ctx:
            lesson.save()
        self.assertIn('end_time', ctx.exception.message_dict)

    def test_blocks_time_slot_ending_during_lunch(self):
        slot = TimeSlot(weekday=0, start_time=time(10, 30), end_time=time(12, 30), active=True)
        with self.assertRaises(ValidationError) as ctx:
            slot.save()
        self.assertIn('end_time', ctx.exception.message_dict)
