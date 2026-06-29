from django.urls import path
from . import views
from . import commercial_views
from .auth_views import RequiredPasswordChangeView
from . import user_views
from django.contrib.auth import views as auth_views

urlpatterns = [
    path('', views.dashboard, name='dashboard'),
    path('operacional/', views.operational_home, name='operational_home'),
    path('historico/', views.history, name='history'),
    path('auditoria/', views.admin_activity_history, name='admin_activity_history'),
    path('auditoria.csv', views.admin_activity_history_csv, name='admin_activity_history_csv'),
    path('backups/', views.backups, name='backups'),
    path('gestao-comercial/tipos-de-funis/', commercial_views.funnel_types_list, name='commercial_funnel_types'),
    path('gestao-comercial/tipos-de-funis/novo/', commercial_views.funnel_type_create, name='funnel_type_create'),
    path('gestao-comercial/tipos-de-funis/<int:funnel_type_id>/editar/', commercial_views.funnel_type_edit, name='funnel_type_edit'),
    path('gestao-comercial/tipos-de-funis/<int:funnel_type_id>/alternar-status/', commercial_views.funnel_type_toggle, name='funnel_type_toggle'),
    path('gestao-comercial/tipos-de-funis/<int:funnel_type_id>/excluir/', commercial_views.funnel_type_delete, name='funnel_type_delete'),
    path('gestao-comercial/funis/etapas/', views.commercial_funnel_stages, name='commercial_funnel_stages'),
    path('gestao-comercial/modelos-de-funis/', views.commercial_funnel_models, name='commercial_funnel_models'),
    path('gestao-comercial/indicadores/', views.commercial_indicators, name='commercial_indicators'),
    path('gestao-comercial/metas/', views.commercial_goals, name='commercial_goals'),
    path('gestao-pedagogica/agenda-de-aulas/', views.pedagogical_class_schedule, name='pedagogical_class_schedule'),
    path('gestao-pedagogica/modelos-feedback-aula/', views.pedagogical_feedback_models, name='pedagogical_feedback_models'),
    path('tipos-usuario/', user_views.positions_list, name='positions_list'),
    path('tipos-usuario/novo/', user_views.position_create, name='position_create'),
    path('tipos-usuario/<int:position_id>/editar/', user_views.position_edit, name='position_edit'),
    path('usuarios/', user_views.users_list, name='employees_list'),
    path('usuarios/novo/', user_views.user_create, name='employee_create'),
    path('usuarios/<int:user_id>/editar/', user_views.user_edit, name='employee_edit'),
    path('usuarios/<int:user_id>/senha/', user_views.user_reset_password, name='employee_reset_password'),
    path('senha/alterar/', RequiredPasswordChangeView.as_view(), name='password_change'),
    path('senha/alterada/', auth_views.PasswordChangeDoneView.as_view(template_name='registration/password_change_done.html'), name='password_change_done'),
    path('relatorio/historico.csv', views.history_csv, name='history_csv'),
    path('evidencia/<int:attachment_id>/', views.evidence_attachment_download, name='evidence_attachment_download'),
    path('evidencia-legado/<int:occurrence_id>/', views.legacy_evidence_download, name='legacy_evidence_download'),
]
