from django.urls import path
from . import views
from .auth_views import RequiredPasswordChangeView
from . import user_views
from django.contrib.auth import views as auth_views

urlpatterns = [
    path('', views.dashboard, name='dashboard'),
    path('atividades/', views.activities, name='activities'),
    path('checklist/', views.checklist_day, name='checklist_day'),
    path('semana/', views.week_view, name='week_view'),
    path('historico/', views.history, name='history'),
    path('tarefas-modelo/', views.templates_list, name='templates_list'),
    path('tarefas-modelo/nova/', views.template_create, name='template_create'),
    path('tarefas-modelo/importar/', views.template_import, name='template_import'),
    path('tarefas-modelo/modelo.xlsx', views.template_import_model, name='template_import_model'),
    path('tarefas-modelo/<int:template_id>/editar/', views.template_edit, name='template_edit'),
    path('metricas/', views.metrics, name='metrics'),
    path('tipos-usuario/', user_views.positions_list, name='positions_list'),
    path('tipos-usuario/novo/', user_views.position_create, name='position_create'),
    path('tipos-usuario/<int:position_id>/editar/', user_views.position_edit, name='position_edit'),
    path('ausencias/', user_views.absences_list, name='absences_list'),
    path('ausencias/nova/', user_views.absence_create, name='absence_create'),
    path('ausencias/<int:absence_id>/editar/', user_views.absence_edit, name='absence_edit'),
    path('usuarios/', user_views.users_list, name='employees_list'),
    path('usuarios/novo/', user_views.user_create, name='employee_create'),
    path('usuarios/<int:user_id>/editar/', user_views.user_edit, name='employee_edit'),
    path('usuarios/<int:user_id>/ausencia/', user_views.absence_create, name='employee_absence_create'),
    path('usuarios/<int:user_id>/senha/', user_views.user_reset_password, name='employee_reset_password'),
    path('senha/alterar/', RequiredPasswordChangeView.as_view(), name='password_change'),
    path('senha/alterada/', auth_views.PasswordChangeDoneView.as_view(template_name='registration/password_change_done.html'), name='password_change_done'),
    path('relatorio/mensal.csv', views.monthly_csv, name='monthly_csv'),
    path('relatorio/historico.csv', views.history_csv, name='history_csv'),
    path('ocorrencia/<int:occurrence_id>/atualizar/', views.update_occurrence, name='update_occurrence'),
    path('evidencia/<int:attachment_id>/', views.evidence_attachment_download, name='evidence_attachment_download'),
    path('evidencia-legado/<int:occurrence_id>/', views.legacy_evidence_download, name='legacy_evidence_download'),
]
