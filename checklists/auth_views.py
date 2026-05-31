from django.contrib.auth.views import PasswordChangeView
from django.urls import reverse_lazy


class RequiredPasswordChangeView(PasswordChangeView):
    """Troca de senha para qualquer tipo de usuário.

    Se o usuário estiver com senha temporária, a flag must_change_password
    é removida somente depois de uma troca de senha bem-sucedida.
    """

    template_name = 'registration/password_change_form.html'
    success_url = reverse_lazy('password_change_done')

    def form_valid(self, form):
        response = super().form_valid(form)
        profile = getattr(self.request.user, 'userprofile', None)
        if profile and profile.must_change_password:
            profile.must_change_password = False
            profile.save(update_fields=['must_change_password'])
        return response

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        profile = getattr(self.request.user, 'userprofile', None)
        context['forced_password_change'] = bool(profile and profile.must_change_password)
        return context
