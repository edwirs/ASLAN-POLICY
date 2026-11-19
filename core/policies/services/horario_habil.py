"""Horario hábil de Colombia para enviar correos a los clientes.

Lunes a viernes de 8:00 a. m. a 5:00 p. m. y sábados de 8:00 a. m. a 12:00 m. (hora de Colombia). Domingos y festivos
no hay envíos. El límite es exclusivo: a las 4:59 p. m. se envía; desde las 5:00 p. m. pasa al siguiente día hábil.

Los festivos se calculan (no hay que cargarlos cada año): los fijos, los que la Ley Emiliani (Ley 51 de 1983) traslada
al lunes siguiente y los que dependen de la Semana Santa.
"""
from datetime import date, datetime, time, timedelta
from functools import lru_cache
from zoneinfo import ZoneInfo

from django.utils import timezone

TZ_COLOMBIA = ZoneInfo('America/Bogota')
# Día de la semana (lunes = 0) -> (apertura, cierre). Sin entrada: no se envía ese día.
HORARIO = {
    0: (time(8, 0), time(17, 0)),
    1: (time(8, 0), time(17, 0)),
    2: (time(8, 0), time(17, 0)),
    3: (time(8, 0), time(17, 0)),
    4: (time(8, 0), time(17, 0)),
    5: (time(8, 0), time(12, 0)),
}
DIAS = ('lunes', 'martes', 'miércoles', 'jueves', 'viernes', 'sábado', 'domingo')

FESTIVOS_FIJOS = ((1, 1), (5, 1), (7, 20), (8, 7), (12, 8), (12, 25))
# Se trasladan al lunes siguiente si no caen en lunes (Ley Emiliani).
FESTIVOS_EMILIANI = ((1, 6), (3, 19), (6, 29), (8, 15), (10, 12), (11, 1), (11, 11))


def _domingo_de_pascua(anio):
    """Algoritmo de Meeus/Jones/Butcher (calendario gregoriano)."""
    a, b, c = anio % 19, anio // 100, anio % 100
    d, e = b // 4, b % 4
    f = (b + 8) // 25
    g = (b - f + 1) // 3
    h = (19 * a + b - d - g + 15) % 30
    i, k = c // 4, c % 4
    l = (32 + 2 * e + 2 * i - h - k) % 7
    m = (a + 11 * h + 22 * l) // 451
    mes = (h + l - 7 * m + 114) // 31
    dia = (h + l - 7 * m + 114) % 31 + 1
    return date(anio, mes, dia)


def _al_lunes(dia):
    return dia + timedelta(days=(7 - dia.weekday()) % 7)


@lru_cache(maxsize=32)
def festivos(anio):
    """Conjunto de fechas festivas de Colombia en `anio`."""
    pascua = _domingo_de_pascua(anio)
    dias = {date(anio, m, d) for m, d in FESTIVOS_FIJOS}
    dias |= {_al_lunes(date(anio, m, d)) for m, d in FESTIVOS_EMILIANI}
    dias |= {pascua - timedelta(days=3), pascua - timedelta(days=2)}  # Jueves y Viernes Santo
    # Ascensión (+39), Corpus Christi (+60) y Sagrado Corazón (+68): se trasladan al lunes.
    dias |= {_al_lunes(pascua + timedelta(days=n)) for n in (39, 60, 68)}
    return frozenset(dias)


def es_festivo(dia):
    return dia in festivos(dia.year)


def _horario_del_dia(dia):
    """(apertura, cierre) del día, o None si no es hábil (domingo o festivo)."""
    if es_festivo(dia):
        return None
    return HORARIO.get(dia.weekday())


def ahora_colombia():
    return timezone.now().astimezone(TZ_COLOMBIA)


def en_horario(momento=None):
    """¿`momento` (aware; por defecto ahora) está dentro del horario hábil?"""
    local = (momento or timezone.now()).astimezone(TZ_COLOMBIA)
    horario = _horario_del_dia(local.date())
    return bool(horario) and horario[0] <= local.time() < horario[1]


def siguiente_hora_habil(momento=None):
    """El mismo `momento` si está en horario; si no, la próxima apertura (aware, en hora de Colombia)."""
    local = (momento or timezone.now()).astimezone(TZ_COLOMBIA)
    if en_horario(local):
        return local
    dia = local.date()
    horario = _horario_del_dia(dia)
    if horario and local.time() < horario[0]:
        return datetime.combine(dia, horario[0], tzinfo=TZ_COLOMBIA)
    for _ in range(30):  # nunca hay tantos días seguidos sin horario; es solo un tope de seguridad
        dia += timedelta(days=1)
        horario = _horario_del_dia(dia)
        if horario:
            return datetime.combine(dia, horario[0], tzinfo=TZ_COLOMBIA)
    raise RuntimeError('No se encontró un día hábil en los próximos 30 días.')


def texto_fecha(momento):
    """«martes 25/11/2026 a las 8:00 a. m.» en hora de Colombia."""
    local = momento.astimezone(TZ_COLOMBIA)
    hora = local.hour % 12 or 12
    sufijo = 'm.' if (local.hour, local.minute) == (12, 0) else ('a. m.' if local.hour < 12 else 'p. m.')
    return f'{DIAS[local.weekday()]} {local:%d/%m/%Y} a las {hora}:{local:%M} {sufijo}'


def texto_horario():
    return 'lunes a viernes de 8:00 a. m. a 5:00 p. m. y sábados de 8:00 a. m. a 12:00 m. (hora de Colombia), sin festivos'
