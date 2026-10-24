import json
import re

from django.contrib.auth.decorators import login_required
from django.db import connection, transaction
from django.http import HttpResponse
from django.views.generic import TemplateView

from core.policies.forms import SolicitudCotizacionForm
from core.policies.models import Aseguradora, AseguradoraCredencial, Cotizacion, TipoPoliza, Vehiculo
from core.policies.services.bots import BOTS_DISPONIBLES
from core.policies.services.bots.runner import lanzar_bot_en_segundo_plano
from core.policies.services.clientes import get_or_update_client
from core.policies.services.reenvio import reenviar
from core.policies.services.proceso import (
    EN_CURSO,
    FINALES_CON_ERROR,
    marcar_interrumpidas,
    serializar_cotizacion,
    ultimas_por_aseguradora,
)
from core.pos.models import Client
from core.security.mixins import GroupPermissionMixin

MODULE_NAME = 'Cotizador'


def aseguradoras_con_bot():
    """Aseguradoras activas para las que existe un bot, en el orden de BOTS_DISPONIBLES.

    Las filas de las aseguradoras con bot se crean si faltan (así una instalación
    nueva ya las lista). Las inactivas no aparecen: no se pueden elegir."""
    return [
        aseguradora for aseguradora in (
            Aseguradora.objects.get_or_create(name=nombre)[0] for nombre in BOTS_DISPONIBLES
        ) if aseguradora.is_active
    ]


def _client_lookup_data(client):
    return {
        'found': True,
        'document_type_id': client.document_type_id,
        'dni': client.dni,
        'names': client.names,
        'birthdate': client.birthdate.strftime('%Y-%m-%d'),
        'email': client.email or '',
        'zona_circulacion_id': client.municipality_id,
    }


@login_required
def consultar_registro(request):
    """Busca por cédula o placa si ya existe un registro guardado (Cliente o
    Vehículo) y, de existir, retorna los datos para autocompletar el
    formulario de Nueva Cotización."""
    tipo = request.GET.get('tipo')
    valor = (request.GET.get('valor') or '').strip()
    data = {'found': False}
    if not valor:
        return HttpResponse(json.dumps(data), content_type='application/json')

    try:
        if tipo == 'dni':
            client = Client.objects.filter(dni=valor).first()
            if client:
                data = _client_lookup_data(client)
                vehiculos = list(client.vehiculos.select_related('zona_circulacion').all())
                if len(vehiculos) == 1:
                    data['placa'] = vehiculos[0].placa
                    data['zona_circulacion_id'] = vehiculos[0].zona_circulacion_id
                elif len(vehiculos) > 1:
                    data['vehiculos'] = [
                        {
                            'placa': v.placa,
                            'zona_circulacion_id': v.zona_circulacion_id,
                            'zona_circulacion': str(v.zona_circulacion),
                        }
                        for v in vehiculos
                    ]
        elif tipo == 'placa':
            vehiculo = Vehiculo.objects.select_related('tomador').filter(placa=valor.upper()).first()
            if vehiculo:
                data = _client_lookup_data(vehiculo.tomador)
                data['zona_circulacion_id'] = vehiculo.zona_circulacion_id
    except Exception as e:
        data = {'found': False, 'error': str(e)}

    return HttpResponse(json.dumps(data), content_type='application/json')


@login_required
def iniciar_cotizacion(request):
    """Lanza, para un vehículo ya registrado, un bot de cotización por cada
    aseguradora soportada (ver BOTS_DISPONIBLES). Cada bot corre en un hilo
    aparte y no bloquea esta respuesta: el frontend consulta el avance con
    `estado_cotizaciones`."""
    if request.method != 'POST':
        return HttpResponse(json.dumps({'error': 'Método no permitido'}), content_type='application/json', status=405)

    vehiculo_id = request.POST.get('vehiculo_id')
    try:
        vehiculo = Vehiculo.objects.select_related('tomador').get(pk=vehiculo_id)
    except (Vehiculo.DoesNotExist, ValueError, TypeError):
        return HttpResponse(json.dumps({'error': 'No se encontró el vehículo indicado'}), content_type='application/json')

    tipo_poliza, _ = TipoPoliza.objects.get_or_create(code='todo-riesgo', defaults={'name': 'Todo Riesgo'})
    schema_name = connection.schema_name

    # El asesor elige en el modal a qué aseguradoras enviar esta solicitud. Sin esa
    # lista (clientes antiguos) se usan todas las activas. Los ids que no sean de una
    # aseguradora activa con bot se ignoran: no se puede forzar una inactiva.
    activas = {a.pk: a for a in aseguradoras_con_bot()}
    if 'aseguradoras' in request.POST or request.POST.get('eligio_aseguradoras'):
        elegidas = set()
        for valor in request.POST.getlist('aseguradoras'):
            try:
                elegidas.add(int(valor))
            except (TypeError, ValueError):
                continue
        seleccion = [a for pk, a in activas.items() if pk in elegidas]
        if not seleccion:
            return HttpResponse(json.dumps({'error': 'Seleccione al menos una aseguradora para cotizar.'}), content_type='application/json')
    else:
        seleccion = list(activas.values())

    cotizaciones = []
    for aseguradora in seleccion:
        nombre_aseguradora = aseguradora.name
        bot_class = BOTS_DISPONIBLES[nombre_aseguradora]
        cotizacion = Cotizacion.objects.create(
            vehiculo=vehiculo,
            tomador=vehiculo.tomador,
            asesor=request.user,
            aseguradora=aseguradora,
            tipo_poliza=tipo_poliza,
        )
        lanzar_bot_en_segundo_plano(cotizacion.id, bot_class, schema_name)
        cotizaciones.append({'id': cotizacion.id, 'aseguradora': nombre_aseguradora})

    if not cotizaciones:
        return HttpResponse(json.dumps({'error': 'No hay aseguradoras activas para cotizar.'}), content_type='application/json')

    return HttpResponse(json.dumps({'cotizaciones': cotizaciones}), content_type='application/json')


def _json(data, status=200):
    return HttpResponse(json.dumps(data), content_type='application/json', status=status)


@login_required
def estado_cotizaciones(request):
    """Consulta el avance de una o varias cotizaciones (polling desde el
    frontend mientras los bots corren). Devuelve el detalle completo: paso,
    error clasificado, qué hacer, datos usados y planes."""
    ids = [i for i in (request.GET.get('ids') or '').split(',') if i.strip().isdigit()]
    cotizaciones = list(Cotizacion.objects.select_related(
        'aseguradora', 'vehiculo', 'tomador', 'tomador__document_type',
        'vehiculo__zona_circulacion', 'vehiculo__zona_circulacion__departamento',
    ).filter(pk__in=ids))
    marcar_interrumpidas(cotizaciones)
    return _json({'cotizaciones': [serializar_cotizacion(c) for c in cotizaciones]})


@login_required
def proceso_vehiculo(request, pk):
    """Estado actual de una solicitud (vehículo): la última cotización de cada
    aseguradora activa. Lo usa el botón «Ver proceso» del listado."""
    try:
        vehiculo = Vehiculo.objects.select_related('tomador').get(pk=pk)
    except Vehiculo.DoesNotExist:
        return _json({'error': 'No se encontró la solicitud'}, status=404)
    cotizaciones = [serializar_cotizacion(c) for c in ultimas_por_aseguradora(vehiculo)]
    return _json({
        'placa': vehiculo.placa,
        'vehiculo_id': vehiculo.pk,
        'tomador': vehiculo.tomador.names,
        'cotizaciones': cotizaciones,
        'en_curso': any(c['estado_bot'] in EN_CURSO for c in cotizaciones),
    })


@login_required
def verificar_cotizacion(request):
    """El asesor responde a lo que un bot le pidió: el código de 6 dígitos que la aseguradora envió al celular
    (`codigo`), o cancela la espera (`cancelar`). El código solo se guarda mientras el bot lo recoge."""
    if request.method != 'POST':
        return _json({'error': 'Método no permitido'}, status=405)
    try:
        cotizacion = Cotizacion.objects.get(pk=request.POST.get('cotizacion_id'))
    except (Cotizacion.DoesNotExist, ValueError, TypeError):
        return _json({'error': 'No se encontró la cotización'}, status=404)
    if cotizacion.estado_bot != 'esperando_confirmacion':
        return _json({'error': 'La aseguradora ya no está esperando una respuesta (se agotó el tiempo o ya continuó).'}, status=409)
    if request.POST.get('cancelar'):
        Cotizacion.objects.filter(pk=cotizacion.pk).update(confirmacion_bot=False)
        return _json({})
    if cotizacion.verificacion_bot != 'codigo':
        return _json({'error': 'Esta cotización no está esperando un código.'}, status=409)
    codigo = (request.POST.get('codigo') or '').strip()
    if not re.fullmatch(r'\d{6}', codigo):
        return _json({'error': 'El código debe tener 6 dígitos.'}, status=400)
    Cotizacion.objects.filter(pk=cotizacion.pk).update(codigo_verificacion=codigo)
    return _json({})


@login_required
def reintentar_cotizacion(request):
    """Reenvía la solicitud SOLO a la aseguradora cuya cotización falló: crea
    una cotización nueva para el mismo vehículo y lanza únicamente ese bot."""
    if request.method != 'POST':
        return _json({'error': 'Método no permitido'}, status=405)
    try:
        original = Cotizacion.objects.select_related('aseguradora', 'vehiculo', 'tomador').get(pk=request.POST.get('cotizacion_id'))
    except (Cotizacion.DoesNotExist, ValueError, TypeError):
        return _json({'error': 'No se encontró la cotización a reenviar'})

    nueva, motivo = reenviar(original, request.user)
    if motivo:
        return _json({'error': motivo})
    return _json({'cotizacion': {'id': nueva.id, 'aseguradora': original.aseguradora.name}})


class SolicitudCotizacionCreateView(GroupPermissionMixin, TemplateView):
    template_name = 'solicitud/create.html'
    permission_required = 'policies.add_vehiculo'

    def post(self, request, *args, **kwargs):
        data = {}
        action = request.POST.get('action')
        try:
            if action == 'add':
                form = SolicitudCotizacionForm(request.POST)
                if form.is_valid():
                    cd = form.cleaned_data
                    defaults_vehiculo = {
                        'zona_circulacion': cd['zona_circulacion'],
                        'es_cero_km': cd['es_cero_km'],
                    }
                    # Fasecolda y valor comercial solo vienen del formulario en
                    # 0 km; en los demás casos no se pisan los que ya capturaron
                    # los bots de las aseguradoras para ese vehículo.
                    if cd['es_cero_km']:
                        defaults_vehiculo['codigo_fasecolda'] = cd['codigo_fasecolda']
                        defaults_vehiculo['valor_comercial'] = cd['valor_comercial']
                    with transaction.atomic():
                        client = get_or_update_client(cd, municipality=cd['zona_circulacion'])
                        defaults_vehiculo['tomador'] = client
                        vehiculo, _ = Vehiculo.objects.update_or_create(
                            placa=cd['placa'],
                            defaults=defaults_vehiculo,
                        )
                        data = vehiculo.toJSON()
                else:
                    data['error'] = dict(form.errors.items())
            else:
                data['error'] = 'No ha seleccionado ninguna opción'
        except Exception as e:
            data['error'] = str(e)
        return HttpResponse(json.dumps(data), content_type='application/json')

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['title'] = 'Nueva Cotización'
        context['module_name'] = MODULE_NAME
        context['form'] = SolicitudCotizacionForm()
        activas = aseguradoras_con_bot()
        pendientes = set(AseguradoraCredencial.objects.filter(
            aseguradora__in=activas, is_active=True, requiere_cambio_clave=True).values_list('aseguradora_id', flat=True))
        for a in activas:
            a.clave_pendiente = a.pk in pendientes  # el modal la deja sin marcar y avisa por qué
        context['aseguradoras_activas'] = activas
        return context
