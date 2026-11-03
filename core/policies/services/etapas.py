"""En qué va cada vehículo, en UNA palabra: la «etapa». Une lo que antes estaba repartido (avance de los bots, «sin decisión»,
póliza vigente, estado del vehículo) para que el usuario sepa de un vistazo qué hacer con cada placa.

Orden de prioridad: vehículo inactivo (vendido, siniestrado…) → cotizando → con póliza vigente (o por renovar) → póliza vencida
→ no compró → esperando decisión → cotización sin valores → sin cotizar.
"""
from datetime import date, timedelta
from zoneinfo import ZoneInfo

from django.utils import timezone

from core.policies.models import Cotizacion, Poliza, ValorExterno
from core.policies.services.polizas import DIAS_AVISO_RENOVACION
from core.policies.services.proceso import EN_CURSO, MINUTOS_INTERRUMPIDA

# id, nombre, color (clase CSS «etapa-<color>»), qué hacer
ETAPAS = (
    ('sin_cotizar', 'Sin cotizar', 'gris', 'Todavía no se ha enviado a ninguna aseguradora.'),
    ('cotizando', 'Cotizando', 'azul', 'Los bots están consultando las aseguradoras.'),
    ('sin_valores', 'Cotización sin valores', 'rojo', 'Ninguna aseguradora devolvió valor: revisa el proceso y reenvía.'),
    ('esperando', 'Esperando decisión', 'ambar', 'Ya tiene valores: falta saber qué eligió el cliente.'),
    ('no_compro', 'No compró', 'gris', 'El cliente no compró esta vez. Se puede volver a cotizar.'),
    ('con_poliza', 'Con póliza vigente', 'verde', 'El cliente tiene una póliza vigente.'),
    ('por_renovar', 'Por renovar', 'naranja', f'La póliza vence en los próximos {DIAS_AVISO_RENOVACION} días: hay que cotizar la renovación.'),
    ('vencida', 'Póliza vencida', 'rojo', 'La póliza venció y no se ha renovado.'),
    ('inactivo', 'Inactivo', 'oscuro', 'Vendido, siniestrado… No se puede cotizar hasta reactivarlo.'),
)
NOMBRES = {e[0]: e[1] for e in ETAPAS}
TZ_NEGOCIO = ZoneInfo('America/Bogota')


def _fecha(d):
    return d.strftime('%d/%m/%Y') if d else None


def etapas_por_vehiculo(vehiculos, hoy=None):
    """{vehiculo_id: {id, nombre, color, detalle, dias, poliza}} con cuatro consultas para todos los vehículos."""
    hoy = hoy or date.today()
    ids = [v.pk for v in vehiculos]
    limite_curso = timezone.now() - timedelta(minutes=MINUTOS_INTERRUMPIDA)

    cotizaciones = {}
    for vid, estado_bot, creada, ejecutada in (Cotizacion.objects.filter(vehiculo_id__in=ids)
                                               .values_list('vehiculo_id', 'estado_bot', 'created_at', 'ejecutado_en')):
        cotizaciones.setdefault(vid, []).append((estado_bot, creada, (ejecutada or creada) >= limite_curso))
    externos = {}
    for vid, creada in ValorExterno.objects.filter(vehiculo_id__in=ids).values_list('vehiculo_id', 'created_at'):
        externos.setdefault(vid, []).append(creada)
    polizas = {}
    for p in (Poliza.objects.filter(vehiculo_id__in=ids).exclude(estado='cancelada').select_related('aseguradora')
              .only('id', 'vehiculo_id', 'fecha_renovacion', 'created_at', 'plan', 'aseguradora__name')):
        polizas.setdefault(p.vehiculo_id, []).append(p)

    resultado = {}
    for v in vehiculos:
        cots = cotizaciones.get(v.pk, [])
        exts = externos.get(v.pk, [])
        pols = polizas.get(v.pk, [])
        vigente = max((p for p in pols if p.fecha_renovacion >= hoy), key=lambda p: p.fecha_renovacion, default=None)
        ultima_poliza = max(pols, key=lambda p: p.created_at, default=None)
        fechas = [c[1] for c in cots] + exts
        ultima_cot = max(fechas) if fechas else None
        cotizando = any(estado in EN_CURSO and fresca for estado, _, fresca in cots)
        poliza = None
        if vigente:
            poliza = {'id': vigente.pk, 'aseguradora': vigente.aseguradora.name, 'plan': vigente.plan,
                      'vence': _fecha(vigente.fecha_renovacion), 'dias': (vigente.fecha_renovacion - hoy).days}
        elif ultima_poliza:
            poliza = {'id': ultima_poliza.pk, 'aseguradora': ultima_poliza.aseguradora.name, 'plan': ultima_poliza.plan,
                      'vence': _fecha(ultima_poliza.fecha_renovacion), 'dias': (ultima_poliza.fecha_renovacion - hoy).days}
        dias, detalle = None, ''

        if v.estado != 'activo':
            etapa = 'inactivo'
            detalle = v.get_estado_display() + (f' desde el {_fecha(v.estado_fecha)}' if v.estado_fecha else '')
        elif cotizando:
            etapa = 'cotizando'
            detalle = 'Cotizando renovación' if vigente else 'Consultando aseguradoras'
        elif vigente:
            dias = poliza['dias']
            etapa = 'por_renovar' if dias <= DIAS_AVISO_RENOVACION else 'con_poliza'
            detalle = f'{vigente.aseguradora.name} · vence el {poliza["vence"]}'
            if etapa == 'por_renovar' and ultima_cot and ultima_cot > vigente.created_at:
                detalle += ' · renovación ya cotizada'
        elif ultima_poliza and (ultima_cot is None or ultima_cot <= ultima_poliza.created_at):
            etapa = 'vencida'
            dias = (hoy - ultima_poliza.fecha_renovacion).days
            detalle = f'{ultima_poliza.aseguradora.name} · venció el {_fecha(ultima_poliza.fecha_renovacion)}'
        elif ultima_cot is None:
            etapa = 'sin_cotizar'
        elif v.no_compro_fecha and v.no_compro_fecha >= timezone.localtime(ultima_cot, TZ_NEGOCIO).date():
            etapa = 'no_compro'
            detalle = (v.get_no_compro_motivo_display() or 'Sin motivo') + f' · {_fecha(v.no_compro_fecha)}'
        else:
            desde = ultima_poliza.created_at if ultima_poliza else None
            con_valor = (any(e == 'completado' and (desde is None or c > desde) for e, c, _ in cots)
                         or any(desde is None or c > desde for c in exts))
            dias = (hoy - timezone.localtime(ultima_cot, TZ_NEGOCIO).date()).days
            if con_valor:
                etapa = 'esperando'
                detalle = 'Cotizado hoy' if dias == 0 else f'Cotizado hace {dias} día{"s" if dias != 1 else ""}'
            else:
                etapa = 'sin_valores'
                detalle = 'Ninguna aseguradora devolvió valor'
        _, nombre, color, ayuda = next(e for e in ETAPAS if e[0] == etapa)
        resultado[v.pk] = {'id': etapa, 'nombre': nombre, 'color': color, 'ayuda': ayuda, 'detalle': detalle, 'dias': dias,
                           'poliza': poliza, 'ultima_cotizacion': timezone.localtime(ultima_cot, TZ_NEGOCIO).strftime('%Y-%m-%d') if ultima_cot else None}
    return resultado


def etapa_de(vehiculo):
    return etapas_por_vehiculo([vehiculo])[vehiculo.pk]
