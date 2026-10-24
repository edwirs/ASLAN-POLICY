"""Respaldos de la base de datos con `pg_dump` (formato personalizado, comprimido).

- `crear(esquema=None)`: respaldo COMPLETO (todas las empresas + la lista de empresas) o de UNA empresa (su schema).
- `listar()`, `verificar()` (comprueba que el archivo se puede leer con pg_restore), `eliminar()`, `rotar()` (borra los viejos).
- Los archivos viven en `settings.RESPALDOS_DIR` (por defecto <proyecto>/respaldos, ignorada por git).

Restaurar NO se hace desde la web a propósito: es la única operación donde un error destruye datos. Las instrucciones paso a
paso están en el panel (`comando_restaurar`).
"""
import logging
import os
import re
import shutil
import subprocess
from datetime import datetime, timedelta

from django.conf import settings
from django.db import connection
from django.utils import timezone

from core.policies.services.panel import TZ_NEGOCIO

logger = logging.getLogger(__name__)

PATRON = re.compile(r'^aslan_(?P<etiqueta>[a-z0-9_]+)_(?P<fecha>\d{8})_(?P<hora>\d{6})\.dump$')
ETIQUETA_COMPLETO = 'completo'
MINIMO_A_CONSERVAR = 3   # la rotación nunca deja menos de estos respaldos


class RespaldoError(Exception):
    pass


def _ahora():
    """Hora de Colombia sin zona (el TIME_ZONE del servidor es otro: los nombres y las edades deben ser de aquí)."""
    return timezone.now().astimezone(TZ_NEGOCIO).replace(tzinfo=None)


def directorio():
    ruta = str(settings.RESPALDOS_DIR)
    os.makedirs(ruta, mode=0o700, exist_ok=True)
    return ruta


def _binario(nombre):
    """pg_dump/pg_restore de la MISMA versión mayor que el servidor (uno más viejo se niega a respaldar)."""
    if nombre == 'pg_dump' and settings.PG_DUMP:
        return settings.PG_DUMP
    with connection.cursor() as c:
        c.execute('SHOW server_version_num')
        mayor = int(c.fetchone()[0]) // 10000
    candidatos = [f'/Library/PostgreSQL/{mayor}/bin/{nombre}', f'/opt/homebrew/opt/postgresql@{mayor}/bin/{nombre}',
                  f'/usr/local/opt/postgresql@{mayor}/bin/{nombre}', f'/usr/lib/postgresql/{mayor}/bin/{nombre}',
                  f'/usr/pgsql-{mayor}/bin/{nombre}', f'/Applications/Postgres.app/Contents/Versions/{mayor}/bin/{nombre}']
    for ruta in candidatos:
        if os.path.exists(ruta):
            return ruta
    encontrado = shutil.which(nombre)
    if encontrado:
        return encontrado
    raise RespaldoError(f'No se encontró {nombre}. Instala las herramientas de PostgreSQL {mayor} o indica PG_DUMP en .env.secrets.')


def _conexion():
    d = settings.DATABASES['default']
    entorno = dict(os.environ, PGPASSWORD=str(d.get('PASSWORD') or ''))   # la clave va por entorno: no queda en la lista de procesos
    args = ['-h', str(d.get('HOST') or 'localhost'), '-p', str(d.get('PORT') or 5432), '-U', str(d.get('USER'))]
    return d['NAME'], args, entorno


def _info(nombre):
    m = PATRON.match(nombre)
    if not m:
        return None
    ruta = os.path.join(directorio(), nombre)
    try:
        estado = os.stat(ruta)
    except OSError:
        return None
    creado = datetime.strptime(m['fecha'] + m['hora'], '%Y%m%d%H%M%S')
    return {'nombre': nombre, 'etiqueta': m['etiqueta'], 'completo': m['etiqueta'] == ETIQUETA_COMPLETO, 'bytes': estado.st_size,
            'creado': creado, 'tamano': formato_tamano(estado.st_size), 'ruta': ruta}


def formato_tamano(n):
    for unidad in ('B', 'KB', 'MB', 'GB'):
        if n < 1024 or unidad == 'GB':
            return f'{n:.0f} {unidad}' if unidad == 'B' else f'{n:.1f} {unidad}'
        n /= 1024


def listar():
    """Respaldos existentes, del más reciente al más antiguo."""
    info = (_info(n) for n in os.listdir(directorio()))
    return sorted((i for i in info if i), key=lambda i: i['creado'], reverse=True)


def ruta_segura(nombre):
    """Ruta de un respaldo por su nombre, o None. Solo acepta nombres con el formato propio (evita rutas tipo ../../)."""
    info = _info(nombre) if isinstance(nombre, str) else None
    return info['ruta'] if info else None


def crear(esquema=None, retener=None):
    """Hace un respaldo y devuelve su info. `esquema=None`: base completa; `esquema='gali'`: solo esa empresa."""
    if esquema is not None and not re.fullmatch(r'[a-z][a-z0-9_]{0,62}', esquema):
        raise RespaldoError('Nombre de empresa no válido.')
    nombre_bd, conexion, entorno = _conexion()
    etiqueta = esquema or ETIQUETA_COMPLETO
    nombre = f'aslan_{etiqueta}_{_ahora():%Y%m%d_%H%M%S}.dump'
    destino = os.path.join(directorio(), nombre)
    comando = [_binario('pg_dump'), *conexion, '-Fc', '--no-owner', '--no-privileges', '-f', destino]
    if esquema:
        comando += ['-n', esquema]
    comando.append(nombre_bd)
    try:
        r = subprocess.run(comando, env=entorno, capture_output=True, text=True, timeout=1800)
    except subprocess.TimeoutExpired:
        raise RespaldoError('El respaldo tardó demasiado y se canceló.')
    if r.returncode != 0 or not os.path.exists(destino) or os.path.getsize(destino) == 0:
        if os.path.exists(destino):
            os.remove(destino)
        logger.error('pg_dump falló: %s', r.stderr[-800:])
        raise RespaldoError('pg_dump falló: ' + (r.stderr.strip().splitlines() or ['sin detalle'])[-1][:200])
    os.chmod(destino, 0o600)
    ok, detalle = verificar(nombre)
    if not ok:
        raise RespaldoError(f'El respaldo se creó pero no se pudo leer ({detalle}).')
    if retener is None:
        retener = settings.RESPALDOS_RETENCION_DIAS
    if retener:
        rotar(retener)
    logger.info('Respaldo creado: %s (%s)', nombre, formato_tamano(os.path.getsize(destino)))
    return _info(nombre)


def verificar(nombre):
    """(ok, detalle): pg_restore -l lista el contenido; si puede leerlo, el archivo no está corrupto."""
    ruta = ruta_segura(nombre)
    if not ruta:
        return False, 'archivo no encontrado'
    r = subprocess.run([_binario('pg_restore'), '-l', ruta], capture_output=True, text=True, timeout=120)
    if r.returncode != 0:
        return False, (r.stderr.strip().splitlines() or ['ilegible'])[-1][:160]
    tablas = sum(1 for linea in r.stdout.splitlines() if ' TABLE ' in linea and 'TABLE DATA' not in linea)
    return True, f'{tablas} tablas'


def eliminar(nombre):
    ruta = ruta_segura(nombre)
    if not ruta:
        raise RespaldoError('Respaldo no encontrado.')
    os.remove(ruta)


def rotar(dias):
    """Borra los respaldos más viejos que `dias`, pero siempre deja los MINIMO_A_CONSERVAR más recientes de cada tipo."""
    limite = _ahora() - timedelta(days=dias)
    por_etiqueta = {}
    for i in listar():
        por_etiqueta.setdefault(i['etiqueta'], []).append(i)
    borrados = 0
    for lista in por_etiqueta.values():
        for i in lista[MINIMO_A_CONSERVAR:]:
            if i['creado'] < limite:
                os.remove(i['ruta']); borrados += 1
    return borrados


def estado():
    """Para el semáforo del panel: último respaldo completo y qué tan viejo es."""
    completos = [i for i in listar() if i['completo']]
    if not completos:
        return {'ultimo': None, 'horas': None, 'nivel': 'rojo', 'mensaje': 'Nunca se ha hecho un respaldo completo.'}
    ultimo = completos[0]
    horas = (_ahora() - ultimo['creado']).total_seconds() / 3600
    nivel = 'verde' if horas < 30 else 'ambar' if horas < 24 * 4 else 'rojo'
    mensaje = {'verde': 'Respaldo al día.', 'ambar': 'El último respaldo completo tiene más de un día.', 'rojo': 'El último respaldo completo tiene varios días.'}[nivel]
    return {'ultimo': ultimo, 'horas': round(horas), 'nivel': nivel, 'mensaje': mensaje}


def comando_restaurar(nombre):
    """Instrucciones (texto) para restaurar a mano, sin riesgo de pisar la base en uso."""
    nombre_bd, conexion, _ = _conexion()
    base = ' '.join(conexion)
    return (f'# 1) Crea una base NUEVA y restaura ahí (nunca encima de la que está en uso):\n'
            f'createdb {base} {nombre_bd}_restaurada\n'
            f'pg_restore {base} -d {nombre_bd}_restaurada --no-owner respaldos/{nombre}\n'
            f'# 2) Revisa los datos en esa base y, si todo está bien, apunta DATABASE_URL a ella o copia lo que necesites.')
