"""Estado de las cotizaciones automáticas para mostrar al asesor: qué pasó en
cada aseguradora, en qué paso quedó, con qué datos y qué debe hacer."""
from datetime import timedelta

from django.urls import reverse
from django.utils import timezone

from core.policies.models import Aseguradora, Cotizacion
from core.policies.services.bots import BOTS_DISPONIBLES
from core.policies.services.bots.base import ACCION_POR_TIPO

# «esperando_confirmacion»: el bot está pausado esperando algo que solo el asesor puede hacer (ej. el código SMS).
EN_CURSO = ('pendiente', 'en_proceso', 'esperando_confirmacion')
FINALES_CON_ERROR = ('error', 'cancelado')
# Una cotización "en proceso" por más tiempo que esto ya no tiene un bot vivo
# detrás (se reinició el servidor o el proceso murió): se declara interrumpida.
MINUTOS_INTERRUMPIDA = 25


def marcar_interrumpidas(cotizaciones):
    """Marca como error 'interrumpida' las que llevan demasiado 'en proceso'."""
    limite = timezone.now() - timedelta(minutes=MINUTOS_INTERRUMPIDA)
    for c in cotizaciones:
        if c.estado_bot in EN_CURSO and (c.ejecutado_en or c.created_at) < limite:
            c.estado_bot = 'error'
            c.error_tipo = 'interrumpida'
            c.mensaje_bot = (
                f'La cotización con {c.aseguradora} se interrumpió'
                + (f' en el paso «{c.paso_bot}»' if c.paso_bot else '')
                + ': el proceso dejó de responder (por ejemplo, el servidor se reinició).'
            )
            c.accion_sugerida = ACCION_POR_TIPO['interrumpida'].format(aseguradora=c.aseguradora)
            c.save(update_fields=['estado_bot', 'error_tipo', 'mensaje_bot', 'accion_sugerida'])


def _aseguradoras_activas():
    """Aseguradoras con bot y activas, en el orden de BOTS_DISPONIBLES."""
    activas = {a.name: a for a in Aseguradora.objects.filter(name__in=list(BOTS_DISPONIBLES), is_active=True)}
    return [activas[n] for n in BOTS_DISPONIBLES if n in activas]


# Plan cuyo valor se muestra resaltado como la prima de la aseguradora (la de las demás es «Premium»).
PLAN_DESTACADO = {'La Equidad Seguros': 'Plan Full', 'Qualitas': 'Amplia', 'AXA Colpatria': 'Plus', 'Seguros Mundial': 'Pago de contado'}


def datos_usados(c):
    """Con qué datos se cotizó, para que el asesor vea de un vistazo si alguno está mal."""
    v, t = c.vehiculo, c.tomador
    datos = [
        ('Placa', v.placa + (' (0 km)' if v.es_cero_km else '')),
        ('Tomador', f'{t.names} · {t.document_type.abbreviation} {t.dni}'),
        ('Nacimiento', t.birthdate.strftime('%d/%m/%Y')),
        ('Ciudad', str(v.zona_circulacion)),
    ]
    if v.codigo_fasecolda:
        datos.append(('Código Fasecolda', v.codigo_fasecolda))
    if v.valor_comercial:
        datos.append(('Valor comercial', f'${int(v.valor_comercial):,}'.replace(',', '.')))
    return [{'etiqueta': e, 'valor': val} for e, val in datos]


def serializar_cotizacion(c):
    es_error = c.estado_bot in FINALES_CON_ERROR
    tipo = c.error_tipo
    mensaje = c.mensaje_bot
    accion = c.accion_sugerida
    if c.estado_bot == 'error' and not tipo:
        # Falla registrada antes de existir el diagnóstico detallado.
        tipo = 'inesperado'
        mensaje = 'Esta falla se registró antes del diagnóstico detallado: ' + (c.mensaje_bot or 'sin detalle').split('\n')[0][:200]
        accion = ACCION_POR_TIPO['inesperado'].format(aseguradora=c.aseguradora)
    clave_pendiente = False
    if tipo == 'clave_vencida':
        # Mientras la contraseña no se actualice en el sistema, reenviar solo repetiría el aviso.
        credencial = c.aseguradora.credenciales.filter(is_active=True).order_by('-id').first()
        clave_pendiente = bool(credencial and credencial.requiere_cambio_clave)
    reintentable = (
        es_error
        and not clave_pendiente
        and c.aseguradora.is_active
        and c.aseguradora.name in BOTS_DISPONIBLES
        and tipo != 'no_cotizable'  # la aseguradora no cotiza este caso: reenviar no cambia nada
        and not Cotizacion.objects.filter(vehiculo=c.vehiculo, aseguradora=c.aseguradora, pk__gt=c.pk).exists()
    )
    return {
        'id': c.id,
        'vehiculo_id': c.vehiculo_id,
        'placa': c.vehiculo.placa,
        'aseguradora': c.aseguradora.name,
        'estado_bot': c.estado_bot,
        'estado_bot_display': c.get_estado_bot_display(),
        'paso': c.paso_bot,
        'error_tipo': tipo if es_error else None,
        'error_tipo_display': dict(Cotizacion._meta.get_field('error_tipo').choices).get(tipo) if es_error else None,
        'mensaje': mensaje if es_error else None,
        'nota': c.mensaje_bot if c.estado_bot == 'completado' else None,
        'accion': accion if es_error else None,
        'detalle_tecnico': c.detalle_tecnico if es_error else None,
        'prima_total': float(c.prima_total),
        'porcentaje_descuento': float(c.porcentaje_descuento) if c.porcentaje_descuento is not None else None,
        'plan_destacado': PLAN_DESTACADO.get(c.aseguradora.name, 'Premium'),
        'planes': [{'nombre': p.nombre_plan, 'prima': float(p.prima_total)} for p in c.planes.all()],
        'verificacion': c.verificacion_bot if c.estado_bot == 'esperando_confirmacion' else None,
        'mensaje_espera': c.mensaje_bot if c.estado_bot == 'esperando_confirmacion' else None,
        'puede_reintentar': reintentable,
        'clave_pendiente': clave_pendiente,
        'url_credencial': reverse('aseguradora_update', args=[c.aseguradora_id]) if clave_pendiente else None,
        'intento': Cotizacion.objects.filter(vehiculo=c.vehiculo, aseguradora=c.aseguradora, pk__lte=c.pk).count(),
        'iniciada': (c.ejecutado_en or c.created_at).strftime('%d/%m/%Y %H:%M'),
        'datos': datos_usados(c),
    }


def ultimas_por_aseguradora(vehiculo):
    """Última cotización del vehículo en cada aseguradora activa (orden estable)."""
    cotizaciones = []
    for aseguradora in _aseguradoras_activas():
        ultima = (Cotizacion.objects.filter(vehiculo=vehiculo, aseguradora=aseguradora)
                  .select_related('aseguradora', 'vehiculo', 'tomador', 'tomador__document_type',
                                  'vehiculo__zona_circulacion', 'vehiculo__zona_circulacion__departamento')
                  .order_by('-id').first())
        if ultima:
            cotizaciones.append(ultima)
    marcar_interrumpidas(cotizaciones)
    return cotizaciones


def resumen_por_vehiculo(vehiculos):
    """{vehiculo_id: {estado, ok, error, curso, total, detalle}} con UNA consulta."""
    activas = _aseguradoras_activas()
    ids_activas = {a.id: a for a in activas}
    ultimas = {}
    qs = (Cotizacion.objects.filter(vehiculo__in=vehiculos, aseguradora__in=activas)
          .select_related('aseguradora').order_by('id'))
    cotizaciones = list(qs)
    marcar_interrumpidas(cotizaciones)
    for c in cotizaciones:  # orden ascendente: la última de cada par queda al final
        ultimas[(c.vehiculo_id, c.aseguradora_id)] = c

    resumen = {}
    for v in vehiculos:
        detalle = [{'aseguradora': a.name, 'estado_bot': ultimas[(v.pk, a.id)].estado_bot,
                    'error_tipo': ultimas[(v.pk, a.id)].error_tipo or None}
                   for a in activas if (v.pk, a.id) in ultimas]
        ok = sum(1 for d in detalle if d['estado_bot'] == 'completado')
        curso = sum(1 for d in detalle if d['estado_bot'] in EN_CURSO)
        # «La aseguradora no cotiza este caso», «portal saturado» y «cambiar contraseña» son advertencias, no fallas del proceso.
        aviso = sum(1 for d in detalle if d['estado_bot'] == 'error' and d['error_tipo'] in ('no_cotizable', 'saturado', 'clave_vencida'))
        error = len(detalle) - ok - curso - aviso
        if not detalle:
            estado = 'sin_cotizar'
        elif curso:
            estado = 'en_proceso'
        elif error == 0:
            estado = 'completado'
        elif ok:
            estado = 'parcial'
        else:
            estado = 'con_errores'
        resumen[v.pk] = {'estado': estado, 'ok': ok, 'error': error, 'aviso': aviso, 'curso': curso, 'total': len(detalle), 'detalle': detalle}
    return resumen
