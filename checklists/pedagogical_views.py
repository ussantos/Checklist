from django.contrib import messages
from django.contrib.auth.decorators import user_passes_test
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST

from .audit import changed_values, log_activity, snapshot_instance
from .forms import CourseForm
from .models import Course
from .services import is_admin_user


COURSE_AUDIT_FIELDS = ['name', 'value', 'active']


def _admin_check(user):
    return user.is_authenticated and is_admin_user(user)


@user_passes_test(_admin_check)
def courses_list(request):
    status = request.GET.get('status', 'ativos')
    courses = Course.objects.all().order_by('-active', 'name')
    if status == 'inativos':
        courses = courses.filter(active=False)
    elif status != 'todos':
        status = 'ativos'
        courses = courses.filter(active=True)

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
            log_activity(
                actor=request.user,
                obj=course,
                action='Curso criado',
                object_label=course.name,
                details=f'Curso: {course.name}; valor: {course.value}; ativo: {course.active}',
                new_values=snapshot_instance(course, COURSE_AUDIT_FIELDS),
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
            previous_values, new_values = changed_values(
                previous_values_full,
                snapshot_instance(course, COURSE_AUDIT_FIELDS),
            )
            if previous_active and not course.active:
                action = 'Curso desativado'
            elif not previous_active and course.active:
                action = 'Curso ativado'
            else:
                action = 'Curso atualizado'
            log_activity(
                actor=request.user,
                obj=course,
                action=action,
                object_label=course.name,
                details=f'Curso: {course.name}; valor: {course.value}; ativo: {course.active}',
                previous_values=previous_values,
                new_values=new_values,
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
    previous_values, new_values = changed_values(
        previous_values_full,
        snapshot_instance(course, COURSE_AUDIT_FIELDS),
    )
    action = 'Curso ativado' if course.active else 'Curso desativado'
    log_activity(
        actor=request.user,
        obj=course,
        action=action,
        object_label=course.name,
        details=f'Curso: {course.name}; valor: {course.value}; ativo: {course.active}',
        previous_values=previous_values,
        new_values=new_values,
    )
    messages.success(request, f'Curso {"ativado" if course.active else "desativado"}.')
    return redirect('pedagogical_courses')
