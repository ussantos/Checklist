from django.urls import path
from . import views
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
