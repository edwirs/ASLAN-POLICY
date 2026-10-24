"""Datos del panel de inicio (dashboard) de seguros: qué se ha cotizado, con qué resultado y qué requiere atención.

Todo se calcula en la zona horaria del negocio (Colombia) para que «hoy» y los cortes por día coincidan con lo que el
asesor ve en su reloj, sin importar el TIME_ZONE del servidor.
"""
from collections import Counter, defaultdict
from datetime import datetime, time, timedelta
from zoneinfo import ZoneInfo

from django.utils import timezone

from core.policies.choices import ERROR_BOT_TIPO
from core.policies.models import Aseguradora, AseguradoraCredencial, Asesor, Cotizacion, Vehiculo
from core.policies.services.bots import BOTS_DISPONIBLES
from core.policies.services.credenciales import faltantes
from core.policies.services.proceso import resumen_por_vehiculo
from core.pos.models import Client

TZ_NEGOCIO = ZoneInfo('America/Bogota')
PERIODOS = (7, 30, 90)
PERIODO_POR_DEFECTO = 30

# Errores que no son una falla del bot: el portal o la aseguradora no permiten cotizar ahora (o ese caso).
AVISOS = ('no_cotizable', 'saturado', 'clave_vencida')
EN_CURSO = ('pendiente', 'en_proceso', 'esperando_confirmacion')
MESES = ['ene', 'feb', 'mar', 'abr', 'may', 'jun', 'jul', 'ago', 'sep', 'oct', 'nov', 'dic']
ETIQUETA_ERROR = dict(ERROR_BOT_TIPO)


def _resultado(estado_bot, error_tipo):
    """ok / aviso / error / curso / otros, para contar igual en todas las gráficas."""
    if estado_bot == 'completado':
        return 'ok'
    if estado_bot == 'error':
        return 'aviso' if error_tipo in AVISOS else 'error'
    if estado_bot in EN_CURSO:
        return 'curso'
    return 'otros'


def _inicio_de_dia(dia):
    return datetime.combine(dia, time.min, tzinfo=TZ_NEGOCIO)


def _variacion(actual, anterior):
    """% de cambio frente al período anterior (None si no hay base para comparar)."""
    if not anterior:
        return None
    return round((actual - anterior) * 100 / anterior)


def _tasa(ok, error):
    total = ok + error
    return round(ok * 100 / total) if total else None


def normalizar_periodo(valor):
    try:
        dias = int(valor)
    except (TypeError, ValueError):
        return PERIODO_POR_DEFECTO
    return dias if dias in PERIODOS else PERIODO_POR_DEFECTO


def _meses_atras(hoy, n):
    """Primer día de cada uno de los últimos `n` meses (el actual incluido), del más antiguo al más reciente."""
    año, mes = hoy.year, hoy.month
    inicios = []
    for _ in range(n):
        inicios.append(hoy.replace(year=año, month=mes, day=1))
        mes -= 1
        if mes == 0:
            mes, año = 12, año - 1
    return inicios[::-1]


def datos_panel(dias=PERIODO_POR_DEFECTO):
    ahora = timezone.now().astimezone(TZ_NEGOCIO)
    hoy = ahora.date()
    dias = normalizar_periodo(dias)
    desde = hoy - timedelta(days=dias - 1)
    ini = _inicio_de_dia(desde)
    ini_previo = _inicio_de_dia(desde - timedelta(days=dias))

    # --- Cotizaciones del período y del anterior (para las variaciones) ---
    filas = list(Cotizacion.objects.filter(created_at__gte=ini_previo).values_list(
        'created_at', 'estado_bot', 'error_tipo', 'aseguradora__name', 'asesor__username', 'asesor__names', 'prima_total'))
    actual, previo = Counter(), Counter()
    por_dia = defaultdict(Counter)
    por_aseguradora = defaultdict(Counter)
    por_asesor = defaultdict(Counter)
    causas = Counter()
    primas = defaultdict(list)
    for creada, estado, tipo, aseguradora, usuario, nombres, prima in filas:
        res = _resultado(estado, tipo)
        creada = creada.astimezone(TZ_NEGOCIO)
        if creada < ini:
            previo[res] += 1
            continue
        actual[res] += 1
        por_dia[creada.date()][res] += 1
        por_aseguradora[aseguradora][res] += 1
        por_asesor[(nombres or usuario)][res] += 1
        if res == 'error':
            causas[tipo or 'inesperado'] += 1
        if res == 'ok' and prima:
            primas[aseguradora].append(float(prima))

    solicitudes = Vehiculo.objects.filter(created_at__gte=ini_previo).values_list('created_at', flat=True)
    sol_actual = sum(1 for c in solicitudes if c.astimezone(TZ_NEGOCIO) >= ini)
    sol_previo = len(solicitudes) - sol_actual

    # --- Series de las gráficas ---
    fechas = [desde + timedelta(days=i) for i in range(dias)]
    serie_dias = {
        'categorias': [f'{f.day} {MESES[f.month - 1]}' for f in fechas],
        'ok': [por_dia[f]['ok'] for f in fechas],
        'aviso': [por_dia[f]['aviso'] for f in fechas],
        'error': [por_dia[f]['error'] for f in fechas],
    }
    nombres_aseg = sorted(por_aseguradora, key=lambda n: (-sum(por_aseguradora[n].values()), n))
    serie_aseguradoras = {
        'categorias': nombres_aseg,
        'ok': [por_aseguradora[n]['ok'] for n in nombres_aseg],
        'aviso': [por_aseguradora[n]['aviso'] for n in nombres_aseg],
        'error': [por_aseguradora[n]['error'] for n in nombres_aseg],
    }
    primas_prom = sorted(((n, round(sum(v) / len(v))) for n, v in primas.items()), key=lambda x: x[1])
    inicios_mes = _meses_atras(hoy, 6)
    sol_mes = Counter()
    for c in Vehiculo.objects.filter(created_at__gte=_inicio_de_dia(inicios_mes[0])).values_list('created_at', flat=True):
        c = c.astimezone(TZ_NEGOCIO)
        sol_mes[(c.year, c.month)] += 1
    ok_mes = Counter()
    for c in Cotizacion.objects.filter(created_at__gte=_inicio_de_dia(inicios_mes[0]), estado_bot='completado').values_list('created_at', flat=True):
        c = c.astimezone(TZ_NEGOCIO)
        ok_mes[(c.year, c.month)] += 1
    serie_meses = {
        'categorias': [MESES[m.month - 1].capitalize() + (f' {m.year}' if m.year != hoy.year else '') for m in inicios_mes],
        'solicitudes': [sol_mes[(m.year, m.month)] for m in inicios_mes],
        'completadas': [ok_mes[(m.year, m.month)] for m in inicios_mes],
    }
    asesores = sorted(por_asesor.items(), key=lambda kv: -(kv[1]['ok'] + kv[1]['aviso'] + kv[1]['error']))[:5]
    top_asesores = [{'nombre': n, 'ok': c['ok'], 'total': sum(c.values())} for n, c in asesores]

    # --- Qué requiere atención ---
    claves = list(AseguradoraCredencial.objects.filter(is_active=True, requiere_cambio_clave=True)
                  .values_list('aseguradora__name', flat=True).distinct())
    esperando = Cotizacion.objects.filter(estado_bot='esperando_confirmacion').count()
    con_bot = [a for a in Aseguradora.objects.filter(is_active=True) if a.name in BOTS_DISPONIBLES]
    incompletas = [{'nombre': a.name, 'faltan': faltantes(a)} for a in con_bot if faltantes(a)]
    atencion = len(claves) + (1 if esperando else 0) + len(incompletas)

    # --- Últimas solicitudes con su avance ---
    ultimas_v = list(Vehiculo.objects.select_related('tomador').order_by('-created_at')[:8])
    avance = resumen_por_vehiculo(ultimas_v) if ultimas_v else {}
    ultimas = [{
        'id': v.pk, 'placa': v.placa, 'tomador': v.tomador.names, 'cero_km': v.es_cero_km,
        'fecha': v.created_at.astimezone(TZ_NEGOCIO),
        'ok': avance.get(v.pk, {}).get('ok', 0), 'total': avance.get(v.pk, {}).get('total', 0),
        'estado': avance.get(v.pk, {}).get('estado', 'sin_cotizar'),
    } for v in ultimas_v]

    primas_todas = [p for lista in primas.values() for p in lista]
    return {
        'dias': dias, 'periodos': PERIODOS, 'desde': desde, 'hasta': hoy,
        'kpi': {
            'solicitudes': sol_actual, 'solicitudes_var': _variacion(sol_actual, sol_previo),
            'completadas': actual['ok'], 'completadas_var': _variacion(actual['ok'], previo['ok']),
            'tasa': _tasa(actual['ok'], actual['error']), 'tasa_previa': _tasa(previo['ok'], previo['error']),
            'avisos': actual['aviso'], 'errores': actual['error'], 'en_curso': actual['curso'],
            'total': sum(actual.values()),
            'atencion': atencion,
        },
        'resumen': {
            'vehiculos': Vehiculo.objects.count(),
            'clientes': Client.objects.count(),
            'asesores': Asesor.objects.filter(is_active=True).count(),
            'aseguradoras_bot': len(con_bot), 'aseguradoras_bot_total': len(BOTS_DISPONIBLES),
            'prima_promedio': round(sum(primas_todas) / len(primas_todas)) if primas_todas else None,
        },
        'atencion': {
            'claves': claves, 'esperando': esperando, 'incompletas': incompletas,
            'causas': [{'tipo': ETIQUETA_ERROR.get(t, t), 'n': n} for t, n in causas.most_common(4)],
        },
        'ultimas': ultimas,
        'top_asesores': top_asesores,
        'graficas': {
            'dias': serie_dias,
            'aseguradoras': serie_aseguradoras,
            'estados': [
                {'name': 'Completadas', 'y': actual['ok'], 'color': '#28a745'},
                {'name': 'Avisos del portal', 'y': actual['aviso'], 'color': '#ffc107'},
                {'name': 'Con error', 'y': actual['error'], 'color': '#dc3545'},
                {'name': 'En curso', 'y': actual['curso'], 'color': '#2ab1ee'},
                {'name': 'Canceladas', 'y': actual['otros'], 'color': '#adb5bd'},
            ],
            'primas': {'categorias': [n for n, _ in primas_prom], 'valores': [v for _, v in primas_prom]},
            'meses': serie_meses,
        },
    }
