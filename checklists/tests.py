from decimal import Decimal
from datetime import date, timedelta, time
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.core.cache import cache
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from .forms import CommercialOpportunityForm, CourseForm, add_months
from .models import (
    CommercialFunnel, CommercialOpportunity, CommercialOpportunityFollowUp,
    Course, FunnelModel, FunnelStage, FunnelType, Lesson, LessonFeedback,
    OpportunityOrigin, PedagogicalStudent, Position, Room, SchoolHoliday,
    TimeSlot, UserProfile,
)
from .sponte import (
    _sponte_config, default_sponte_schedule_window, import_sponte_course_records, import_sponte_free_class_records,
    import_sponte_student_records, parse_sponte_courses, parse_sponte_free_class_schedule, parse_sponte_students,
    SponteCourseImportResult, SponteScheduleSyncResult, SponteStudentImportResult,
    sync_sponte_free_class_schedule,
)
from .sponte_client import (
    SponteAPIDisabledError, SponteAPIRateLimitError, SponteSOAPClient, normalize_students,
)


User = get_user_model()


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

    def test_cancelled_lesson_does_not_block_room_or_kit(self):
        self._lesson(status=Lesson.STATUS_CANCELLED).save()
        lesson = self._lesson(student=self.other_student)

        lesson.save()

        self.assertEqual(Lesson.objects.count(), 2)

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


class LessonFeedbackTests(TestCase):
    def setUp(self):
        self.day = date(2026, 7, 7)
        self.course = Course.objects.create(name='Techbot', value='500.00', kit_quantity=2, active=True)
        self.room = Room.objects.create(name='Sala Maker', capacity=2, active=True)
        self.student = PedagogicalStudent.objects.create(name='Aluno Um', responsible_name='Responsável Um', whatsapp='21999990001')
        self.instructor_position = Position.objects.create(
            name='Instrutor de Cursos Livres',
            code='instrutor-aula-livre',
            active=True,
        )
        self.instructor = User.objects.create_user(username='instrutor-feedback', password='teste123')
        UserProfile.objects.create(
            user=self.instructor,
            display_name='Instrutor Feedback',
            system_role=UserProfile.ROLE_OPERATOR,
            position=self.instructor_position,
            active=True,
        )
        self.sales_position = Position.objects.create(
            name='Atendente Comercial',
            code='atendente-comercial',
            active=True,
        )
        self.sales_user = User.objects.create_user(username='atendente-pos-venda', password='teste123')
        UserProfile.objects.create(
            user=self.sales_user,
            display_name='Atendente Pós-Venda',
            system_role=UserProfile.ROLE_OPERATOR,
            position=self.sales_position,
            active=True,
        )
        self.lesson = Lesson.objects.create(
            lesson_type=Lesson.TYPE_REGULAR,
            student=self.student,
            course=self.course,
            room=self.room,
            date=self.day,
            start_time=time(14, 0),
            end_time=time(16, 0),
            status=Lesson.STATUS_DONE,
            source=Lesson.SOURCE_SPONTE,
            external_id='aula_livre:1',
        )
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

    def _feedback(self, **kwargs):
        data = {
            'lesson': self.lesson,
            'module_number': 1,
            'lesson_number': 1,
            'punctuality_score': 10,
            'assembly_comment': 'Montou dentro do tempo.',
            'assembly_score': 8,
            'has_programming': False,
            'participation_comment': 'Participou bem.',
            'participation_score': 9,
            'behavior_comment': 'Comportamento adequado.',
            'behavior_score': 10,
            'general_comment': 'Bom desempenho geral.',
        }
        data.update(kwargs)
        return LessonFeedback(**data)

    def _feedback_post_data(self, **kwargs):
        data = {
            'module_number': '1',
            'lesson_number': '10',
            'punctuality_score': '10',
            'assembly_comment': 'Montou dentro do tempo.',
            'assembly_score': '8',
            'participation_comment': 'Participou bem.',
            'participation_score': '9',
            'behavior_comment': 'Comportamento adequado.',
            'behavior_score': '10',
            'general_comment': 'Bom desempenho geral.',
            'general_score': '',
        }
        data.update(kwargs)
        return data

    def test_calculates_general_score_without_programming(self):
        feedback = self._feedback()
        feedback.save()

        self.assertEqual(str(feedback.general_score), '9.25')
        self.assertIsNone(feedback.programming_score)
        self.assertEqual(feedback.programming_comment, '')

    def test_calculates_general_score_with_programming(self):
        feedback = self._feedback(
            has_programming=True,
            programming_comment='Programou com apoio.',
            programming_score=7,
        )
        feedback.save()

        self.assertEqual(str(feedback.general_score), '8.80')

    def test_blocks_feedback_for_trial_or_play_lesson(self):
        trial = Lesson.objects.create(
            lesson_type=Lesson.TYPE_TRIAL,
            trial_kind=Lesson.TRIAL_KIND_PLAY,
            commercial_opportunity=self.opportunity,
            student_name_snapshot='Interessado Teste',
            course=self.course,
            room=self.room,
            date=self.day,
            start_time=time(16, 0),
            end_time=time(17, 0),
            status=Lesson.STATUS_DONE,
        )
        feedback = self._feedback(lesson=trial)

        with self.assertRaises(ValidationError) as ctx:
            feedback.save()

        self.assertIn('lesson', ctx.exception.message_dict)

    def test_tenth_lesson_feedback_creates_post_sale_opportunity_once(self):
        self.client.force_login(self.instructor)

        response = self.client.post(
            reverse('pedagogical_lesson_feedback_edit', args=[self.lesson.id]),
            self._feedback_post_data(),
        )

        self.assertRedirects(response, f"{reverse('pedagogical_lesson_feedbacks')}?data={self.lesson.date.isoformat()}")
        automation_key = f'post-sale:lesson-10:student:{self.student.id}:module:1'
        opportunity = CommercialOpportunity.objects.get(automation_key=automation_key)
        self.assertEqual(opportunity.funnel_type.code, 'posvenda')
        self.assertEqual(opportunity.stage.code, '6-pos-venda')
        self.assertEqual(opportunity.origin.code, 'sistema')
        self.assertEqual(opportunity.commercial_funnel.name, 'Pós-Venda')
        self.assertEqual(opportunity.owner, self.sales_user)
        self.assertEqual(opportunity.contact_name, self.student.responsible_name)
        self.assertEqual(opportunity.contact_phone, self.student.whatsapp)
        self.assertEqual(opportunity.interest_course, self.course)
        self.assertEqual(opportunity.next_follow_up_date, timezone.localdate() + timedelta(days=1))
        self.assertIn('10ª aula', opportunity.notes)
        self.assertIn('próxima apostila', opportunity.notes)
        self.assertEqual(CommercialOpportunityFollowUp.objects.filter(opportunity=opportunity).count(), 1)

        response = self.client.post(
            reverse('pedagogical_lesson_feedback_edit', args=[self.lesson.id]),
            self._feedback_post_data(assembly_comment='Feedback atualizado.'),
        )

        self.assertRedirects(response, f"{reverse('pedagogical_lesson_feedbacks')}?data={self.lesson.date.isoformat()}")
        self.assertEqual(CommercialOpportunity.objects.filter(automation_key=automation_key).count(), 1)
        self.assertEqual(CommercialOpportunityFollowUp.objects.filter(opportunity=opportunity).count(), 1)

    def test_feedback_before_tenth_lesson_does_not_create_post_sale_opportunity(self):
        self.client.force_login(self.instructor)

        response = self.client.post(
            reverse('pedagogical_lesson_feedback_edit', args=[self.lesson.id]),
            self._feedback_post_data(lesson_number='9'),
        )

        self.assertRedirects(response, f"{reverse('pedagogical_lesson_feedbacks')}?data={self.lesson.date.isoformat()}")
        self.assertFalse(CommercialOpportunity.objects.filter(automation_key__startswith='post-sale:lesson-10').exists())


class InstructorExperienceTests(TestCase):
    def setUp(self):
        self.position = Position.objects.create(
            name='Instrutor de Cursos Livres',
            code='instrutor-aula-livre',
            active=True,
        )
        self.user = User.objects.create_user(username='instrutor', password='teste123')
        UserProfile.objects.create(
            user=self.user,
            display_name='Instrutor Teste',
            system_role=UserProfile.ROLE_OPERATOR,
            position=self.position,
            active=True,
        )
        self.today = timezone.localdate()
        self.week_trial_day = self.today + timedelta(days=max(0, 5 - self.today.weekday()))
        self.course = Course.objects.create(name='Firstbot 2.0', value=Decimal('3690.00'), kit_quantity=2, active=True)
        self.room = Room.objects.create(name='Sala Maker', capacity=3, active=True)
        self.student = PedagogicalStudent.objects.create(
            name='Aluno Regular',
            responsible_name='Responsável Regular',
            whatsapp='21999990001',
        )
        self.today_lesson = Lesson.objects.create(
            lesson_type=Lesson.TYPE_REGULAR,
            student=self.student,
            course=self.course,
            room=self.room,
            date=self.today,
            start_time=time(23, 0),
            end_time=time(23, 30),
            status=Lesson.STATUS_NOT_GIVEN,
            source=Lesson.SOURCE_SPONTE,
            external_id='regular-hoje',
        )
        self.pending_feedback_lesson = Lesson.objects.create(
            lesson_type=Lesson.TYPE_REGULAR,
            student=self.student,
            course=self.course,
            room=self.room,
            date=self.today - timedelta(days=1),
            start_time=time(13, 0),
            end_time=time(15, 0),
            status=Lesson.STATUS_DONE,
            source=Lesson.SOURCE_SPONTE,
            external_id='regular-ontem',
        )
        funnel_model = FunnelModel.objects.create(name='Modelo teste', active=True)
        funnel = CommercialFunnel.objects.create(name='Funil teste', funnel_model=funnel_model, active=True)
        opportunity = CommercialOpportunity.objects.create(
            title='07-2026-0001',
            commercial_funnel=funnel,
            contact_name='Responsável Trial',
            contact_phone='21999990002',
            next_follow_up_date=self.today,
            active=True,
        )
        self.trial_lesson = Lesson.objects.create(
            lesson_type=Lesson.TYPE_TRIAL,
            trial_kind=Lesson.TRIAL_KIND_EXPERIMENTAL,
            commercial_opportunity=opportunity,
            student_name_snapshot='Criança Trial',
            responsible_name_snapshot='Responsável Trial',
            whatsapp_snapshot='21999990002',
            course=self.course,
            room=self.room,
            date=self.week_trial_day,
            start_time=time(15, 0),
            end_time=time(17, 0),
            status=Lesson.STATUS_NOT_GIVEN,
        )

    def test_operational_home_redirects_instructor_to_dashboard(self):
        self.client.force_login(self.user)

        response = self.client.get(reverse('operational_home'))

        self.assertRedirects(response, reverse('instructor_dashboard'))

    def test_instructor_dashboard_surfaces_core_work(self):
        self.client.force_login(self.user)

        response = self.client.get(reverse('instructor_dashboard'))

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context['today_count'], 1)
        self.assertEqual(response.context['pending_feedback_count'], 1)
        self.assertContains(response, 'Painel do Instrutor')
        self.assertContains(response, 'Aluno Regular')
        self.assertContains(response, 'Criança Trial')
        self.assertContains(response, 'Importar do Sponte')
        self.assertNotContains(response, 'Gestão Pedagógica')

    def test_instructor_can_import_all_sponte_data_from_menu_action(self):
        self.client.force_login(self.user)

        with (
            patch('checklists.pedagogical_views.import_sponte_courses') as courses_mock,
            patch('checklists.pedagogical_views.import_sponte_students') as students_mock,
            patch('checklists.pedagogical_views.sync_sponte_free_class_schedule') as schedule_mock,
        ):
            courses_mock.return_value = SponteCourseImportResult(created=1, updated=2, unchanged=3)
            students_mock.return_value = SponteStudentImportResult(created=4, updated=5, unchanged=6)
            schedule_mock.return_value = SponteScheduleSyncResult(created=7, updated=8, unchanged=9, cancelled=1)

            response = self.client.post(
                reverse('instructor_import_sponte'),
                {'next': reverse('instructor_dashboard')},
                follow=True,
            )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.redirect_chain[-1][0], reverse('instructor_dashboard'))
        courses_mock.assert_called_once_with()
        students_mock.assert_called_once_with()
        schedule_mock.assert_called_once()
        self.assertContains(response, 'Importação do Sponte concluída')

    def test_instructor_agenda_is_read_only_and_links_feedback(self):
        self.client.force_login(self.user)

        response = self.client.get(f"{reverse('instructor_agenda')}?periodo=semana&data={self.today.isoformat()}")

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Agenda do Instrutor')
        self.assertContains(response, 'Preencher feedback')
        self.assertContains(response, 'Aula Experimental ou Play')
        self.assertContains(response, 'Importar do Sponte')
        self.assertNotContains(response, 'Sincronizar Sponte')
        self.assertNotContains(response, 'Nova aula Experimental ou Play')


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
    NO_RECORDS_XML = '''<?xml version="1.0" encoding="utf-8"?>
    <ArrayOfWsAluno xmlns="http://api.sponteeducacional.net.br/">
      <wsAluno>
        <RetornoOperacao>43 - Nenhum registro foi encontrado para os parâmetros de busca informados.</RetornoOperacao>
        <AlunoID>0</AlunoID>
        <ResponsavelFinanceiroID>0</ResponsavelFinanceiroID>
        <ResponsavelDidaticoID>0</ResponsavelDidaticoID>
      </wsAluno>
    </ArrayOfWsAluno>
    '''
    INACTIVE_XML = '''<?xml version="1.0" encoding="utf-8"?>
    <ArrayOfWsAluno xmlns="http://api.sponteeducacional.net.br/">
      <wsAluno>
        <RetornoOperacao>01 - Operação Realizada com Sucesso.</RetornoOperacao>
        <AlunoID>456</AlunoID>
        <Nome>Aluno Inativo Sponte</Nome>
        <NumeroMatricula>M456</NumeroMatricula>
        <Situacao>Inativo</Situacao>
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

    def test_no_records_response_does_not_create_nameless_student(self):
        records = parse_sponte_students(self.NO_RECORDS_XML)
        result = import_sponte_student_records(records)

        self.assertEqual(records, [])
        self.assertEqual(result.skipped, 0)
        self.assertEqual(PedagogicalStudent.objects.count(), 0)

    def test_import_keeps_inactive_sponte_students(self):
        records = parse_sponte_students(self.INACTIVE_XML)
        result = import_sponte_student_records(records)

        student = PedagogicalStudent.objects.get(external_id='456')
        self.assertEqual(result.created, 1)
        self.assertEqual(student.name, 'Aluno Inativo Sponte')
        self.assertEqual(student.status, PedagogicalStudent.STATUS_INACTIVE)

    @override_settings(
        SPONTE_API_URL='https://api.sponteeducacional.net.br/WSAPIEdu.asmx',
        SPONTE_CODIGO_CLIENTE='123',
        SPONTE_TOKEN='token',
        SPONTE_STUDENT_SEARCH_PARAMS='Situacao=1',
        SPONTE_TIMEOUT_SECONDS=30,
    )
    def test_legacy_student_search_param_uses_wildcard_name_filter(self):
        *_, search_params, _timeout = _sponte_config()

        self.assertEqual(search_params, 'Nome=%')


class SponteCourseImportTests(TestCase):
    SAMPLE_XML = '''<?xml version="1.0" encoding="utf-8"?>
    <ArrayOfWsCurso xmlns="http://api.sponteeducacional.net.br/">
      <wsCurso>
        <CursoID>10</CursoID>
        <Nome>FIRSTBOT 1.0</Nome>
        <Situacao>Ativo</Situacao>
      </wsCurso>
      <wsCurso>
        <CursoID>11</CursoID>
        <Nome>FIRSTBOT 2.0</Nome>
        <Situacao>Ativo</Situacao>
      </wsCurso>
      <wsCurso>
        <CursoID>12</CursoID>
        <Nome>ELECTROBOT 2.0</Nome>
        <Situacao>Ativo</Situacao>
      </wsCurso>
    </ArrayOfWsCurso>
    '''
    ELECTROBOT_XML = '''<?xml version="1.0" encoding="utf-8"?>
    <ArrayOfWsCurso xmlns="http://api.sponteeducacional.net.br/">
      <wsCurso>
        <CursoID>12</CursoID>
        <Nome>ELECTROBOT 2.0</Nome>
        <Situacao>Ativo</Situacao>
      </wsCurso>
    </ArrayOfWsCurso>
    '''

    def test_parse_keeps_version_two_and_ignores_legacy_courses(self):
        records = parse_sponte_courses(self.SAMPLE_XML)

        names = {record['name'] for record in records}
        self.assertIn('FIRSTBOT 2.0', names)
        self.assertIn('ELECTROBOT 2.0', names)
        self.assertNotIn('FIRSTBOT 1.0', names)

    def test_import_replaces_manual_conflicting_course_with_sponte_course(self):
        Course.objects.create(
            name='Electrobot',
            value=Decimal('3690.00'),
            kit_quantity=1,
            max_students_per_slot=1,
            active=True,
        )

        records = parse_sponte_courses(self.ELECTROBOT_XML)
        result = import_sponte_course_records(records)

        course = Course.objects.get()
        self.assertEqual(result.updated, 1)
        self.assertEqual(course.name, 'ELECTROBOT 2.0')
        self.assertEqual(course.source, Course.SOURCE_SPONTE)
        self.assertEqual(course.external_id, '12')
        self.assertEqual(course.value, Decimal('3690.00'))
        self.assertEqual(course.kit_quantity, 1)


class CourseFormTests(TestCase):
    def _form_data(self, name='ELECTROBOT', value='3690'):
        return {
            'name': name,
            'description': 'Criado automaticamente pela sincronização de agenda do Sponte.',
            'value': value,
            'kit_quantity': '1',
            'max_students_per_slot': '1',
            'status': CourseForm.STATUS_ACTIVE,
        }

    def test_edit_allows_same_name_when_legacy_inactive_duplicate_exists(self):
        Course.objects.create(
            name='Electrobot',
            value=Decimal('3690.00'),
            kit_quantity=1,
            max_students_per_slot=1,
            active=False,
        )
        course = Course.objects.create(
            name='ELECTROBOT',
            value=Decimal('0.00'),
            kit_quantity=1,
            max_students_per_slot=1,
            active=True,
            source=Course.SOURCE_SPONTE,
            external_id='-24',
        )

        form = CourseForm(data=self._form_data(), instance=course)

        self.assertTrue(form.is_valid(), form.errors)

    def test_edit_blocks_renaming_to_existing_course_name(self):
        Course.objects.create(
            name='FIRSTBOT 2.0',
            value=Decimal('3690.00'),
            kit_quantity=2,
            max_students_per_slot=2,
            active=True,
        )
        course = Course.objects.create(
            name='ELECTROBOT',
            value=Decimal('3690.00'),
            kit_quantity=1,
            max_students_per_slot=1,
            active=True,
        )

        form = CourseForm(data=self._form_data(name='FIRSTBOT 2.0'), instance=course)

        self.assertFalse(form.is_valid())
        self.assertIn('name', form.errors)


@override_settings(
    SPONTE_API_ENABLED=True,
    SPONTE_API_BASE_URL='https://api.sponteeducacional.net.br/WSAPIEdu.asmx',
    SPONTE_API_CLIENT_CODE='client-123',
    SPONTE_API_TOKEN='very-secret-token',
    SPONTE_API_TIMEOUT_SECONDS=5,
    SPONTE_API_CACHE_TTL_MINUTES=30,
    SPONTE_API_MAX_REQUESTS_PER_MINUTE=30,
)
class SponteSOAPClientSafetyTests(TestCase):
    STUDENTS_XML = '''<?xml version="1.0" encoding="utf-8"?>
    <ArrayOfWsAluno xmlns="http://api.sponteeducacional.net.br/">
      <wsAluno>
        <RetornoOperacao>01 - Operação Realizada com Sucesso.</RetornoOperacao>
        <AlunoID>123</AlunoID>
        <Nome>Aluno Sponte</Nome>
        <NumeroMatricula>M123</NumeroMatricula>
        <CPF>00000000000</CPF>
        <SenhaPortal>segredo-do-portal</SenhaPortal>
      </wsAluno>
    </ArrayOfWsAluno>
    '''

    COURSES_XML = '''<?xml version="1.0" encoding="utf-8"?>
    <ArrayOfWsCurso xmlns="http://api.sponteeducacional.net.br/">
      <wsCurso>
        <RetornoOperacao>01 - Operação Realizada com Sucesso.</RetornoOperacao>
        <CursoID>10</CursoID>
        <Nome>FIRSTBOT 2.0</Nome>
      </wsCurso>
    </ArrayOfWsCurso>
    '''

    def setUp(self):
        cache.clear()

    def test_safe_log_never_contains_token_or_client_code(self):
        client = SponteSOAPClient(fetcher=lambda _request, _timeout: self.STUDENTS_XML)

        with self.assertLogs('checklists.sponte', level='INFO') as captured:
            client.get_students('Nome=%')

        log_output = '\n'.join(captured.output)
        self.assertIn('GetAlunos', log_output)
        self.assertNotIn('very-secret-token', log_output)
        self.assertNotIn('client-123', log_output)

    def test_cache_prevents_second_external_call(self):
        calls = []

        def fetcher(_request, _timeout):
            calls.append(1)
            return self.COURSES_XML

        client = SponteSOAPClient(fetcher=fetcher)
        first = client.get_courses('Situacao=1')
        second = client.get_courses('Situacao=1')

        self.assertEqual(len(calls), 1)
        self.assertFalse(first.from_cache)
        self.assertTrue(second.from_cache)

    def test_forced_refresh_bypasses_and_updates_cache(self):
        responses = [self.STUDENTS_XML, self.COURSES_XML]

        def fetcher(_request, _timeout):
            return responses.pop(0)

        client = SponteSOAPClient(fetcher=fetcher)
        first = client.get_courses('Situacao=1')
        refreshed = client.call('GetCursos', {'sParametrosBusca': 'Situacao=1'}, use_cache=False)
        cached_after_refresh = client.get_courses('Situacao=1')

        self.assertFalse(first.from_cache)
        self.assertFalse(refreshed.from_cache)
        self.assertTrue(cached_after_refresh.from_cache)
        self.assertIn('FIRSTBOT 2.0', refreshed.xml_text)
        self.assertIn('FIRSTBOT 2.0', cached_after_refresh.xml_text)

    def test_timeout_uses_last_valid_cache_when_available(self):
        client = SponteSOAPClient(fetcher=lambda _request, _timeout: self.COURSES_XML)
        client.get_courses('Situacao=1')
        cache.delete(client._cache_key('GetCursos', {'sParametrosBusca': 'Situacao=1'}))

        failing_client = SponteSOAPClient(fetcher=lambda _request, _timeout: (_ for _ in ()).throw(TimeoutError()))
        response = failing_client.get_courses('Situacao=1')

        self.assertTrue(response.from_cache)
        self.assertTrue(response.stale_cache)
        self.assertIn('FIRSTBOT 2.0', response.xml_text)

    @override_settings(SPONTE_API_MAX_REQUESTS_PER_MINUTE=1)
    def test_rate_limit_blocks_when_cache_cannot_be_used(self):
        client = SponteSOAPClient(fetcher=lambda _request, _timeout: self.STUDENTS_XML)
        client.get_students('Nome=A')

        with self.assertRaises(SponteAPIRateLimitError):
            client.get_students('Nome=B')

    def test_normalizer_discards_sensitive_fields(self):
        snapshots = normalize_students(self.STUDENTS_XML)

        self.assertEqual(len(snapshots), 1)
        self.assertEqual(snapshots[0].name, 'Aluno Sponte')
        self.assertIn('CPF', snapshots[0].discarded_sensitive_fields)
        self.assertIn('SenhaPortal', snapshots[0].discarded_sensitive_fields)
        self.assertFalse(hasattr(snapshots[0], 'password'))

    @override_settings(SPONTE_API_ENABLED=False)
    def test_disabled_integration_fails_before_external_request(self):
        calls = []
        client = SponteSOAPClient(fetcher=lambda _request, _timeout: calls.append(1))

        with self.assertRaises(SponteAPIDisabledError):
            client.get_courses('Situacao=1')

        self.assertEqual(calls, [])


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
    CANCELLED_XML = '''<?xml version="1.0" encoding="utf-8"?>
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
            <SituacaoAula>Cancelada</SituacaoAula>
          </wsAulasLivresAluno>
        </AulasLivres>
      </wsAgendaAluno>
    </ArrayOfWsAgendaAluno>
    '''
    CANCELLED_FLAG_XML = '''<?xml version="1.0" encoding="utf-8"?>
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
            <P>0</P>
            <F>0</F>
            <C>1</C>
          </wsAulasLivresAluno>
        </AulasLivres>
      </wsAgendaAluno>
    </ArrayOfWsAgendaAluno>
    '''

    def setUp(self):
        self.today = date(2026, 7, 1)
        self.localdate_patcher = patch('checklists.sponte.timezone.localdate', return_value=self.today)
        self.localdate_patcher.start()
        self.addCleanup(self.localdate_patcher.stop)
        self.student = PedagogicalStudent.objects.create(
            name='Aluno Sponte',
            responsible_name='Responsável',
            whatsapp='21999990000',
            source='Sponte',
            external_id='123',
        )

    @override_settings(SPONTE_SCHEDULE_SYNC_DAYS_BACK=30, SPONTE_SCHEDULE_SYNC_DAYS_AHEAD=10)
    def test_default_schedule_window_starts_on_sync_day(self):
        start_date, end_date = default_sponte_schedule_window(date(2026, 6, 1))

        self.assertEqual(start_date, self.today)
        self.assertEqual(end_date, date(2026, 7, 11))

    def test_import_ignores_past_sponte_lessons(self):
        xml_text = '''<?xml version="1.0" encoding="utf-8"?>
        <ArrayOfWsAgendaAluno xmlns="http://api.sponteeducacional.net.br/">
          <wsAgendaAluno>
            <AlunoID>123</AlunoID>
            <AulasLivres>
              <wsAulasLivresAluno>
                <AulaLivreID>899</AulaLivreID>
                <DataAula>30/06/2026</DataAula>
                <HorarioInicial>14:00</HorarioInicial>
                <HorarioFinal>16:00</HorarioFinal>
                <CursoID>77</CursoID>
                <NomeCurso>Techbot</NomeCurso>
                <Sala>Sala Maker</Sala>
              </wsAulasLivresAluno>
            </AulasLivres>
          </wsAgendaAluno>
        </ArrayOfWsAgendaAluno>
        '''
        records = parse_sponte_free_class_schedule(xml_text, student_external_id='123')

        result = import_sponte_free_class_records(
            self.student,
            records,
            start_date=date(2026, 6, 1),
            end_date=date(2026, 7, 31),
        )

        self.assertEqual(result.created, 0)
        self.assertEqual(result.skipped, 1)
        self.assertFalse(Lesson.objects.filter(external_id='aula_livre:123:899:2026-06-30').exists())

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
        self.assertEqual(lesson.status, Lesson.STATUS_NOT_GIVEN)
        self.assertIn('Situação no Sponte: não informada pela API', lesson.notes)
        self.assertTrue(lesson.is_sponte_synced)

    def test_parse_success_response_without_lessons_is_empty_schedule(self):
        xml_text = '''<?xml version="1.0" encoding="utf-8"?>
        <ArrayOfWsAgendaAluno xmlns="http://api.sponteeducacional.net.br/">
          <wsAgendaAluno>
            <RetornoOperacao>01 - Operação Realizada com Sucesso.</RetornoOperacao>
            <AlunoID>123</AlunoID>
            <AulasLivres />
          </wsAgendaAluno>
        </ArrayOfWsAgendaAluno>
        '''

        records = parse_sponte_free_class_schedule(xml_text, student_external_id='123')

        self.assertEqual(records, [])

    def test_import_updates_lesson_status_from_sponte_situation(self):
        records = parse_sponte_free_class_schedule(self.SAMPLE_XML, student_external_id='123')
        import_sponte_free_class_records(
            self.student,
            records,
            start_date=date(2026, 7, 1),
            end_date=date(2026, 7, 31),
        )

        cancelled_records = parse_sponte_free_class_schedule(self.CANCELLED_XML, student_external_id='123')
        result = import_sponte_free_class_records(
            self.student,
            cancelled_records,
            start_date=date(2026, 7, 1),
            end_date=date(2026, 7, 31),
        )

        lesson = Lesson.objects.get(external_id='aula_livre:123:900:2026-07-07')
        self.assertEqual(result.updated, 1)
        self.assertEqual(cancelled_records[0]['lesson_status'], 'Cancelada')
        self.assertEqual(lesson.status, Lesson.STATUS_CANCELLED)

    def test_import_updates_lesson_status_from_sponte_cancelled_flag(self):
        records = parse_sponte_free_class_schedule(self.SAMPLE_XML, student_external_id='123')
        import_sponte_free_class_records(
            self.student,
            records,
            start_date=date(2026, 7, 1),
            end_date=date(2026, 7, 31),
        )

        cancelled_records = parse_sponte_free_class_schedule(self.CANCELLED_FLAG_XML, student_external_id='123')
        result = import_sponte_free_class_records(
            self.student,
            cancelled_records,
            start_date=date(2026, 7, 1),
            end_date=date(2026, 7, 31),
        )

        lesson = Lesson.objects.get(external_id='aula_livre:123:900:2026-07-07')
        self.assertEqual(result.updated, 1)
        self.assertEqual(cancelled_records[0]['lesson_status'], 'Cancelada')
        self.assertEqual(lesson.status, Lesson.STATUS_CANCELLED)

    def test_import_preserves_existing_status_when_sponte_omits_lesson_status(self):
        cancelled_records = parse_sponte_free_class_schedule(self.CANCELLED_XML, student_external_id='123')
        import_sponte_free_class_records(
            self.student,
            cancelled_records,
            start_date=date(2026, 7, 1),
            end_date=date(2026, 7, 31),
        )

        records_without_status = parse_sponte_free_class_schedule(self.SAMPLE_XML, student_external_id='123')
        result = import_sponte_free_class_records(
            self.student,
            records_without_status,
            start_date=date(2026, 7, 1),
            end_date=date(2026, 7, 31),
        )

        lesson = Lesson.objects.get(external_id='aula_livre:123:900:2026-07-07')
        self.assertEqual(result.updated, 1)
        self.assertEqual(lesson.status, Lesson.STATUS_CANCELLED)

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

    def test_sync_never_requests_past_dates(self):
        calls = []

        def fetcher(student_id, start, end):
            calls.append((student_id, start, end))
            return self.EMPTY_XML

        sync_sponte_free_class_schedule(
            date(2026, 6, 1),
            date(2026, 7, 31),
            fetcher=fetcher,
        )

        self.assertEqual(calls, [('123', self.today, date(2026, 7, 31))])

    def test_sync_frees_old_slot_when_student_changes_schedule_in_sponte(self):
        records = parse_sponte_free_class_schedule(self.SAMPLE_XML, student_external_id='123')
        import_sponte_free_class_records(
            self.student,
            records,
            start_date=date(2026, 7, 1),
            end_date=date(2026, 7, 31),
        )
        changed_schedule_xml = '''<?xml version="1.0" encoding="utf-8"?>
        <ArrayOfWsAgendaAluno xmlns="http://api.sponteeducacional.net.br/">
          <wsAgendaAluno>
            <AlunoID>123</AlunoID>
            <AulasLivres>
              <wsAulasLivresAluno>
                <AulaLivreID>901</AulaLivreID>
                <DataAula>07/07/2026</DataAula>
                <HorarioInicial>16:00</HorarioInicial>
                <HorarioFinal>18:00</HorarioFinal>
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

        result = sync_sponte_free_class_schedule(
            date(2026, 7, 1),
            date(2026, 7, 31),
            fetcher=lambda student_id, start, end: changed_schedule_xml,
        )

        old_lesson = Lesson.objects.get(external_id='aula_livre:123:900:2026-07-07')
        new_lesson = Lesson.objects.get(external_id='aula_livre:123:901:2026-07-07')
        self.assertEqual(result.created, 1)
        self.assertEqual(result.cancelled, 1)
        self.assertEqual(old_lesson.status, Lesson.STATUS_CANCELLED)
        self.assertEqual(new_lesson.status, Lesson.STATUS_NOT_GIVEN)
        self.assertEqual(new_lesson.start_time, time(16, 0))

    def test_sync_cancels_future_sponte_lessons_outside_active_student_scope(self):
        inactive_student = PedagogicalStudent.objects.create(
            name='Aluno Inativo Sponte',
            responsible_name='Responsável',
            whatsapp='21999990001',
            source='Sponte',
            external_id='999',
            status=PedagogicalStudent.STATUS_INACTIVE,
        )
        course = Course.objects.create(name='Curso Sponte Inativo', value=Decimal('0.00'), kit_quantity=1)
        room = Room.objects.create(name='Sala Sponte', capacity=1)
        lesson = Lesson.objects.create(
            lesson_type=Lesson.TYPE_REGULAR,
            student=inactive_student,
            course=course,
            room=room,
            date=date(2026, 7, 8),
            start_time=time(9, 0),
            end_time=time(11, 0),
            status=Lesson.STATUS_SCHEDULED,
            source=Lesson.SOURCE_SPONTE,
            external_id='aula_livre:999:800:2026-07-08',
        )

        result = sync_sponte_free_class_schedule(
            date(2026, 7, 1),
            date(2026, 7, 31),
            fetcher=lambda student_id, start, end: self.EMPTY_XML,
        )

        lesson.refresh_from_db()
        self.assertEqual(result.cancelled, 1)
        self.assertEqual(lesson.status, Lesson.STATUS_CANCELLED)


class LessonAgendaViewTests(TestCase):
    def setUp(self):
        self.admin = User.objects.create_superuser(
            username='agenda-admin',
            email='agenda-admin@example.com',
            password='testpass123',
        )
        self.course = Course.objects.create(name='Techbot', value=Decimal('3690.00'), kit_quantity=4, active=True)
        self.room = Room.objects.create(name='Sala Maker', capacity=4, active=True)
        self.student = PedagogicalStudent.objects.create(
            name='Aluno Agenda',
            responsible_name='Responsável Agenda',
            whatsapp='21999990000',
        )

    def _lesson(self, lesson_date, student_name):
        student = PedagogicalStudent.objects.create(
            name=student_name,
            responsible_name='Responsável Agenda',
            whatsapp='21999990000',
        )
        return Lesson.objects.create(
            lesson_type=Lesson.TYPE_REGULAR,
            student=student,
            student_name_snapshot=student_name,
            responsible_name_snapshot='Responsável Agenda',
            course=self.course,
            room=self.room,
            date=lesson_date,
            start_time=time(14, 0),
            end_time=time(16, 0),
            status=Lesson.STATUS_SCHEDULED,
        )

    def test_week_period_filter_shows_lessons_from_selected_week(self):
        self._lesson(date(2026, 7, 7), 'Aluno Semana')
        self._lesson(date(2026, 7, 9), 'Aluno Mesma Semana')
        self._lesson(date(2026, 7, 14), 'Aluno Fora')
        self.client.force_login(self.admin)

        response = self.client.get(reverse('pedagogical_class_schedule'), {
            'data': '2026-07-08',
            'periodo': 'semana',
        })

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Aluno Semana')
        self.assertContains(response, 'Aluno Mesma Semana')
        self.assertNotContains(response, 'Aluno Fora')
        self.assertContains(response, 'data-auto-submit')
        self.assertContains(response, 'lesson-calendar')
        self.assertEqual(response.context['period_start'], date(2026, 7, 6))
        self.assertEqual(response.context['period_end'], date(2026, 7, 12))
        self.assertEqual(len(response.context['calendar_weeks']), 1)
        self.assertEqual(response.context['calendar_weeks'][0][0]['date'], date(2026, 7, 6))


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
        self.room = Room.objects.create(name='Sala Comercial', capacity=3, active=True)
        self.funnel_model = FunnelModel.objects.create(name='Modelo comercial', active=True)
        self.funnel = CommercialFunnel.objects.create(
            name='Funil comercial',
            funnel_model=self.funnel_model,
            active=True,
        )

    def _form_data(self, **kwargs):
        data = {
            'title': '06-2026-0001',
            'commercial_funnel': str(self.funnel.pk),
            'stage': str(self.stage.pk),
            'origin': str(self.origin.pk),
            'interest': '',
            'value': '',
            'contact_name': 'Responsável',
            'contact_phone': '21999990000',
            'next_follow_up_date': '2026-07-10',
            'status': CommercialOpportunityForm.STATUS_ACTIVE,
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

    def test_stage_aula_experimental_agendada_requires_trial_lesson(self):
        stage = FunnelStage.objects.create(
            code='aula-experimental-agendada',
            name='Aula Experimental Agendada',
            active=True,
            order=2,
        )
        form = CommercialOpportunityForm(data=self._form_data(stage=str(stage.pk)))

        self.assertFalse(form.is_valid())
        self.assertIn('trial_lesson_slot', form.errors)

    def test_trial_lesson_payload_is_prepared_from_available_slot(self):
        stage = FunnelStage.objects.create(
            code='aula-experimental-agendada-form',
            name='Aula Experimental Agendada Form',
            active=True,
            order=3,
        )
        selected_date = date(2026, 7, 14)
        slot = {
            'value': f'{selected_date.isoformat()}|09:00|11:00|{self.room.pk}',
            'label': '14/07 09:00-11:00 · Sala Comercial',
            'date': selected_date,
            'start_time': time(9, 0),
            'end_time': time(11, 0),
            'room': self.room,
        }
        form = CommercialOpportunityForm(
            data=self._form_data(
                stage=str(stage.pk),
                trial_lesson_kind=Lesson.TRIAL_KIND_EXPERIMENTAL,
                trial_lesson_course=str(self.course.pk),
                trial_lesson_slot=slot['value'],
                trial_lesson_student_name='Criança Teste',
                trial_lesson_notes='Cliente prefere conhecer o curso.',
            ),
            available_trial_slots=[slot],
        )

        self.assertTrue(form.is_valid(), form.errors)
        self.assertEqual(form.trial_lesson_payload['trial_kind'], Lesson.TRIAL_KIND_EXPERIMENTAL)
        self.assertEqual(form.trial_lesson_payload['course'], self.course)
        self.assertEqual(form.trial_lesson_payload['room'], self.room)
        self.assertEqual(form.trial_lesson_payload['student_name'], 'Criança Teste')

    def test_trial_lesson_can_leave_course_to_define_during_class(self):
        stage = FunnelStage.objects.create(
            code='aula-experimental-sem-curso',
            name='Aula Experimental Agendada sem curso',
            active=True,
            order=4,
        )
        selected_date = date(2026, 7, 15)
        slot = {
            'value': f'{selected_date.isoformat()}|09:00|11:00|{self.room.pk}',
            'label': '15/07 09:00-11:00 · Sala Comercial',
            'date': selected_date,
            'start_time': time(9, 0),
            'end_time': time(11, 0),
            'room': self.room,
        }
        form = CommercialOpportunityForm(
            data=self._form_data(
                stage=str(stage.pk),
                trial_lesson_kind=Lesson.TRIAL_KIND_EXPERIMENTAL,
                trial_lesson_course='',
                trial_lesson_slot=slot['value'],
            ),
            available_trial_slots=[slot],
        )

        self.assertTrue(form.is_valid(), form.errors)
        self.assertIsNone(form.trial_lesson_payload['course'])

    def test_lost_stage_defaults_inactive_and_future_follow_up(self):
        lost_stage = FunnelStage.objects.create(
            code='5-perdido',
            name='5 - Perdido',
            active=True,
            order=5,
        )
        form = CommercialOpportunityForm(data=self._form_data(
            stage=str(lost_stage.pk),
            next_follow_up_date='',
            status=CommercialOpportunityForm.STATUS_ACTIVE,
        ))

        self.assertTrue(form.is_valid(), form.errors)
        opportunity = form.save()
        self.assertFalse(opportunity.active)
        self.assertEqual(opportunity.next_follow_up_date, add_months(timezone.localdate(), 3))


class CommercialDashboardTests(TestCase):
    def setUp(self):
        self.position = Position.objects.create(
            name='Atendente Comercial',
            code='atendente-comercial',
            active=True,
        )
        self.user = User.objects.create_user(username='atendente', password='teste123')
        UserProfile.objects.create(
            user=self.user,
            display_name='Atendente Comercial',
            system_role=UserProfile.ROLE_OPERATOR,
            position=self.position,
            active=True,
        )
        self.other_user = User.objects.create_user(username='outro-atendente', password='teste123')
        UserProfile.objects.create(
            user=self.other_user,
            display_name='Outro Atendente',
            system_role=UserProfile.ROLE_OPERATOR,
            position=self.position,
            active=True,
        )
        self.funnel_model = FunnelModel.objects.create(name='Modelo comercial', active=True)
        self.funnel = CommercialFunnel.objects.create(
            name='Funil comercial',
            funnel_model=self.funnel_model,
            active=True,
        )
        self.interested_type, _ = FunnelType.objects.get_or_create(
            code='interessados',
            defaults={'name': 'Interessados', 'active': True},
        )
        self.interested_model = FunnelModel.objects.create(
            name='Modelo interessados',
            funnel_type=self.interested_type,
            active=True,
        )
        self.interested_funnel = CommercialFunnel.objects.create(
            name='Interessados',
            funnel_model=self.interested_model,
            active=True,
        )
        self.stage = FunnelStage.objects.create(code='novo-dashboard', name='Novo', active=True, order=1)
        self.origin = OpportunityOrigin.objects.create(code='whatsapp-dashboard', name='WhatsApp', active=True)
        self.course = Course.objects.create(name='Gamebot', value=Decimal('3690.00'), kit_quantity=1, active=True)
        self.room = Room.objects.create(name='Sala Comercial', capacity=2, active=True)

    def _opportunity(self, *, title, owner, next_follow_up_date, updated_at=None):
        opportunity = CommercialOpportunity.objects.create(
            title=title,
            commercial_funnel=self.funnel,
            stage=self.stage,
            origin=self.origin,
            contact_name='Responsável',
            contact_phone='21999990000',
            owner=owner,
            next_follow_up_date=next_follow_up_date,
            active=True,
        )
        if updated_at:
            CommercialOpportunity.objects.filter(pk=opportunity.pk).update(updated_at=updated_at)
            opportunity.refresh_from_db()
        return opportunity

    def test_operational_home_redirects_commercial_operator_to_dashboard(self):
        self.client.force_login(self.user)

        response = self.client.get(reverse('operational_home'))

        self.assertRedirects(response, reverse('commercial_dashboard'))

    def test_commercial_dashboard_is_scoped_to_logged_operator(self):
        today = timezone.localdate()
        self._opportunity(title='Lead hoje', owner=self.user, next_follow_up_date=today)
        self._opportunity(title='Lead amanhã', owner=self.user, next_follow_up_date=today + timedelta(days=1))
        self._opportunity(
            title='Lead crítico',
            owner=self.user,
            next_follow_up_date=today - timedelta(days=1),
            updated_at=timezone.now() - timedelta(days=4),
        )
        self._opportunity(title='Lead de outro atendente', owner=self.other_user, next_follow_up_date=today)
        self.client.force_login(self.user)

        response = self.client.get(reverse('commercial_dashboard'))

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context['follow_up_today_count'], 1)
        self.assertEqual(response.context['follow_up_tomorrow_count'], 1)
        self.assertEqual(response.context['overdue_count'], 1)
        self.assertEqual(response.context['critical_count'], 1)
        self.assertEqual(response.context['opportunity_funnel_groups'][0]['funnel'], self.funnel)
        self.assertContains(response, 'Lead crítico')
        self.assertNotContains(response, 'Lead de outro atendente')

    def test_commercial_operator_menu_includes_lesson_agenda(self):
        self.client.force_login(self.user)

        response = self.client.get(reverse('commercial_dashboard'))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, reverse('commercial_follow_up_agenda'))
        self.assertContains(response, 'Agenda de Follow-Ups')
        self.assertContains(response, reverse('commercial_lesson_agenda'))
        self.assertContains(response, 'Agenda de Aulas')

    def test_commercial_follow_up_agenda_groups_week_and_is_scoped(self):
        today = timezone.localdate()
        week_start = today - timedelta(days=today.weekday())
        monday = week_start
        friday = week_start + timedelta(days=4)
        self._opportunity(title='Lead segunda', owner=self.user, next_follow_up_date=monday)
        self._opportunity(title='Lead sexta', owner=self.user, next_follow_up_date=friday)
        self._opportunity(title='Lead de outro atendente', owner=self.other_user, next_follow_up_date=monday)
        self.client.force_login(self.user)

        response = self.client.get(f"{reverse('commercial_follow_up_agenda')}?semana={week_start.isoformat()}")

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Agenda de Follow-Ups')
        self.assertContains(response, 'Lead segunda')
        self.assertContains(response, 'Lead sexta')
        self.assertNotContains(response, 'Lead de outro atendente')
        self.assertEqual(response.context['week_start'], week_start)
        self.assertEqual(response.context['week_end'], week_start + timedelta(days=6))
        self.assertEqual(response.context['opportunity_count'], 2)
        self.assertContains(response, f"semana={(week_start - timedelta(days=7)).isoformat()}")
        self.assertContains(response, f"semana={(week_start + timedelta(days=7)).isoformat()}")

    def test_commercial_operator_can_open_read_only_lesson_agenda(self):
        today = timezone.localdate()
        student = PedagogicalStudent.objects.create(
            name='Aluno Agenda',
            responsible_name='Responsável Agenda',
        )
        Lesson.objects.create(
            lesson_type=Lesson.TYPE_REGULAR,
            student=student,
            course=self.course,
            room=self.room,
            date=today,
            start_time=time(9, 0),
            end_time=time(11, 0),
            status=Lesson.STATUS_NOT_GIVEN,
            source=Lesson.SOURCE_SPONTE,
            external_id='agenda-regular',
        )
        own_opportunity = self._opportunity(
            title='Lead aula própria',
            owner=self.user,
            next_follow_up_date=today,
        )
        other_opportunity = self._opportunity(
            title='Lead aula outro',
            owner=self.other_user,
            next_follow_up_date=today,
        )
        Lesson.objects.create(
            lesson_type=Lesson.TYPE_TRIAL,
            trial_kind=Lesson.TRIAL_KIND_EXPERIMENTAL,
            commercial_opportunity=own_opportunity,
            student_name_snapshot='Criança Agenda',
            responsible_name_snapshot='Responsável Agenda',
            course=self.course,
            room=self.room,
            date=today,
            start_time=time(15, 0),
            end_time=time(17, 0),
            status=Lesson.STATUS_NOT_GIVEN,
        )
        Lesson.objects.create(
            lesson_type=Lesson.TYPE_TRIAL,
            trial_kind=Lesson.TRIAL_KIND_PLAY,
            commercial_opportunity=other_opportunity,
            student_name_snapshot='Criança Outro Atendimento',
            responsible_name_snapshot='Responsável Outro',
            room=self.room,
            date=today,
            start_time=time(17, 0),
            end_time=time(18, 0),
            status=Lesson.STATUS_NOT_GIVEN,
        )
        self.client.force_login(self.user)

        response = self.client.get(f"{reverse('commercial_lesson_agenda')}?periodo=semana&data={today.isoformat()}")

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Agenda Comercial')
        self.assertContains(response, 'Aluno Agenda')
        self.assertContains(response, 'Criança Agenda')
        self.assertContains(response, 'Abrir oportunidade')
        self.assertContains(response, 'Oportunidade de outro atendente')
        self.assertContains(response, 'Sincronizar Sponte')
        self.assertNotContains(response, 'Preencher feedback')

    def test_commercial_operator_can_sync_sponte_schedule_from_lesson_agenda(self):
        today = timezone.localdate()
        self.client.force_login(self.user)

        with patch('checklists.pedagogical_views.sync_sponte_free_class_schedule') as sync_mock:
            sync_mock.return_value = SponteScheduleSyncResult(
                created=1,
                updated=2,
                unchanged=3,
                cancelled=1,
                students_synced=4,
            )

            response = self.client.post(
                reverse('commercial_lessons_sync_sponte'),
                {'data': today.isoformat(), 'periodo': 'semana'},
                follow=True,
            )

        expected_redirect = f"{reverse('commercial_lesson_agenda')}?data={today.isoformat()}&periodo=semana"
        self.assertEqual(response.redirect_chain[-1][0], expected_redirect)
        sync_mock.assert_called_once()
        self.assertContains(response, 'Agenda Sponte sincronizada')

    def test_commercial_funnel_board_groups_scoped_opportunities_by_stage(self):
        today = timezone.localdate()
        second_stage = FunnelStage.objects.create(code='negociando-board', name='Negociando', active=True, order=2)
        self._opportunity(title='Lead contato', owner=self.user, next_follow_up_date=today)
        self._opportunity(title='Lead negociando', owner=self.user, next_follow_up_date=today, updated_at=timezone.now())
        CommercialOpportunity.objects.filter(title='Lead negociando').update(stage=second_stage)
        self._opportunity(title='Lead de outro atendente', owner=self.other_user, next_follow_up_date=today)
        self.client.force_login(self.user)

        response = self.client.get(f"{reverse('commercial_funnel_board')}?funil={self.funnel.id}")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context['selected_funnel'], self.funnel)
        self.assertContains(response, 'Lead contato')
        self.assertContains(response, 'Lead negociando')
        self.assertContains(response, 'Negociando')
        self.assertNotContains(response, 'Lead de outro atendente')

    def test_operator_can_open_opportunity_create_form(self):
        self.client.force_login(self.user)

        response = self.client.get(reverse('commercial_opportunity_create'))

        tomorrow = timezone.localdate() + timedelta(days=1)
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Criar oportunidade')
        self.assertContains(response, 'Agenda da semana')
        self.assertEqual(response.context['form'].initial['next_follow_up_date'], tomorrow)
        self.assertContains(response, f'value="{tomorrow.isoformat()}"')

    def _post_opportunity_data(self, **kwargs):
        data = {
            'title': '06-2026-0001',
            'commercial_funnel': str(self.funnel.pk),
            'stage': str(self.stage.pk),
            'origin': str(self.origin.pk),
            'interest': '',
            'value': '',
            'contact_name': 'Responsável Comercial',
            'contact_phone': '21999990000',
            'next_follow_up_date': timezone.localdate().isoformat(),
            'status': CommercialOpportunityForm.STATUS_ACTIVE,
            'notes': '',
            'trial_lesson_week': timezone.localdate().isoformat(),
            'trial_lesson_kind': '',
            'trial_lesson_course': '',
            'trial_lesson_student_name': '',
            'trial_lesson_slot': '',
            'trial_lesson_notes': '',
        }
        data.update(kwargs)
        return data

    def test_create_generates_sequential_code_for_opportunity(self):
        self.client.force_login(self.user)

        response = self.client.post(reverse('commercial_opportunity_create'), self._post_opportunity_data())

        self.assertRedirects(response, reverse('commercial_dashboard'))
        opportunity = CommercialOpportunity.objects.latest('id')
        self.assertRegex(opportunity.title, r'^\d{2}-\d{4}-0001$')

    def test_lost_stage_moves_to_interested_funnel_and_deactivates(self):
        lost_stage = FunnelStage.objects.create(code='5-perdido', name='5 - Perdido', active=True, order=5)
        self.client.force_login(self.user)

        response = self.client.post(reverse('commercial_opportunity_create'), self._post_opportunity_data(
            stage=str(lost_stage.pk),
            next_follow_up_date='',
        ))

        self.assertRedirects(response, reverse('commercial_dashboard'))
        opportunity = CommercialOpportunity.objects.latest('id')
        self.assertEqual(opportunity.commercial_funnel, self.interested_funnel)
        self.assertEqual(opportunity.funnel_type, self.interested_type)
        self.assertFalse(opportunity.active)
        self.assertEqual(opportunity.next_follow_up_date, add_months(timezone.localdate(), 3))

    def test_enrollment_stage_moves_to_post_sale_funnel(self):
        enrollment_stage = FunnelStage.objects.create(code='5-matricula', name='5 - Matrícula', active=True, order=5)
        opportunity = self._opportunity(
            title='Lead matricula',
            owner=self.user,
            next_follow_up_date=timezone.localdate(),
        )
        self.client.force_login(self.user)

        response = self.client.post(reverse('commercial_opportunity_edit', args=[opportunity.pk]), self._post_opportunity_data(
            commercial_funnel=str(self.funnel.pk),
            stage=str(enrollment_stage.pk),
        ))

        self.assertRedirects(response, reverse('commercial_dashboard'))
        opportunity.refresh_from_db()
        self.assertEqual(opportunity.commercial_funnel.name, 'Pós-Venda')
        self.assertEqual(opportunity.funnel_type.code, 'posvenda')
        self.assertEqual(opportunity.stage, enrollment_stage)
        self.assertTrue(opportunity.active)

    def test_scheduling_trial_lesson_moves_to_trial_stage_and_allows_undefined_course(self):
        trial_stage = FunnelStage.objects.create(
            code='3-aula-experimental',
            name='3 - Aula Experimental',
            active=True,
            order=3,
        )
        target = timezone.localdate() + timedelta(days=((7 - timezone.localdate().weekday()) % 7 or 7))
        week_start = target - timedelta(days=target.weekday())
        TimeSlot.objects.create(weekday=target.weekday(), start_time=time(9, 0), end_time=time(11, 0), active=True)
        slot_value = f'{target.isoformat()}|09:00|11:00|{self.room.pk}'
        self.client.force_login(self.user)

        response = self.client.post(reverse('commercial_opportunity_create'), self._post_opportunity_data(
            trial_lesson_week=week_start.isoformat(),
            trial_lesson_kind=Lesson.TRIAL_KIND_EXPERIMENTAL,
            trial_lesson_course='',
            trial_lesson_student_name='Aluno Experimental',
            trial_lesson_slot=slot_value,
        ))

        self.assertRedirects(response, reverse('commercial_dashboard'))
        opportunity = CommercialOpportunity.objects.latest('id')
        lesson = Lesson.objects.get(commercial_opportunity=opportunity)
        self.assertEqual(opportunity.stage, trial_stage)
        self.assertIsNone(lesson.course)
        self.assertEqual(lesson.student_name_snapshot, 'Aluno Experimental')
        self.assertEqual(lesson.status, Lesson.STATUS_NOT_GIVEN)

    def test_create_form_lists_slots_blocked_by_selected_course_capacity(self):
        target = timezone.localdate() + timedelta(days=((7 - timezone.localdate().weekday()) % 7 or 7))
        week_start = target - timedelta(days=target.weekday())
        TimeSlot.objects.create(weekday=target.weekday(), start_time=time(9, 0), end_time=time(11, 0), active=True)
        student = PedagogicalStudent.objects.create(name='Aluno Gamebot')
        Lesson.objects.create(
            lesson_type=Lesson.TYPE_REGULAR,
            student=student,
            course=self.course,
            room=self.room,
            date=target,
            start_time=time(9, 0),
            end_time=time(11, 0),
            status=Lesson.STATUS_SCHEDULED,
        )
        self.client.force_login(self.user)

        response = self.client.get(f"{reverse('commercial_opportunity_create')}?semana={week_start.isoformat()}")

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, f'data-blocked-course-id="{self.course.id}"')
        self.assertContains(response, 'data-trial-slot-blocked-reason')
        self.assertContains(response, 'kits insuficientes para Gamebot')
        self.assertNotContains(response, 'Horários indisponíveis para o curso selecionado')

    def test_create_rejects_trial_slot_when_selected_course_has_no_kits(self):
        trial_stage = FunnelStage.objects.create(
            code='3-aula-experimental-kits',
            name='3 - Aula Experimental kits',
            active=True,
            order=3,
        )
        target = timezone.localdate() + timedelta(days=((7 - timezone.localdate().weekday()) % 7 or 7))
        week_start = target - timedelta(days=target.weekday())
        TimeSlot.objects.create(weekday=target.weekday(), start_time=time(9, 0), end_time=time(11, 0), active=True)
        student = PedagogicalStudent.objects.create(name='Aluno Kit Ocupado')
        Lesson.objects.create(
            lesson_type=Lesson.TYPE_REGULAR,
            student=student,
            course=self.course,
            room=self.room,
            date=target,
            start_time=time(9, 0),
            end_time=time(11, 0),
            status=Lesson.STATUS_SCHEDULED,
        )
        slot_value = f'{target.isoformat()}|09:00|11:00|{self.room.pk}'
        self.client.force_login(self.user)

        response = self.client.post(reverse('commercial_opportunity_create'), self._post_opportunity_data(
            stage=str(trial_stage.pk),
            trial_lesson_week=week_start.isoformat(),
            trial_lesson_kind=Lesson.TRIAL_KIND_EXPERIMENTAL,
            trial_lesson_course=str(self.course.pk),
            trial_lesson_slot=slot_value,
        ))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Selecione um horário livre válido.')
        self.assertFalse(Lesson.objects.filter(lesson_type=Lesson.TYPE_TRIAL).exists())
