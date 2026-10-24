import json

from django.http import HttpResponse
from django.urls import reverse, reverse_lazy
from django.views.generic import TemplateView

from core.policies.models import ValorExterno, Vehiculo
from core.policies.services.comparativo import aseguradoras_sin_bot
from core.policies.services.proceso import resumen_por_vehiculo
from core.security.mixins import GroupPermissionMixin

MODULE_NAME = 'Cotizador'


class VehiculoListView(GroupPermissionMixin, TemplateView):
    template_name = 'vehiculo/list.html'
    permission_required = 'policies.view_vehiculo'

    def post(self, request, *args, **kwargs):
        data = {}
        action = request.POST.get('action')
        try:
            if action == 'search':
                data = []
                qs = Vehiculo.objects.select_related('tomador', 'zona_circulacion', 'zona_circulacion__departamento')
                vehiculos = list(qs)
                resumenes = resumen_por_vehiculo(vehiculos)
                # Aseguradoras sin bot a las que todavía no se les registró valor, por vehículo: si no falta
                # ninguna, «Realizar comparativo» va directo al comparativo sin preguntar.
                sin_bot = aseguradoras_sin_bot()
                registradas = {}
                for vehiculo_id, aseguradora_id in (ValorExterno.objects.filter(vehiculo__in=vehiculos)
                                                    .values_list('vehiculo_id', 'aseguradora_id').distinct()):
                    registradas.setdefault(vehiculo_id, set()).add(aseguradora_id)
                for vehiculo in vehiculos:
                    item = vehiculo.toJSON()
                    item['proceso'] = resumenes[vehiculo.pk]
                    item['externas_faltantes'] = [a.name for a in sin_bot if a.pk not in registradas.get(vehiculo.pk, set())]
                    data.append(item)
            else:
                data['error'] = 'No ha seleccionado ninguna opción'
        except Exception as e:
            data['error'] = str(e)
        return HttpResponse(json.dumps(data), content_type='application/json')

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['title'] = 'Solicitudes de Cotización'
        context['module_name'] = MODULE_NAME
        context['create_url'] = reverse_lazy('solicitud_cotizacion_create')
        context['list_url'] = reverse_lazy('vehiculo_list')
        user = self.request.user
        context['puede_comparar'] = user.has_perm('policies.view_comparativo')
        context['puede_registrar_valores'] = user.has_perm('policies.add_valor_externo')
        context['aseguradoras_sin_bot'] = aseguradoras_sin_bot()
        context['guardar_url_plantilla'] = reverse('vehiculo_comparativo_valores', args=[0])
        context['comparativo_url_plantilla'] = reverse('vehiculo_comparativo', args=[0])
        return context
