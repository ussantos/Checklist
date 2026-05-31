from django.urls import path
from django.contrib.auth import views as auth_views
from . import views

urlpatterns = [
    path('', views.dashboard, name='dashboard'),
    path('checklist/', views.checklist_day, name='checklist_day'),
    path('semana/', views.week_view, name='week_view'),
    path('historico/', views.history, name='history'),
    path('tarefas-modelo/', views.templates_list, name='templates_list'),
    path('metricas/', views.metrics, name='metrics'),
    path('funcionarios/', views.employees_list, name='employees_list'),
    path('funcionarios/novo/', views.employee_create, name='employee_create'),
    path('funcionarios/<int:user_id>/editar/', views.employee_edit, name='employee_edit'),
    path('funcionarios/<int:user_id>/senha/', views.employee_reset_password, name='employee_reset_password'),
    path('senha/alterar/', auth_views.PasswordChangeView.as_view(template_name='registration/password_change_form.html', success_url='/senha/alterada/'), name='password_change'),
    path('senha/alterada/', auth_views.PasswordChangeDoneView.as_view(template_name='registration/password_change_done.html'), name='password_change_done'),
    path('relatorio/mensal.csv', views.monthly_csv, name='monthly_csv'),
    path('relatorio/historico.csv', views.history_csv, name='history_csv'),
    path('ocorrencia/<int:occurrence_id>/atualizar/', views.update_occurrence, name='update_occurrence'),
    path('evidencia/<int:attachment_id>/', views.evidence_attachment_download, name='evidence_attachment_download'),
    path('evidencia-legado/<int:occurrence_id>/', views.legacy_evidence_download, name='legacy_evidence_download'),
]
