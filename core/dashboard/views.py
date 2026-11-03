from django.contrib.auth.mixins import LoginRequiredMixin
from django.views.generic import TemplateView

from core.policies.services.panel import datos_panel, datos_seguimiento
from core.security.models import Dashboard


class DashboardView(LoginRequiredMixin, TemplateView):
    """Panel de inicio: resumen de las cotizaciones de seguros (ver core/policies/services/panel.py)."""
    template_name = 'panel.html'

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['title'] = 'Panel de control'
        context['dashboard'] = Dashboard.objects.first()
        context['panel'] = datos_panel(self.request.GET.get('dias'))
        user = self.request.user
        if user.has_perm('policies.view_poliza') or user.has_perm('policies.view_vehiculo'):
            context['seguimiento'] = datos_seguimiento(self.request.GET.get('dias'))
        return context
