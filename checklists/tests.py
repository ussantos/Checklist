from decimal import Decimal
from datetime import date, time

from django.core.exceptions import ValidationError
from django.test import TestCase

from .forms import CommercialOpportunityForm
from .models import (
    CommercialFunnel, CommercialOpportunity, Course, FunnelModel, FunnelStage,
    FunnelType, Lesson, OpportunityOrigin, PedagogicalStudent, Room,
    SchoolHoliday, TimeSlot,
)
from .sponte import (
    import_sponte_free_class_records, import_sponte_student_records,
    parse_sponte_free_class_schedule, parse_sponte_students,
    sync_sponte_free_class_schedule,
)


class PedagogicalSchedulingRulesTests(TestCase):
    def setUp(self):
        self.day = date(2026, 7, 7)
        self.start = time(14, 0)
        self.end = time(16, 0)
        self.course = Course.objects.create(name='Techbot', value='500.00', kit_quantity=1, active=True)
        self.room = Room.objects.create(name='Sala Maker', capacity=2, active=True)
        self.student = PedagogicalStudent.objects.create(name='Aluno Um', responsible_name='Responsável Um', whatsapp='21999990001')
        self.other_student = PedagogicalStudent.objects.create(name='Aluno Dois', responsible_name='Responsável Dois', whatsapp='21999990002')
        self.funnel_model = FunnelModel.objects.create(name='Modelo teste', active=True)
        self.funnel = CommercialFunnel.objects.create(name='Funil teste', funnel_model=self.funnel_model, active=True)
        self.opportunity = CommercialOpportunity.objects.create(
            title='Interessado Teste',
            commercial_funnel=self.funnel,
            contact_name='Responsável Teste',
            contact_phone='21999990003',
            next_follow_up_date=self.day,
            active=True,
        )

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
            trial_kind=Lesson.TRIAL_KIND_EXPERIMENTAL,
            commercial_opportunity=self.opportunity,
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

    def test_trial_or_play_lesson_requires_kind_and_opportunity(self):
        lesson = self._lesson(
            lesson_type=Lesson.TYPE_TRIAL,
            student=None,
            student_name_snapshot='Interessado sem vínculo',
        )
        with self.assertRaises(ValidationError) as ctx:
            lesson.save()
        self.assertIn('trial_kind', ctx.exception.message_dict)
        self.assertIn('commercial_opportunity', ctx.exception.message_dict)

    def test_opportunity_can_have_multiple_trial_or_play_lessons(self):
        self.course.kit_quantity = 5
        self.course.save(update_fields=['kit_quantity'])
        self.room.capacity = 5
        self.room.save(update_fields=['capacity'])

        self._lesson(
            lesson_type=Lesson.TYPE_TRIAL,
            trial_kind=Lesson.TRIAL_KIND_EXPERIMENTAL,
            commercial_opportunity=self.opportunity,
            student=None,
            student_name_snapshot='Interessado Teste',
        ).save()
        self._lesson(
            lesson_type=Lesson.TYPE_TRIAL,
            trial_kind=Lesson.TRIAL_KIND_PLAY,
            commercial_opportunity=self.opportunity,
            student=None,
            student_name_snapshot='Interessado Teste',
            start_time=time(16, 0),
            end_time=time(17, 0),
        ).save()

        self.assertEqual(self.opportunity.trial_lessons.count(), 2)


class SponteStudentImportTests(TestCase):
    SAMPLE_XML = '''<?xml version="1.0" encoding="utf-8"?>
    <ArrayOfWsAluno xmlns="http://api.sponteeducacional.net.br/">
      <wsAluno>
        <AlunoID>123</AlunoID>
        <Nome>Aluno Sponte</Nome>
        <Celular>21999990000</Celular>
        <NumeroMatricula>M123</NumeroMatricula>
        <Situacao>Ativo</Situacao>
        <Responsaveis>
          <wsResponsaveis>
            <ResponsavelID>10</ResponsavelID>
            <Nome>Responsável Sponte</Nome>
            <Parentesco>Mãe</Parentesco>
          </wsResponsaveis>
        </Responsaveis>
      </wsAluno>
    </ArrayOfWsAluno>
    '''

    def test_import_creates_student_from_sponte_xml(self):
        records = parse_sponte_students(self.SAMPLE_XML)
        result = import_sponte_student_records(records)

        student = PedagogicalStudent.objects.get(external_id='123')
        self.assertEqual(result.created, 1)
        self.assertEqual(student.source, 'Sponte')
        self.assertEqual(student.name, 'Aluno Sponte')
        self.assertEqual(student.enrollment_number, 'M123')
        self.assertEqual(student.responsible_name, 'Responsável Sponte')
        self.assertEqual(student.whatsapp, '21999990000')
        self.assertTrue(student.active)

    def test_import_updates_existing_student_by_external_id(self):
        PedagogicalStudent.objects.create(
            name='Nome antigo',
            enrollment_number='M123',
            source='Sponte',
            external_id='123',
        )

        records = parse_sponte_students(self.SAMPLE_XML)
        result = import_sponte_student_records(records)

        student = PedagogicalStudent.objects.get(external_id='123')
        self.assertEqual(result.updated, 1)
        self.assertEqual(PedagogicalStudent.objects.count(), 1)
        self.assertEqual(student.name, 'Aluno Sponte')

    def test_import_reuses_existing_student_by_enrollment_number(self):
        PedagogicalStudent.objects.create(name='Aluno local', enrollment_number='M123')

        records = parse_sponte_students(self.SAMPLE_XML)
        result = import_sponte_student_records(records)

        student = PedagogicalStudent.objects.get(enrollment_number='M123')
        self.assertEqual(result.updated, 1)
        self.assertEqual(PedagogicalStudent.objects.count(), 1)
        self.assertEqual(student.source, 'Sponte')
        self.assertEqual(student.external_id, '123')


class SponteFreeClassScheduleSyncTests(TestCase):
    SAMPLE_XML = '''<?xml version="1.0" encoding="utf-8"?>
    <ArrayOfWsAgendaAluno xmlns="http://api.sponteeducacional.net.br/">
      <wsAgendaAluno>
        <AlunoID>123</AlunoID>
        <AulasLivres>
          <wsAulasLivresAluno>
            <AulaLivreID>900</AulaLivreID>
            <DataAula>07/07/2026</DataAula>
            <HorarioInicial>14:00</HorarioInicial>
            <HorarioFinal>16:00</HorarioFinal>
            <CursoID>77</CursoID>
            <NomeCurso>Techbot</NomeCurso>
            <DisciplinaID>88</DisciplinaID>
            <NomeDisciplina>Robótica</NomeDisciplina>
            <ProfessorID>99</ProfessorID>
            <NomeProfessor>Professor Sponte</NomeProfessor>
            <Sala>Sala Maker</Sala>
          </wsAulasLivresAluno>
        </AulasLivres>
      </wsAgendaAluno>
    </ArrayOfWsAgendaAluno>
    '''
    EMPTY_XML = '''<?xml version="1.0" encoding="utf-8"?>
    <ArrayOfWsAgendaAluno xmlns="http://api.sponteeducacional.net.br/">
      <wsAgendaAluno>
        <AlunoID>123</AlunoID>
        <AulasLivres />
      </wsAgendaAluno>
    </ArrayOfWsAgendaAluno>
    '''

    def setUp(self):
        self.student = PedagogicalStudent.objects.create(
            name='Aluno Sponte',
            responsible_name='Responsável',
            whatsapp='21999990000',
            source='Sponte',
            external_id='123',
        )

    def test_import_creates_regular_read_only_sponte_lesson(self):
        records = parse_sponte_free_class_schedule(self.SAMPLE_XML, student_external_id='123')
        result = import_sponte_free_class_records(
            self.student,
            records,
            start_date=date(2026, 7, 1),
            end_date=date(2026, 7, 31),
        )

        lesson = Lesson.objects.get(external_id='aula_livre:123:900:2026-07-07')
        self.assertEqual(result.created, 1)
        self.assertEqual(lesson.source, Lesson.SOURCE_SPONTE)
        self.assertEqual(lesson.lesson_type, Lesson.TYPE_REGULAR)
        self.assertEqual(lesson.student, self.student)
        self.assertEqual(lesson.course.name, 'Techbot')
        self.assertEqual(lesson.room.name, 'Sala Maker')
        self.assertTrue(lesson.is_sponte_synced)

    def test_sync_cancels_stale_sponte_lesson_without_deleting(self):
        records = parse_sponte_free_class_schedule(self.SAMPLE_XML, student_external_id='123')
        import_sponte_free_class_records(
            self.student,
            records,
            start_date=date(2026, 7, 1),
            end_date=date(2026, 7, 31),
        )

        result = sync_sponte_free_class_schedule(
            date(2026, 7, 1),
            date(2026, 7, 31),
            fetcher=lambda student_id, start, end: self.EMPTY_XML,
        )

        lesson = Lesson.objects.get(external_id='aula_livre:123:900:2026-07-07')
        self.assertEqual(result.cancelled, 1)
        self.assertEqual(lesson.status, Lesson.STATUS_CANCELLED)


class CommercialOpportunityInterestFormTests(TestCase):
    def setUp(self):
        self.course = Course.objects.create(
            name='Inteligência Artificial',
            value=Decimal('4190.00'),
            kit_quantity=4,
            active=True,
        )
        self.funnel_type, _ = FunnelType.objects.get_or_create(
            code='interessados',
            defaults={'name': 'Interessados', 'active': True},
        )
        self.stage, _ = FunnelStage.objects.get_or_create(
            code='novo-teste',
            defaults={'name': 'Novo teste', 'active': True, 'order': 1},
        )
        self.origin, _ = OpportunityOrigin.objects.get_or_create(
            code='whatsapp-teste',
            defaults={'name': 'WhatsApp teste', 'active': True},
        )
        self.funnel_model = FunnelModel.objects.create(name='Modelo comercial', active=True)
        self.funnel = CommercialFunnel.objects.create(
            name='Funil comercial',
            funnel_model=self.funnel_model,
            active=True,
        )

    def _form_data(self, **kwargs):
        data = {
            'title': 'Oportunidade teste',
            'commercial_funnel': str(self.funnel.pk),
            'funnel_type': str(self.funnel_type.pk),
            'stage': str(self.stage.pk),
            'origin': str(self.origin.pk),
            'interest': '',
            'value': '',
            'contact_name': 'Responsável',
            'contact_phone': '21999990000',
            'next_follow_up_date': '2026-07-10',
            'status': CommercialOpportunityForm.STATUS_ACTIVE,
            'follow_up_note': '',
            'notes': '',
        }
        data.update(kwargs)
        return data

    def test_course_interest_defaults_value_from_course(self):
        form = CommercialOpportunityForm(data=self._form_data(interest=f'course:{self.course.pk}'))
        self.assertTrue(form.is_valid(), form.errors)

        opportunity = form.save()

        self.assertEqual(opportunity.interest_course, self.course)
        self.assertEqual(opportunity.interest_type, '')
        self.assertEqual(opportunity.value, Decimal('4190.00'))

    def test_course_interest_allows_manual_value_override(self):
        form = CommercialOpportunityForm(data=self._form_data(
            interest=f'course:{self.course.pk}',
            value='3990.00',
        ))
        self.assertTrue(form.is_valid(), form.errors)

        opportunity = form.save()

        self.assertEqual(opportunity.interest_course, self.course)
        self.assertEqual(opportunity.value, Decimal('3990.00'))

    def test_blank_interest_clears_value(self):
        form = CommercialOpportunityForm(data=self._form_data(value='1200.00'))
        self.assertTrue(form.is_valid(), form.errors)

        opportunity = form.save()

        self.assertIsNone(opportunity.interest_course)
        self.assertEqual(opportunity.interest_type, '')
        self.assertIsNone(opportunity.value)

    def test_course_price_change_does_not_update_existing_opportunity(self):
        form = CommercialOpportunityForm(data=self._form_data(interest=f'course:{self.course.pk}'))
        self.assertTrue(form.is_valid(), form.errors)
        opportunity = form.save()

        self.course.value = Decimal('5000.00')
        self.course.save(update_fields=['value'])
        edit_form = CommercialOpportunityForm(
            data=self._form_data(
                title=opportunity.title,
                interest=f'course:{self.course.pk}',
                value='4190.00',
            ),
            instance=opportunity,
        )
        self.assertTrue(edit_form.is_valid(), edit_form.errors)

        opportunity = edit_form.save()

        self.assertEqual(opportunity.interest_course, self.course)
        self.assertEqual(opportunity.value, Decimal('4190.00'))
