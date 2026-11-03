import json
from datetime import date

from django.http import HttpResponse
from django.urls import reverse, reverse_lazy
from django.utils.decorators import method_decorator
from django.views.generic import TemplateView
from django.views.decorators.gzip import gzip_page

from core.policies.choices import MOTIVO_NO_COMPRO
from core.policies.models import Aseguradora, ValorExterno, Vehiculo
from core.policies.services.bots import BOTS_DISPONIBLES
from core.policies.services.comparativo import aseguradoras_sin_bot
from core.policies.services.etapas import ETAPAS, etapa_de, etapas_por_vehiculo
from core.policies.services.polizas import registrar_evento
from core.policies.services.proceso import resumen_por_vehiculo
from core.security.mixins import GroupPermissionMixin

MODULE_NAME = 'Cotizador'



def _fila(vehiculo):
    """Lo que necesita la tabla de solicitudes (static/vehiculo/js/list.js), sin la ficha completa del cliente."""
    tomador = vehiculo.tomador
    return {
        'id': vehiculo.id,
        'placa': vehiculo.placa,
        'marca': vehiculo.marca,
        'clase': vehiculo.clase,
        'modelo': vehiculo.modelo,
        'es_cero_km': vehiculo.es_cero_km,
        'zona_circulacion': str(vehiculo.zona_circulacion),
        'created_at': vehiculo.created_at.strftime('%Y-%m-%d %H:%M'),
        'tomador': {
            'names': tomador.names,
            'dni': tomador.dni,
            'document_type': {'abbreviation': tomador.document_type.abbreviation} if tomador.document_type else None,
            'mobile': tomador.mobile,
            'phone': tomador.phone,
            'email': tomador.email,
            'email_secundario': tomador.email_secundario,
        },
    }


# Los datos de la tabla (JSON) viajan comprimidos: con miles de filas pesan ~10 veces menos.
@method_decorator(gzip_page, name='post')
class VehiculoListView(GroupPermissionMixin, TemplateView):
    template_name = 'vehiculo/list.html'
    permission_required = 'policies.view_vehiculo'

    def post(self, request, *args, **kwargs):
        data = {}
        action = request.POST.get('action')
        try:
            if action == 'search':
                data = []
                # Todo en pocas consultas (no una por fila) y solo los datos que pinta la tabla: con miles de
                # vehículos la respuesta completa de toJSON() pesaba varios MB.
                vehiculos = list(Vehiculo.objects.select_related('tomador__document_type', 'zona_circulacion__departamento'))
                resumenes = resumen_por_vehiculo(vehiculos)
                # Aseguradoras sin bot a las que todavía no se les registró valor, por vehículo: si no falta
                # ninguna, «Realizar comparativo» va directo al comparativo sin preguntar.
                sin_bot = aseguradoras_sin_bot()
                con_bot = {a.name: a.pk for a in Aseguradora.objects.filter(is_active=True, name__in=list(BOTS_DISPONIBLES))}
                registradas = {}
                for vehiculo_id, aseguradora_id in (ValorExterno.objects.filter(vehiculo__in=vehiculos)
                                                    .values_list('vehiculo_id', 'aseguradora_id').distinct()):
                    registradas.setdefault(vehiculo_id, set()).add(aseguradora_id)
                etapas = etapas_por_vehiculo(vehiculos)
                for vehiculo in vehiculos:
                    item = _fila(vehiculo)
                    item['etapa'] = etapas[vehiculo.pk]
                    item['ultima_cotizacion'] = etapas[vehiculo.pk]['ultima_cotizacion']
                    item['tiene_valor_externo'] = bool(registradas.get(vehiculo.pk))
                    item['proceso'] = resumenes[vehiculo.pk]
                    item['externas_faltantes'] = [a.name for a in sin_bot if a.pk not in registradas.get(vehiculo.pk, set())]
                    # A qué aseguradoras se les puede registrar valor a mano: sin bot, o con bot que no trajo valor.
                    completadas = {d['aseguradora'] for d in resumenes[vehiculo.pk]['detalle'] if d['estado_bot'] == 'completado'}
                    item['valor_manual_ids'] = [a.pk for a in sin_bot] + [pk for nombre, pk in con_bot.items() if nombre not in completadas]
                    data.append(item)
            elif action in ('no_compro', 'deshacer_no_compro'):
                data = self._no_compro(request, action)
            else:
                data['error'] = 'No ha seleccionado ninguna opción'
        except Exception as e:
            data['error'] = str(e)
        return HttpResponse(json.dumps(data), content_type='application/json')

    @staticmethod
    def _no_compro(request, action):
        """«El cliente no compró»: cierra la cotización sin póliza (no bloquea la placa; se puede volver a cotizar)."""
        if not request.user.has_perm('policies.add_poliza'):
            return {'error': 'Tu perfil no puede registrar la decisión del cliente.'}
        vehiculo = Vehiculo.objects.get(pk=request.POST.get('id'))
        if action == 'deshacer_no_compro':
            anterior = vehiculo.get_no_compro_motivo_display() or 'No compró'
            vehiculo.no_compro_fecha, vehiculo.no_compro_motivo, vehiculo.no_compro_nota = None, '', ''
            vehiculo.save(update_fields=['no_compro_fecha', 'no_compro_motivo', 'no_compro_nota'])
            registrar_evento(vehiculo, 'decision', anterior, 'Vuelve a esperar decisión', '', request.user)
            return {'etapa': etapa_de(vehiculo)}
        motivo = request.POST.get('motivo', '')
        if motivo not in dict(MOTIVO_NO_COMPRO):
            return {'error': 'Elige el motivo por el que el cliente no compró.'}
        vehiculo.no_compro_fecha = date.today()
        vehiculo.no_compro_motivo = motivo
        vehiculo.no_compro_nota = request.POST.get('nota', '').strip()[:300]
        vehiculo.save(update_fields=['no_compro_fecha', 'no_compro_motivo', 'no_compro_nota'])
        registrar_evento(vehiculo, 'decision', 'Esperando decisión', f'No compró: {vehiculo.get_no_compro_motivo_display()}',
                         vehiculo.no_compro_nota, request.user)
        return {'etapa': etapa_de(vehiculo)}

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['title'] = 'Solicitudes de Cotización'
        context['module_name'] = MODULE_NAME
        context['create_url'] = reverse_lazy('solicitud_cotizacion_create')
        context['list_url'] = reverse_lazy('vehiculo_list')
        user = self.request.user
        context['puede_comparar'] = user.has_perm('policies.view_comparativo')
        context['puede_registrar_valores'] = user.has_perm('policies.add_valor_externo')
        context['puede_registrar_poliza'] = user.has_perm('policies.add_poliza')
        context['aseguradoras_manual'] = [(a, a.name in BOTS_DISPONIBLES) for a in Aseguradora.objects.filter(is_active=True).order_by('name')]
        context['guardar_url_plantilla'] = reverse('vehiculo_comparativo_valores', args=[0])
        context['comparativo_url_plantilla'] = reverse('vehiculo_comparativo', args=[0])
        context['etapas'] = [(e[0], e[1]) for e in ETAPAS]
        context['motivos_no_compro'] = MOTIVO_NO_COMPRO
        return context
