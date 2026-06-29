from datetime import date

from django.contrib import messages
from django.contrib.auth.decorators import user_passes_test
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.http import require_POST

from .audit import changed_values, log_activity, snapshot_instance
from .forms import (
    CourseForm, LessonForm, PedagogicalStudentForm, RoomForm, SchoolHolidayForm,
    TimeSlotForm,
)
from .models import Course, Lesson, PedagogicalStudent, Room, SchoolHoliday, TimeSlot
from .services import is_admin_user


COURSE_AUDIT_FIELDS = ['name', 'description', 'value', 'kit_quantity', 'max_students_per_slot', 'active']
ROOM_AUDIT_FIELDS = ['name', 'capacity', 'active']
TIME_SLOT_AUDIT_FIELDS = ['weekday', 'start_time', 'end_time', 'active']
HOLIDAY_AUDIT_FIELDS = ['description', 'kind', 'start_date', 'end_date', 'active']
STUDENT_AUDIT_FIELDS = ['name', 'enrollment_number', 'responsible_name', 'whatsapp', 'status', 'source', 'external_id']
LESSON_AUDIT_FIELDS = [
    'lesson_type', 'student', 'student_name_snapshot', 'responsible_name_snapshot',
    'whatsapp_snapshot', 'course', 'room', 'date', 'start_time', 'end_time',
    'status', 'notes', 'created_by',
]


def _admin_check(user):
    return user.is_authenticated and is_admin_user(user)


def _parse_date(value):
    if not value:
        return timezone.localdate()
    try:
        return date.fromisoformat(value)
    except ValueError:
        return timezone.localdate()


def _active_filter(queryset, status, *, active_label='ativos', inactive_label='inativos', all_label='todos'):
    if status == inactive_label:
        return queryset.filter(active=False), status
    if status == all_label:
        return queryset, status
    return queryset.filter(active=True), active_label


def _student_status_filter(queryset, status):
    if status == 'inativos':
        return queryset.filter(status=PedagogicalStudent.STATUS_INACTIVE), status
    if status == 'todos':
        return queryset, status
    return queryset.filter(status=PedagogicalStudent.STATUS_ACTIVE), 'ativos'


def _log_change(*, request, obj, action, audit_fields, previous_values_full=None, details=''):
    previous_values = {}
    new_values = snapshot_instance(obj, audit_fields)
    if previous_values_full is not None:
        previous_values, new_values = changed_values(previous_values_full, new_values)
    log_activity(
        actor=request.user,
        obj=obj,
        action=action,
        object_label=str(obj),
        details=details,
        previous_values=previous_values,
        new_values=new_values,
    )


@user_passes_test(_admin_check)
def courses_list(request):
    status = request.GET.get('status', 'ativos')
    courses, status = _active_filter(Course.objects.all().order_by('-active', 'name'), status)
    return render(request, 'checklists/courses_list.html', {
        'courses': courses,
        'status': status,
        'is_admin': True,
    })


@user_passes_test(_admin_check)
def course_create(request):
    if request.method == 'POST':
        form = CourseForm(request.POST)
        if form.is_valid():
            course = form.save()
            _log_change(
                request=request,
                obj=course,
                action='Curso criado',
                audit_fields=COURSE_AUDIT_FIELDS,
                details=f'Curso: {course.name}; valor: {course.value}; kits: {course.kit_quantity}; ativo: {course.active}',
            )
            messages.success(request, 'Curso criado.')
            return redirect('pedagogical_courses')
    else:
        form = CourseForm()

    return render(request, 'checklists/course_form.html', {
        'form': form,
        'title': 'Inserir curso',
        'submit_label': 'Inserir curso',
        'is_admin': True,
    })


@user_passes_test(_admin_check)
def course_edit(request, course_id):
    course = get_object_or_404(Course, pk=course_id)
    previous_active = course.active
    previous_values_full = snapshot_instance(course, COURSE_AUDIT_FIELDS)
    if request.method == 'POST':
        form = CourseForm(request.POST, instance=course)
        if form.is_valid():
            course = form.save()
            action = 'Curso atualizado'
            if previous_active and not course.active:
                action = 'Curso desativado'
            elif not previous_active and course.active:
                action = 'Curso ativado'
            _log_change(
                request=request,
                obj=course,
                action=action,
                audit_fields=COURSE_AUDIT_FIELDS,
                previous_values_full=previous_values_full,
                details=f'Curso: {course.name}; valor: {course.value}; kits: {course.kit_quantity}; ativo: {course.active}',
            )
            messages.success(request, 'Curso atualizado.')
            return redirect('pedagogical_courses')
    else:
        form = CourseForm(instance=course)

    return render(request, 'checklists/course_form.html', {
        'form': form,
        'title': f'Editar curso - {course.name}',
        'submit_label': 'Salvar alterações',
        'course': course,
        'is_admin': True,
    })


@require_POST
@user_passes_test(_admin_check)
def course_toggle(request, course_id):
    course = get_object_or_404(Course, pk=course_id)
    previous_values_full = snapshot_instance(course, COURSE_AUDIT_FIELDS)
    course.active = not course.active
    course.save(update_fields=['active', 'updated_at'])
    _log_change(
        request=request,
        obj=course,
        action='Curso ativado' if course.active else 'Curso desativado',
        audit_fields=COURSE_AUDIT_FIELDS,
        previous_values_full=previous_values_full,
        details=f'Curso: {course.name}; valor: {course.value}; kits: {course.kit_quantity}; ativo: {course.active}',
    )
    messages.success(request, f'Curso {"ativado" if course.active else "desativado"}.')
    return redirect('pedagogical_courses')


@user_passes_test(_admin_check)
def rooms_list(request):
    status = request.GET.get('status', 'ativas')
    rooms, status = _active_filter(
        Room.objects.all().order_by('-active', 'name'),
        status,
        active_label='ativas',
        inactive_label='inativas',
        all_label='todas',
    )
    return render(request, 'checklists/rooms_list.html', {
        'rooms': rooms,
        'status': status,
        'is_admin': True,
    })


@user_passes_test(_admin_check)
def room_create(request):
    if request.method == 'POST':
        form = RoomForm(request.POST)
        if form.is_valid():
            room = form.save()
            _log_change(
                request=request,
                obj=room,
                action='Sala criada',
                audit_fields=ROOM_AUDIT_FIELDS,
                details=f'Sala: {room.name}; capacidade: {room.capacity}; ativa: {room.active}',
            )
            messages.success(request, 'Sala criada.')
            return redirect('pedagogical_rooms')
    else:
        form = RoomForm()
    return render(request, 'checklists/room_form.html', {'form': form, 'title': 'Inserir sala', 'submit_label': 'Inserir sala', 'is_admin': True})


@user_passes_test(_admin_check)
def room_edit(request, room_id):
    room = get_object_or_404(Room, pk=room_id)
    previous_active = room.active
    previous_values_full = snapshot_instance(room, ROOM_AUDIT_FIELDS)
    if request.method == 'POST':
        form = RoomForm(request.POST, instance=room)
        if form.is_valid():
            room = form.save()
            action = 'Sala atualizada'
            if previous_active and not room.active:
                action = 'Sala desativada'
            elif not previous_active and room.active:
                action = 'Sala ativada'
            _log_change(
                request=request,
                obj=room,
                action=action,
                audit_fields=ROOM_AUDIT_FIELDS,
                previous_values_full=previous_values_full,
                details=f'Sala: {room.name}; capacidade: {room.capacity}; ativa: {room.active}',
            )
            messages.success(request, 'Sala atualizada.')
            return redirect('pedagogical_rooms')
    else:
        form = RoomForm(instance=room)
    return render(request, 'checklists/room_form.html', {'form': form, 'title': f'Editar sala - {room.name}', 'submit_label': 'Salvar alterações', 'room': room, 'is_admin': True})


@require_POST
@user_passes_test(_admin_check)
def room_toggle(request, room_id):
    room = get_object_or_404(Room, pk=room_id)
    previous_values_full = snapshot_instance(room, ROOM_AUDIT_FIELDS)
    room.active = not room.active
    room.save(update_fields=['active', 'updated_at'])
    _log_change(
        request=request,
        obj=room,
        action='Sala ativada' if room.active else 'Sala desativada',
        audit_fields=ROOM_AUDIT_FIELDS,
        previous_values_full=previous_values_full,
        details=f'Sala: {room.name}; capacidade: {room.capacity}; ativa: {room.active}',
    )
    messages.success(request, f'Sala {"ativada" if room.active else "desativada"}.')
    return redirect('pedagogical_rooms')


@user_passes_test(_admin_check)
def time_slots_list(request):
    status = request.GET.get('status', 'ativos')
    slots, status = _active_filter(TimeSlot.objects.all().order_by('weekday', 'start_time'), status)
    return render(request, 'checklists/time_slots_list.html', {
        'slots': slots,
        'status': status,
        'is_admin': True,
    })


@user_passes_test(_admin_check)
def time_slot_create(request):
    if request.method == 'POST':
        form = TimeSlotForm(request.POST)
        if form.is_valid():
            slot = form.save()
            _log_change(request=request, obj=slot, action='Horário criado', audit_fields=TIME_SLOT_AUDIT_FIELDS, details=f'Horário: {slot}; ativo: {slot.active}')
            messages.success(request, 'Horário criado.')
            return redirect('pedagogical_time_slots')
    else:
        form = TimeSlotForm()
    return render(request, 'checklists/time_slot_form.html', {'form': form, 'title': 'Inserir horário', 'submit_label': 'Inserir horário', 'is_admin': True})


@user_passes_test(_admin_check)
def time_slot_edit(request, slot_id):
    slot = get_object_or_404(TimeSlot, pk=slot_id)
    previous_active = slot.active
    previous_values_full = snapshot_instance(slot, TIME_SLOT_AUDIT_FIELDS)
    if request.method == 'POST':
        form = TimeSlotForm(request.POST, instance=slot)
        if form.is_valid():
            slot = form.save()
            action = 'Horário atualizado'
            if previous_active and not slot.active:
                action = 'Horário desativado'
            elif not previous_active and slot.active:
                action = 'Horário ativado'
            _log_change(request=request, obj=slot, action=action, audit_fields=TIME_SLOT_AUDIT_FIELDS, previous_values_full=previous_values_full, details=f'Horário: {slot}; ativo: {slot.active}')
            messages.success(request, 'Horário atualizado.')
            return redirect('pedagogical_time_slots')
    else:
        form = TimeSlotForm(instance=slot)
    return render(request, 'checklists/time_slot_form.html', {'form': form, 'title': f'Editar horário - {slot}', 'submit_label': 'Salvar alterações', 'slot': slot, 'is_admin': True})


@require_POST
@user_passes_test(_admin_check)
def time_slot_toggle(request, slot_id):
    slot = get_object_or_404(TimeSlot, pk=slot_id)
    previous_values_full = snapshot_instance(slot, TIME_SLOT_AUDIT_FIELDS)
    slot.active = not slot.active
    slot.save(update_fields=['active', 'updated_at'])
    _log_change(request=request, obj=slot, action='Horário ativado' if slot.active else 'Horário desativado', audit_fields=TIME_SLOT_AUDIT_FIELDS, previous_values_full=previous_values_full, details=f'Horário: {slot}; ativo: {slot.active}')
    messages.success(request, f'Horário {"ativado" if slot.active else "desativado"}.')
    return redirect('pedagogical_time_slots')


@user_passes_test(_admin_check)
def holidays_list(request):
    status = request.GET.get('status', 'ativos')
    holidays, status = _active_filter(SchoolHoliday.objects.all().order_by('start_date'), status)
    return render(request, 'checklists/holidays_list.html', {
        'holidays': holidays,
        'status': status,
        'is_admin': True,
    })


@user_passes_test(_admin_check)
def holiday_create(request):
    if request.method == 'POST':
        form = SchoolHolidayForm(request.POST)
        if form.is_valid():
            holiday = form.save()
            _log_change(request=request, obj=holiday, action='Feriado/Recesso criado', audit_fields=HOLIDAY_AUDIT_FIELDS, details=f'Feriado/Recesso: {holiday}; ativo: {holiday.active}')
            messages.success(request, 'Feriado/Recesso criado.')
            return redirect('pedagogical_holidays')
    else:
        form = SchoolHolidayForm()
    return render(request, 'checklists/holiday_form.html', {'form': form, 'title': 'Inserir feriado/recesso', 'submit_label': 'Inserir', 'is_admin': True})


@user_passes_test(_admin_check)
def holiday_edit(request, holiday_id):
    holiday = get_object_or_404(SchoolHoliday, pk=holiday_id)
    previous_active = holiday.active
    previous_values_full = snapshot_instance(holiday, HOLIDAY_AUDIT_FIELDS)
    if request.method == 'POST':
        form = SchoolHolidayForm(request.POST, instance=holiday)
        if form.is_valid():
            holiday = form.save()
            action = 'Feriado/Recesso atualizado'
            if previous_active and not holiday.active:
                action = 'Feriado/Recesso desativado'
            elif not previous_active and holiday.active:
                action = 'Feriado/Recesso ativado'
            _log_change(request=request, obj=holiday, action=action, audit_fields=HOLIDAY_AUDIT_FIELDS, previous_values_full=previous_values_full, details=f'Feriado/Recesso: {holiday}; ativo: {holiday.active}')
            messages.success(request, 'Feriado/Recesso atualizado.')
            return redirect('pedagogical_holidays')
    else:
        form = SchoolHolidayForm(instance=holiday)
    return render(request, 'checklists/holiday_form.html', {'form': form, 'title': f'Editar feriado/recesso - {holiday.description}', 'submit_label': 'Salvar alterações', 'holiday': holiday, 'is_admin': True})


@require_POST
@user_passes_test(_admin_check)
def holiday_toggle(request, holiday_id):
    holiday = get_object_or_404(SchoolHoliday, pk=holiday_id)
    previous_values_full = snapshot_instance(holiday, HOLIDAY_AUDIT_FIELDS)
    holiday.active = not holiday.active
    holiday.save(update_fields=['active', 'updated_at'])
    _log_change(request=request, obj=holiday, action='Feriado/Recesso ativado' if holiday.active else 'Feriado/Recesso desativado', audit_fields=HOLIDAY_AUDIT_FIELDS, previous_values_full=previous_values_full, details=f'Feriado/Recesso: {holiday}; ativo: {holiday.active}')
    messages.success(request, f'Feriado/Recesso {"ativado" if holiday.active else "desativado"}.')
    return redirect('pedagogical_holidays')


@user_passes_test(_admin_check)
def students_list(request):
    status = request.GET.get('status', 'ativos')
    students, status = _student_status_filter(PedagogicalStudent.objects.all().order_by('name'), status)
    return render(request, 'checklists/students_list.html', {
        'students': students,
        'status': status,
        'is_admin': True,
    })


@user_passes_test(_admin_check)
def student_create(request):
    if request.method == 'POST':
        form = PedagogicalStudentForm(request.POST)
        if form.is_valid():
            student = form.save()
            _log_change(request=request, obj=student, action='Aluno pedagógico criado', audit_fields=STUDENT_AUDIT_FIELDS, details=f'Aluno: {student.name}; status: {student.status}')
            messages.success(request, 'Aluno criado.')
            return redirect('pedagogical_students')
    else:
        form = PedagogicalStudentForm()
    return render(request, 'checklists/student_form.html', {'form': form, 'title': 'Inserir aluno', 'submit_label': 'Inserir aluno', 'is_admin': True})


@user_passes_test(_admin_check)
def student_edit(request, student_id):
    student = get_object_or_404(PedagogicalStudent, pk=student_id)
    previous_status = student.status
    previous_values_full = snapshot_instance(student, STUDENT_AUDIT_FIELDS)
    if request.method == 'POST':
        form = PedagogicalStudentForm(request.POST, instance=student)
        if form.is_valid():
            student = form.save()
            action = 'Aluno pedagógico atualizado'
            if previous_status != student.status:
                action = 'Aluno pedagógico ativado' if student.active else 'Aluno pedagógico desativado'
            _log_change(request=request, obj=student, action=action, audit_fields=STUDENT_AUDIT_FIELDS, previous_values_full=previous_values_full, details=f'Aluno: {student.name}; status: {student.status}')
            messages.success(request, 'Aluno atualizado.')
            return redirect('pedagogical_students')
    else:
        form = PedagogicalStudentForm(instance=student)
    return render(request, 'checklists/student_form.html', {'form': form, 'title': f'Editar aluno - {student.name}', 'submit_label': 'Salvar alterações', 'student': student, 'is_admin': True})


@require_POST
@user_passes_test(_admin_check)
def student_toggle(request, student_id):
    student = get_object_or_404(PedagogicalStudent, pk=student_id)
    previous_values_full = snapshot_instance(student, STUDENT_AUDIT_FIELDS)
    student.status = PedagogicalStudent.STATUS_INACTIVE if student.active else PedagogicalStudent.STATUS_ACTIVE
    student.save(update_fields=['status', 'updated_at'])
    _log_change(request=request, obj=student, action='Aluno pedagógico ativado' if student.active else 'Aluno pedagógico desativado', audit_fields=STUDENT_AUDIT_FIELDS, previous_values_full=previous_values_full, details=f'Aluno: {student.name}; status: {student.status}')
    messages.success(request, f'Aluno {"ativado" if student.active else "desativado"}.')
    return redirect('pedagogical_students')


def _lesson_queryset():
    return Lesson.objects.select_related('student', 'course', 'room', 'created_by').order_by('date', 'start_time', 'room__name')


def _apply_lesson_filters(request, lessons):
    course_id = request.GET.get('curso', '')
    room_id = request.GET.get('sala', '')
    lesson_type = request.GET.get('tipo', '')
    status = request.GET.get('status', '')
    if course_id.isdigit():
        lessons = lessons.filter(course_id=course_id)
    else:
        course_id = ''
    if room_id.isdigit():
        lessons = lessons.filter(room_id=room_id)
    else:
        room_id = ''
    if lesson_type in dict(Lesson.TYPE_CHOICES):
        lessons = lessons.filter(lesson_type=lesson_type)
    else:
        lesson_type = ''
    if status in dict(Lesson.STATUS_CHOICES):
        lessons = lessons.filter(status=status)
    else:
        status = ''
    return lessons, {
        'course_id': course_id,
        'room_id': room_id,
        'lesson_type': lesson_type,
        'status': status,
    }


@user_passes_test(_admin_check)
def lesson_agenda(request):
    target_date = _parse_date(request.GET.get('data'))
    lessons = _lesson_queryset().filter(date=target_date)
    lessons, selected = _apply_lesson_filters(request, lessons)
    lessons = list(lessons)
    for lesson in lessons:
        lesson.assistant_warning = lesson.assistant_warning_message()
    return render(request, 'checklists/lesson_agenda.html', {
        'title': 'Agenda de Aulas',
        'lessons': lessons,
        'target_date': target_date,
        'selected': selected,
        'courses': Course.objects.order_by('name'),
        'rooms': Room.objects.order_by('name'),
        'lesson_type_choices': Lesson.TYPE_CHOICES,
        'status_choices': Lesson.STATUS_CHOICES,
        'trial_only': False,
        'is_admin': True,
    })


@user_passes_test(_admin_check)
def trial_lessons(request):
    target_date = _parse_date(request.GET.get('data'))
    lessons = _lesson_queryset().filter(date=target_date, lesson_type=Lesson.TYPE_TRIAL)
    lessons, selected = _apply_lesson_filters(request, lessons)
    lessons = list(lessons)
    for lesson in lessons:
        lesson.assistant_warning = lesson.assistant_warning_message()
    return render(request, 'checklists/lesson_agenda.html', {
        'title': 'Aulas Experimentais',
        'lessons': lessons,
        'target_date': target_date,
        'selected': selected,
        'courses': Course.objects.order_by('name'),
        'rooms': Room.objects.order_by('name'),
        'lesson_type_choices': Lesson.TYPE_CHOICES,
        'status_choices': Lesson.STATUS_CHOICES,
        'trial_only': True,
        'is_admin': True,
    })


@user_passes_test(_admin_check)
def lesson_create(request):
    initial = {}
    if request.GET.get('tipo') == Lesson.TYPE_TRIAL:
        initial['lesson_type'] = Lesson.TYPE_TRIAL
    if request.method == 'POST':
        form = LessonForm(request.POST)
        if form.is_valid():
            lesson = form.save(commit=False)
            lesson.created_by = request.user
            lesson.save()
            _log_change(
                request=request,
                obj=lesson,
                action='Aula pedagógica criada',
                audit_fields=LESSON_AUDIT_FIELDS,
                details=f'Aula: {lesson}; status: {lesson.status}',
            )
            warning = lesson.assistant_warning_message()
            if warning:
                messages.warning(request, warning)
            messages.success(request, 'Aula agendada.')
            return redirect(f'{reverse("pedagogical_class_schedule")}?data={lesson.date.isoformat()}')
    else:
        form = LessonForm(initial=initial)
    return render(request, 'checklists/lesson_form.html', {
        'form': form,
        'title': 'Agendar aula',
        'submit_label': 'Salvar aula',
        'lesson': None,
        'is_admin': True,
    })


@user_passes_test(_admin_check)
def lesson_edit(request, lesson_id):
    lesson = get_object_or_404(_lesson_queryset(), pk=lesson_id)
    previous_values_full = snapshot_instance(lesson, LESSON_AUDIT_FIELDS)
    if request.method == 'POST':
        form = LessonForm(request.POST, instance=lesson)
        if form.is_valid():
            lesson = form.save()
            _log_change(
                request=request,
                obj=lesson,
                action='Aula pedagógica atualizada',
                audit_fields=LESSON_AUDIT_FIELDS,
                previous_values_full=previous_values_full,
                details=f'Aula: {lesson}; status: {lesson.status}',
            )
            warning = lesson.assistant_warning_message()
            if warning:
                messages.warning(request, warning)
            messages.success(request, 'Aula atualizada.')
            return redirect(f'{reverse("pedagogical_class_schedule")}?data={lesson.date.isoformat()}')
    else:
        form = LessonForm(instance=lesson)
    return render(request, 'checklists/lesson_form.html', {
        'form': form,
        'title': f'Editar aula - {lesson.student_name_snapshot}',
        'submit_label': 'Salvar alterações',
        'lesson': lesson,
        'is_admin': True,
    })
