import json
from datetime import date, timedelta

from django.db.models import Count, Max
from django.http import HttpResponse
from django.urls import reverse, reverse_lazy
from django.utils.decorators import method_decorator
from django.views.generic import TemplateView
from django.views.decorators.gzip import gzip_page

from core.tenants.estado import modulo_activo
from core.policies.choices import ESTADO_VEHICULO
from core.policies.models import Vehiculo
from core.policies.services.etapas import ETAPAS, etapa_de, etapas_por_vehiculo
from core.policies.services.polizas import cambiar_estado
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
        'otro_celular': tomador.phone,
        'otro_correo': tomador.email_secundario,
        'propietario_empresa_documento': tomador.propietario_documento,
        'propietario_empresa_nombre': tomador.propietario_nombre,
        'estado': vehiculo.estado_json(),
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


def _historial(vehiculo):
    """Seguimiento del vehículo a lo largo de los años: pólizas elegidas, dónde y para quién se cotizó cada año y los cambios
    de estado, propietario y ciudad."""
    polizas = [p.toJSON() for p in vehiculo.polizas.select_related('tomador', 'tomador__document_type', 'asesor', 'aseguradora',
                                                                    'tipo_poliza', 'zona_circulacion', 'zona_circulacion__departamento')]
    por_anio = {}
    for c in vehiculo.cotizaciones.select_related('tomador', 'aseguradora', 'zona_circulacion__departamento').order_by('created_at'):
        a = por_anio.setdefault(c.created_at.year, {'anio': c.created_at.year, 'ciudades': [], 'tomadores': [], 'aseguradoras': set(), 'total': 0})
        ciudad = str(c.zona_circulacion) if c.zona_circulacion else '—'
        if ciudad not in a['ciudades']:
            a['ciudades'].append(ciudad)
        if c.tomador.names not in a['tomadores']:
            a['tomadores'].append(c.tomador.names)
        a['aseguradoras'].add(c.aseguradora.name)
        a['total'] += 1
    cotizaciones = [{**a, 'aseguradoras': len(a['aseguradoras'])} for a in sorted(por_anio.values(), key=lambda x: -x['anio'])]
    eventos = [e.toJSON() for e in vehiculo.historial.select_related('usuario')[:50]]
    return {'polizas': polizas, 'cotizaciones': cotizaciones, 'eventos': eventos, 'estado': vehiculo.estado_json(),
            'resumen': _resumen(vehiculo)}


def _resumen(vehiculo):
    """Lo primero que se ve en la ficha: etapa, póliza vigente con sus cuotas y la última ronda de cotización."""
    hoy = date.today()
    etapa = etapa_de(vehiculo)
    poliza = None
    vigente = (vehiculo.polizas.filter(estado='generada', fecha_renovacion__gte=hoy).select_related('aseguradora', 'asesor')
               .order_by('-fecha_renovacion').first())
    if vigente:
        cuotas = list(vigente.cuotas.all())
        pendientes = [c for c in cuotas if not c.pagada]
        proxima = pendientes[0] if pendientes else None
        poliza = {**vigente.toJSON(), 'cuotas_pagadas': len(cuotas) - len(pendientes),
                  'cuotas_atrasadas': sum(1 for c in pendientes if c.fecha < hoy),
                  'proxima_cuota': {'fecha': proxima.fecha.strftime('%Y-%m-%d'), 'valor': float(proxima.valor), 'numero': proxima.numero} if proxima else None}
    ronda = None
    ultima = vehiculo.cotizaciones.order_by('-created_at').first()
    if ultima:
        # «Ronda» = las cotizaciones de los 30 días anteriores a la última (una solicitud con varias aseguradoras y reenvíos).
        recientes = vehiculo.cotizaciones.filter(created_at__gte=ultima.created_at - timedelta(days=30)).select_related('aseguradora', 'zona_circulacion')
        completas = [c for c in recientes if c.estado_bot == 'completado' and c.prima_total and c.prima_total > 0]
        mejor = min(completas, key=lambda c: c.prima_total, default=None)
        externos = list(vehiculo.valores_externos.filter(created_at__gte=ultima.created_at - timedelta(days=30)).select_related('aseguradora'))
        mejor_ext = min(externos, key=lambda e: e.valor, default=None)
        if mejor_ext and (mejor is None or mejor_ext.valor < mejor.prima_total):
            mejor_valor = {'aseguradora': mejor_ext.aseguradora.name, 'valor': float(mejor_ext.valor)}
        else:
            mejor_valor = {'aseguradora': mejor.aseguradora.name, 'valor': float(mejor.prima_total)} if mejor else None
        ronda = {'fecha': etapa['ultima_cotizacion'], 'ciudad': str(ultima.zona_circulacion or vehiculo.zona_circulacion),
                 'con_valor': len({c.aseguradora_id for c in completas} | {e.aseguradora_id for e in externos}),
                 'consultadas': len({c.aseguradora_id for c in recientes} | {e.aseguradora_id for e in externos}), 'mejor': mejor_valor}
    return {'etapa': etapa, 'poliza': poliza, 'ronda': ronda}


# Los datos de la tabla (JSON) viajan comprimidos: con miles de filas pesan ~10 veces menos.
@method_decorator(gzip_page, name='post')
class VehiculoRegistradoListView(StrictPermissionMixin, TemplateView):
    template_name = 'vehiculo_registrado/list.html'
    permission_required = 'policies.view_vehiculo_registrado'

    def post(self, request, *args, **kwargs):
        data = {}
        try:
            if request.POST.get('action') == 'search':
                queryset = (Vehiculo.objects
                            .select_related('tomador__document_type', 'tomador__municipality__departamento',
                                            'zona_circulacion__departamento')
                            .annotate(ultima_cotizacion=Max('cotizaciones__created_at'),
                                      total_cotizaciones=Count('cotizaciones', distinct=True))
                            .order_by('placa'))
                vehiculos = list(queryset)
                etapas = etapas_por_vehiculo(vehiculos)
                data = [{**_fila(v), 'etapa': etapas[v.pk]} for v in vehiculos]
            elif request.POST.get('action') == 'historial':
                data = _historial(Vehiculo.objects.get(pk=request.POST.get('id')))
            elif request.POST.get('action') == 'estado':
                if not request.user.has_perm('policies.change_vehiculo_estado'):
                    data['error'] = 'Tu perfil no puede cambiar el estado de un vehículo.'
                else:
                    vehiculo = Vehiculo.objects.get(pk=request.POST.get('id'))
                    estado = request.POST.get('estado')
                    if estado == 'activo' or estado not in dict(ESTADO_VEHICULO):
                        data['error'] = 'Elige un estado válido. Para volver a cotizarlo se reactiva desde «Nueva solicitud».'
                    else:
                        try:
                            fecha = date.fromisoformat(request.POST.get('fecha')) if request.POST.get('fecha') else None
                        except ValueError:
                            fecha = None
                        cambiar_estado(vehiculo, estado, fecha, request.POST.get('nota', '').strip(), request.user)
                        data = vehiculo.estado_json()
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
        context['estados'] = [e for e in ESTADO_VEHICULO if e[0] != 'activo']
        context['puede_cambiar_estado'] = self.request.user.has_perm('policies.change_vehiculo_estado')
        user = self.request.user
        context['puede_ver_polizas'] = user.has_perm('policies.view_poliza') and modulo_activo(self.request, 'cartera')
        context['etapas'] = [(e[0], e[1]) for e in ETAPAS]
        context['ficha'] = {
            'cotizar': reverse('solicitud_cotizacion_create') if user.has_perm('policies.add_vehiculo') else '',
            'solicitudes': reverse('vehiculo_list') if user.has_perm('policies.view_vehiculo') else '',
            'polizas': reverse('poliza_list') if context['puede_ver_polizas'] else '',
        }
        return context
