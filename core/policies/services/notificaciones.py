"""Campana de notificaciones de la barra superior: información de los clientes para que el asesor actúe a tiempo.

Cada notificación es un ESTADO, no un mensaje: aparece mientras hay algo que hacer y desaparece sola (no hay «marcar
como leída»). Nada de bots ni de portales: solo clientes. En orden:

1. Pólizas por vencer: les quedan máximo 30 días de vigencia → hay que cotizar la renovación.
2. Solicitudes esperando decisión: ya tienen valores y el cliente no ha respondido (se resaltan las de más días).
3. Cumpleaños de clientes: hoy y los próximos días, para felicitarlos.
4. SOAT por vencer: vehículos de clientes con el SOAT a 30 días o menos (dato del comparativo).

Las etapas (1 y 2) son las mismas del listado de solicitudes (services/etapas.py), así los números coinciden con sus
filtros. El cálculo recorre todos los vehículos, por eso se guarda unos minutos por empresa.
"""
from datetime import timedelta
from zoneinfo import ZoneInfo

from django.core.cache import cache
from django.db.models import Q
from django.urls import reverse
from django.utils import timezone

from core.policies.models import Vehiculo
from core.policies.services.polizas import DIAS_AVISO_RENOVACION

DIAS_SIN_DECISION = 7       # desde cuántos días esperando se resalta una solicitud
DIAS_URGENTE_VENCE = 7      # una póliza que vence en estos días y no tiene la renovación cotizada es urgente
DIAS_CUMPLEANOS = 7         # cumpleaños de hoy y de los próximos días
DIAS_AVISO_SOAT = 30
SEGUNDOS_CACHE = 120
TZ_NEGOCIO = ZoneInfo('America/Bogota')   # «hoy» en Colombia, sin importar el TIME_ZONE del servidor
DIAS_SEMANA = ('lun', 'mar', 'mié', 'jue', 'vie', 'sáb', 'dom')


def _lista(nombres, maximo=3):
    nombres = list(nombres)
    if len(nombres) <= maximo:
        return ', '.join(nombres)
    return f'{", ".join(nombres[:maximo])} y {len(nombres) - maximo} más'


def _cuando(dias, fecha=None):
    if dias == 0:
        return 'hoy'
    if dias == 1:
        return 'mañana'
    if fecha is not None and dias < 7:
        return f'el {DIAS_SEMANA[fecha.weekday()]} {fecha.day}'
    return f'en {dias} días'


def _polizas_y_decisiones(hoy):
    from core.policies.services.etapas import etapas_por_vehiculo

    vehiculos = list(Vehiculo.objects.filter(is_active=True).select_related('tomador'))
    etapas = etapas_por_vehiculo(vehiculos, hoy=hoy) if vehiculos else {}
    lista = reverse('vehiculo_list')
    resultado = {}

    renovar = sorted(((v, etapas[v.pk]) for v in vehiculos if etapas[v.pk]['id'] == 'por_renovar'),
                     key=lambda x: x[1]['dias'] if x[1]['dias'] is not None else 999)
    if renovar:
        sin_cotizar = [(v, e) for v, e in renovar if 'renovación ya cotizada' not in e['detalle']]
        v, e = (sin_cotizar or renovar)[0]
        dias = e['dias'] or 0
        cuando = _cuando(dias, hoy + timedelta(days=dias))
        if len(renovar) == 1:
            texto = f'La póliza de {v.placa} vence {cuando}'
        else:
            texto = f'{len(renovar)} pólizas vencen en los próximos {DIAS_AVISO_RENOVACION} días'
        if sin_cotizar:
            detalle = (f'{len(sin_cotizar)} sin cotizar la renovación. La más próxima: {v.placa} '
                       f'({v.tomador.names}), vence {cuando}.' if len(renovar) > 1 else
                       f'{v.tomador.names} · {e["detalle"]}. Cotiza la renovación.')
        else:
            detalle = 'Todas ya tienen la renovación cotizada: falta la decisión del cliente.'
        resultado['renovar'] = {
            'tipo': 'renovar', 'icono': 'fa-rotate', 'color': 'danger' if sin_cotizar and dias <= DIAS_URGENTE_VENCE else 'orange',
            'urgente': bool(sin_cotizar) and dias <= DIAS_URGENTE_VENCE, 'texto': texto, 'detalle': detalle,
            'hora': f'vence {cuando}', 'url': f'{lista}?etapa=por_renovar'}

    esperando = sorted(((v, etapas[v.pk]) for v in vehiculos if etapas[v.pk]['id'] == 'esperando'),
                       key=lambda x: -(x[1]['dias'] or 0))
    if esperando:
        viejos = [x for x in esperando if (x[1]['dias'] or 0) >= DIAS_SIN_DECISION]
        v, e = esperando[0]
        dias = e['dias'] or 0
        texto = (f'{len(esperando)} solicitudes esperan la decisión del cliente' if len(esperando) > 1
                 else f'{v.placa} espera la decisión del cliente')
        hace_txt = 'hoy' if dias == 0 else 'ayer' if dias == 1 else f'hace {dias} días'
        if len(esperando) == 1:
            detalle = f'{v.tomador.names} · cotizado {hace_txt}. Llámalo para saber qué decidió.'
        else:
            detalle = (f'{len(viejos)} con más de {DIAS_SIN_DECISION} días. ' if viejos else '')
            detalle += f'La más antigua: {v.placa} ({v.tomador.names}), {hace_txt}.'
        resultado['esperando'] = {
            'tipo': 'esperando', 'icono': 'fa-hourglass-half', 'color': 'warning', 'urgente': False,
            'texto': texto, 'detalle': detalle, 'hora': f'{dias} días' if dias else 'hoy', 'url': f'{lista}?etapa=esperando'}
    return resultado


def _cumpleanos(hoy):
    from core.pos.models import Client

    dias = [hoy + timedelta(days=n) for n in range(DIAS_CUMPLEANOS)]
    filtro = Q()
    for d in dias:
        filtro |= Q(birthdate__month=d.month, birthdate__day=d.day)
    # Sin fecha real la ficha trae la del día en que se creó (valor por defecto): esas no se cuentan (nadie cotiza un
    # seguro con menos de 16 años), ni las empresas (NIT).
    clientes = list(Client.objects.filter(filtro, is_active=True, birthdate__year__lte=hoy.year - 16)
                    .exclude(document_type__abbreviation__iexact='NIT').only('id', 'names', 'dni', 'birthdate'))
    if not clientes:
        return None
    orden = {(d.month, d.day): i for i, d in enumerate(dias)}
    clientes.sort(key=lambda c: (orden[(c.birthdate.month, c.birthdate.day)], c.names))
    hoy_cumplen = [c for c in clientes if orden[(c.birthdate.month, c.birthdate.day)] == 0]
    url = reverse('client_list')

    def cuando(c):
        n = orden[(c.birthdate.month, c.birthdate.day)]
        return _cuando(n, dias[n])

    def edad(c):
        fecha = dias[orden[(c.birthdate.month, c.birthdate.day)]]
        return fecha.year - c.birthdate.year

    if len(clientes) == 1:
        c = clientes[0]
        texto = f'{c.names} cumple años {cuando(c)}' if not hoy_cumplen else f'Hoy cumple años {c.names}'
        return {'tipo': 'cumpleanos', 'icono': 'fa-cake-candles', 'color': 'pink', 'urgente': False, 'texto': texto,
                'detalle': f'Cumple {edad(c)} años. Un saludo a tiempo fideliza al cliente.',
                'hora': cuando(c), 'url': f'{url}?buscar={c.dni}'}
    texto = (f'{len(hoy_cumplen)} {"cliente cumple" if len(hoy_cumplen) == 1 else "clientes cumplen"} años hoy'
             if hoy_cumplen else f'{len(clientes)} clientes cumplen años esta semana')
    detalle = _lista(f'{c.names.split()[0].title()} ({cuando(c)})' for c in clientes)
    return {'tipo': 'cumpleanos', 'icono': 'fa-cake-candles', 'color': 'pink', 'urgente': False, 'texto': texto,
            'detalle': detalle, 'hora': 'hoy' if hoy_cumplen else cuando(clientes[0]),
            'url': f'{url}?buscar={hoy_cumplen[0].dni}' if len(hoy_cumplen) == 1 else url}


def _soat(hoy, url_lista):
    vehiculos = list(Vehiculo.objects.filter(is_active=True, estado='activo', soat_vencimiento__gte=hoy,
                                             soat_vencimiento__lte=hoy + timedelta(days=DIAS_AVISO_SOAT))
                     .select_related('tomador').order_by('soat_vencimiento'))
    if not vehiculos:
        return None
    v = vehiculos[0]
    dias = (v.soat_vencimiento - hoy).days
    cuando = _cuando(dias, v.soat_vencimiento)
    texto = (f'El SOAT de {v.placa} vence {cuando}' if len(vehiculos) == 1
             else f'{len(vehiculos)} vehículos con el SOAT por vencer')
    detalle = (f'{v.tomador.names}. Ofrécele la renovación del SOAT.' if len(vehiculos) == 1
               else f'El más próximo: {v.placa} ({v.tomador.names}), vence {cuando}.')
    return {'tipo': 'soat', 'icono': 'fa-id-card', 'color': 'info', 'urgente': False, 'texto': texto,
            'detalle': detalle, 'hora': f'vence {cuando}', 'url': f'{url_lista}?buscar={v.placa}' if len(vehiculos) == 1 else url_lista}


def _calcular(schema_name, hoy):
    clave = f'notificaciones:{schema_name}:{hoy.isoformat()}'
    datos = cache.get(clave)
    if datos is None:
        datos = _polizas_y_decisiones(hoy)
        datos['cumpleanos'] = _cumpleanos(hoy)
        datos['soat_solicitudes'] = _soat(hoy, reverse('vehiculo_list'))
        datos['soat_registrados'] = _soat(hoy, reverse('vehiculo_registrado_list'))
        cache.set(clave, datos, SEGUNDOS_CACHE)
    return datos


def notificaciones_de(usuario, schema_name):
    """Las notificaciones que le tocan a este usuario según sus permisos, en orden (máximo 4)."""
    datos = _calcular(schema_name, timezone.now().astimezone(TZ_NEGOCIO).date())
    lista = []
    if usuario.has_perm('policies.view_vehiculo'):
        lista += [datos.get('renovar'), datos.get('esperando')]
    if usuario.has_perm('pos.view_client'):
        lista.append(datos.get('cumpleanos'))
    if usuario.has_perm('policies.view_vehiculo_registrado'):
        lista.append(datos.get('soat_registrados'))
    elif usuario.has_perm('policies.view_vehiculo'):
        lista.append(datos.get('soat_solicitudes'))
    return [n for n in lista if n][:4]
