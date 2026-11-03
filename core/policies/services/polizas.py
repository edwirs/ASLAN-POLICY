"""Pólizas elegidas, sus cuotas y el seguimiento de cada vehículo (estado, propietario y ciudad a lo largo de los años).

Reglas de negocio (definidas con Gali):
- La aseguradora financia; nosotros no recaudamos. Las cuotas son siempre mensuales y la primera es la «fecha de pago».
- La «fecha de renovación» es el vencimiento de la póliza: un mes antes se le avisa al cliente para renovar.
- Un vehículo que no está «activo» (vendido, siniestrado…) no se puede cotizar hasta que alguien lo reactive desde la solicitud.
"""
import calendar
import re
from datetime import date
from decimal import ROUND_HALF_UP, Decimal

from django.db import transaction

from core.policies.choices import ESTADO_VEHICULO
from core.policies.models import Asesor, Cotizacion, CuotaPoliza, HistorialVehiculo, ValorExterno

DIAS_AVISO_RENOVACION = 30
MAX_CUOTAS = 24


def sumar_meses(desde, meses):
    """`desde` + N meses sin salirse del calendario (31 de enero + 1 mes = 28/29 de febrero)."""
    m = desde.month - 1 + meses
    anio, mes = desde.year + m // 12, m % 12 + 1
    return date(anio, mes, min(desde.day, calendar.monthrange(anio, mes)[1]))


def fechas_cuotas(primera, numero):
    return [sumar_meses(primera, i) for i in range(max(numero, 1))]


@transaction.atomic
def generar_cuotas(poliza):
    """(Re)arma las cuotas de la póliza a partir de la primera fecha de pago y el número de cuotas. Conserva la marca
    «pagada» de las cuotas que siguen existiendo (mismo número) y borra las que sobran."""
    numero = max(poliza.numero_cuotas or 1, 1)
    valor = (Decimal(poliza.prima_total or 0) / numero).quantize(Decimal('1'), rounding=ROUND_HALF_UP)
    existentes = {c.numero: c for c in poliza.cuotas.all()}
    for i, fecha in enumerate(fechas_cuotas(poliza.fecha_pago, numero), start=1):
        cuota = existentes.pop(i, None) or CuotaPoliza(poliza=poliza, numero=i)
        cuota.fecha, cuota.valor = fecha, valor
        cuota.save()
    CuotaPoliza.objects.filter(pk__in=[c.pk for c in existentes.values()]).delete()


def registrar_evento(vehiculo, tipo, anterior, nuevo, nota='', usuario=None):
    HistorialVehiculo.objects.create(vehiculo=vehiculo, tipo=tipo, anterior=str(anterior or '')[:200], nuevo=str(nuevo or '')[:200],
                                     nota=(nota or '')[:300], usuario=usuario if getattr(usuario, 'is_authenticated', False) else None)


def cambiar_estado(vehiculo, estado, fecha=None, nota='', usuario=None):
    """Cambia el estado del vehículo y deja el rastro en su historial. Lanza ValueError si el estado no existe."""
    nombres = dict(ESTADO_VEHICULO)
    if estado not in nombres:
        raise ValueError('Estado de vehículo no válido.')
    anterior = vehiculo.get_estado_display()
    vehiculo.estado = estado
    vehiculo.estado_fecha = None if estado == 'activo' else (fecha or date.today())
    vehiculo.estado_nota = '' if estado == 'activo' else (nota or '')[:300]
    vehiculo.save(update_fields=['estado', 'estado_fecha', 'estado_nota'])
    registrar_evento(vehiculo, 'estado', anterior, nombres[estado], nota, usuario)


def aviso_estado(vehiculo):
    """Texto para el asesor cuando la placa no está activa (o None si está activa)."""
    if not vehiculo.bloqueado_para_cotizar:
        return None
    desde = f' desde el {vehiculo.estado_fecha:%d/%m/%Y}' if vehiculo.estado_fecha else ''
    nota = f' Nota: {vehiculo.estado_nota.rstrip(".")}.' if vehiculo.estado_nota else ''
    return (f'La placa {vehiculo.placa} está marcada como «{vehiculo.get_estado_display()}»{desde}.{nota} '
            'Para cotizarla, primero actualiza su estado (por ejemplo, si llegó con un nuevo propietario).')


def asesor_de(usuario):
    """El asesor enlazado al usuario que está en el sistema (o None)."""
    return Asesor.objects.filter(usuario=usuario, is_active=True).first() if getattr(usuario, 'is_authenticated', False) else None


def _cuotas_del_plan(nombre):
    """«Pago mensual (12 cuotas)» → 12. Algunos portales cotizan la forma de pago como si fuera un plan."""
    m = re.search(r'(\d+)\s*cuotas', nombre or '', re.IGNORECASE)
    return int(m.group(1)) if m and 1 < int(m.group(1)) <= MAX_CUOTAS else None


def opciones_poliza(vehiculo):
    """Lo que el cliente puede elegir para convertir la solicitud en póliza: por aseguradora (en el orden del comparativo,
    de la más económica a la más costosa) cada plan cotizado con su valor. `comparado` marca el plan que se usa en el
    comparativo; la primera opción comparada es la más económica."""
    from core.policies.services.comparativo import construir  # import local: comparativo importa los bots

    grupos = []
    for fila in construir(vehiculo)['filas']:
        grupo = {'aseguradora': fila['aseguradora'], 'aseguradora_id': fila['aseguradora_id'], 'origen': fila['origen'],
                 'posicion': fila['posicion'], 'opciones': []}
        if fila['origen'] == 'bot':
            cotizacion = Cotizacion.objects.prefetch_related('planes').get(pk=fila['cotizacion_id'])
            planes = [(p.nombre_plan, p.prima_total) for p in cotizacion.planes.all() if p.prima_total and p.prima_total > 0]
            if not any(nombre == fila['etiqueta'] for nombre, _ in planes):
                planes.insert(0, (fila['etiqueta'], fila['valor']))
            for nombre, valor in planes:
                grupo['opciones'].append({'id': f'c{cotizacion.pk}|{nombre}', 'plan': nombre, 'valor': float(valor),
                                          'comparado': nombre == fila['etiqueta'], 'cuotas': _cuotas_del_plan(nombre)})
        else:
            externo = ValorExterno.objects.filter(vehiculo=vehiculo, aseguradora_id=fila['aseguradora_id']).order_by('-id').first()
            grupo['opciones'].append({'id': f'e{externo.pk}', 'plan': '', 'valor': float(externo.valor), 'comparado': True, 'cuotas': None})
        grupo['opciones'].sort(key=lambda o: (not o['comparado'], o['valor']))
        grupos.append(grupo)
    return grupos


def resolver_opcion(vehiculo, opcion):
    """Valida la opción elegida (que sea de ESTE vehículo) y devuelve los datos para la póliza, o lanza ValueError."""
    if opcion.startswith('c') and '|' in opcion:
        cotizacion_id, plan = opcion[1:].split('|', 1)
        cotizacion = (Cotizacion.objects.select_related('aseguradora', 'tipo_poliza').prefetch_related('planes')
                      .filter(pk=cotizacion_id if cotizacion_id.isdigit() else 0, vehiculo=vehiculo, estado_bot='completado').first())
        if cotizacion is None:
            raise ValueError('Esa cotización ya no está disponible.')
        valor = next((p.prima_total for p in cotizacion.planes.all() if p.nombre_plan == plan), None)
        if valor is None and plan and cotizacion.prima_total:
            valor = cotizacion.prima_total  # el plan del comparativo que el bot guardó solo como prima_total
        if not valor or valor <= 0:
            raise ValueError('Ese plan no tiene valor cotizado.')
        # Sin IVA, comisión y descuentos que capturó el bot corresponden al plan destacado (el de prima_total).
        mismos = valor == cotizacion.prima_total
        return {'aseguradora': cotizacion.aseguradora, 'cotizacion': cotizacion, 'plan': plan, 'prima_total': valor,
                'tipo_poliza': cotizacion.tipo_poliza, 'zona_circulacion_id': cotizacion.zona_circulacion_id or vehiculo.zona_circulacion_id,
                'valor_sin_iva': cotizacion.valor_sin_iva if mismos else 0, 'valor_comision': cotizacion.valor_comision if mismos else 0,
                'descuentos': cotizacion.descuentos if mismos else 0, 'fecha_descuento': cotizacion.fecha_descuento if mismos else None}
    if opcion.startswith('e') and opcion[1:].isdigit():
        externo = ValorExterno.objects.select_related('aseguradora').filter(pk=opcion[1:], vehiculo=vehiculo).first()
        if externo is None:
            raise ValueError('Ese valor ya no está disponible.')
        return {'aseguradora': externo.aseguradora, 'cotizacion': None, 'plan': '', 'prima_total': externo.valor, 'tipo_poliza': None,
                'zona_circulacion_id': vehiculo.zona_circulacion_id, 'valor_sin_iva': 0, 'valor_comision': 0, 'descuentos': 0,
                'fecha_descuento': None}
    raise ValueError('Elige la opción que escogió el cliente.')
