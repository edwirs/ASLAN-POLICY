import json

from django.db.models import Count, Max
from django.http import HttpResponse
from django.urls import reverse_lazy
from django.views.generic import TemplateView

from core.policies.models import Vehiculo
from core.security.mixins import StrictPermissionMixin

MODULE_NAME = 'Vehículos'


def _fila(vehiculo):
    tomador = vehiculo.tomador
    documento = tomador.document_type.abbreviation if tomador.document_type else ''
    return {
        'id': vehiculo.id,
        'placa': vehiculo.placa,
        'es_cero_km': vehiculo.es_cero_km,
        'propietario': tomador.names,
        'documento': f'{documento}: {tomador.dni}'.strip(': '),
        'telefono': tomador.mobile,
        'email': tomador.email,
        'marca': vehiculo.marca,
        'referencia': vehiculo.referencia,
        'modelo': vehiculo.modelo,
        'clase': vehiculo.clase,
        'tipo_vehiculo': vehiculo.tipo_vehiculo,
        'color': vehiculo.color,
        'motor': vehiculo.motor,
        'chasis': vehiculo.chasis,
        'serie': vehiculo.serie,
        'combustible': vehiculo.combustible,
        'valor_accesorios': float(vehiculo.valor_accesorios) if vehiculo.valor_accesorios else None,
        'direccion': tomador.address,
        'ciudad_propietario': str(tomador.municipality) if tomador.municipality else None,
        'cotizaciones': getattr(vehiculo, 'total_cotizaciones', 0),
        'servicio': vehiculo.get_servicio_display() if vehiculo.servicio else None,
        'codigo_fasecolda': vehiculo.codigo_fasecolda,
        'valor_comercial': float(vehiculo.valor_comercial) if vehiculo.valor_comercial is not None else None,
        'ciudad': str(vehiculo.zona_circulacion),
        'ultima_cotizacion': vehiculo.ultima_cotizacion.strftime('%Y-%m-%d') if vehiculo.ultima_cotizacion else None,
        'created_at': vehiculo.created_at.strftime('%Y-%m-%d'),
    }


class VehiculoRegistradoListView(StrictPermissionMixin, TemplateView):
    template_name = 'vehiculo_registrado/list.html'
    permission_required = 'policies.view_vehiculo_registrado'

    def post(self, request, *args, **kwargs):
        data = {}
        try:
            if request.POST.get('action') == 'search':
                queryset = (Vehiculo.objects
                            .select_related('tomador', 'tomador__document_type', 'tomador__municipality',
                                            'zona_circulacion', 'zona_circulacion__departamento')
                            .annotate(ultima_cotizacion=Max('cotizaciones__created_at'),
                                      total_cotizaciones=Count('cotizaciones', distinct=True))
                            .order_by('placa'))
                data = [_fila(v) for v in queryset]
            else:
                data['error'] = 'No ha seleccionado ninguna opción'
        except Exception as e:
            data['error'] = str(e)
        return HttpResponse(json.dumps(data), content_type='application/json')

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['title'] = 'Vehículos registrados'
        context['module_name'] = MODULE_NAME
        context['list_url'] = reverse_lazy('vehiculo_registrado_list')
        return context
