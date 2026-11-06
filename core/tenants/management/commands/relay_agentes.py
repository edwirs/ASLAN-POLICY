"""Relevo entre los bots (en este servidor) y los «Agente ASLAN» de las oficinas.

    venv/bin/python manage.py relay_agentes            # escucha en 127.0.0.1:AGENTE_RELAY_PUERTO (8008)

En producción corre como servicio (deploy/agente/aslan-relay.service) y nginx le pasa /agente/ws/ (wss en el 443).

Rutas:
- /agente/ws/control          el agente se mantiene conectado aquí (llave en «Authorization: Bearer …»), da señal de
                               vida y recibe la orden de abrir un navegador.
- /agente/ws/datos/<sid>      el agente abre una conexión por cada navegador que le piden; por ella van los mensajes
                               de Playwright.
- /interno/sesion/<agente>    SOLO para los bots de este servidor (clave interna, nunca a través de nginx): el bot se
                               conecta aquí como si fuera un navegador remoto y el relevo une sus mensajes con los
                               del agente.
"""
import asyncio
import hmac
import json
import logging
import secrets
from http import HTTPStatus
from urllib.parse import parse_qs, urlsplit

from asgiref.sync import sync_to_async
from django.conf import settings
from django.core.management.base import BaseCommand
from django.db import close_old_connections
from django.utils import timezone

logger = logging.getLogger('relay_agentes')

SEGUNDOS_ESPERA_AGENTE = 45   # lo que espera un bot a que el agente abra el navegador
SEGUNDOS_HOLA = 15


def _db(funcion):
    """Corre una función con el ORM fuera del bucle de asyncio (Django no deja usarlo dentro)."""
    def envoltura(*args, **kwargs):
        close_old_connections()
        try:
            return funcion(*args, **kwargs)
        finally:
            close_old_connections()
    return sync_to_async(envoltura, thread_sensitive=True)


@_db
def _autenticar(llave):
    from core.tenants.agentes import por_llave
    agente = por_llave(llave)
    return (agente.pk, agente.nombre, agente.empresa.schema_name, agente.empresa.name) if agente else None


@_db
def _marcar(agente_id, conectado, **campos):
    """Actualiza la señal del agente. Devuelve False si ya lo desvincularon (hay que cortarlo)."""
    from core.tenants.models import AgenteLocal
    if conectado:
        return AgenteLocal.objects.filter(pk=agente_id, activo=True).update(
            conectado=True, ultima_senal=timezone.now(), **campos) > 0
    AgenteLocal.objects.filter(pk=agente_id).update(conectado=False, **campos)
    return True


@_db
def _apagar_todos(excepto=()):
    from core.tenants.models import AgenteLocal
    AgenteLocal.objects.filter(conectado=True).exclude(pk__in=list(excepto)).update(conectado=False)


def _llave(request):
    valor = request.headers.get('Authorization', '')
    return valor[7:].strip() if valor.lower().startswith('bearer ') else ''


def _ip(conexion):
    cabeceras = conexion.request.headers
    reenviada = cabeceras.get('X-Forwarded-For', '').split(',')[0].strip()
    return (cabeceras.get('X-Real-IP') or reenviada or (conexion.remote_address or ('',))[0])[:45]


class Relevo:
    def __init__(self):
        self.controles = {}      # agente_id -> conexión de control
        self.pendientes = {}     # sid -> (agente_id, Future con la conexión de datos)

    # ---------------------------------------------------------------- filtro previo (antes del handshake)
    def filtrar(self, conexion, request):
        ruta = urlsplit(request.path).path
        if ruta.startswith('/interno/'):
            # Los bots llegan directo a 127.0.0.1: algo que pasó por nginx trae X-Forwarded-For / X-Real-IP.
            if request.headers.get('X-Forwarded-For') or request.headers.get('X-Real-IP'):
                return conexion.respond(HTTPStatus.FORBIDDEN, 'Prohibido\n')
            clave = request.headers.get('X-Relay-Clave', '')
            from core.tenants.agentes import clave_relay
            if not hmac.compare_digest(clave.encode(), clave_relay().encode()):
                return conexion.respond(HTTPStatus.FORBIDDEN, 'Prohibido\n')
            return None
        if ruta == '/agente/ws/control' or ruta.startswith('/agente/ws/datos/'):
            if not _llave(request):
                return conexion.respond(HTTPStatus.UNAUTHORIZED, 'Falta la llave del agente\n')
            return None
        return conexion.respond(HTTPStatus.NOT_FOUND, 'No existe\n')

    # ---------------------------------------------------------------- despachador
    async def atender(self, conexion):
        ruta = urlsplit(conexion.request.path).path
        try:
            if ruta == '/agente/ws/control':
                await self._control(conexion)
            elif ruta.startswith('/agente/ws/datos/'):
                await self._datos(conexion, ruta.rsplit('/', 1)[-1])
            elif ruta.startswith('/interno/sesion/'):
                await self._sesion_bot(conexion)
        except Exception:
            logger.exception('Error atendiendo %s', ruta)
            await conexion.close(1011, 'Error interno del relevo')

    # ---------------------------------------------------------------- agente: conexión de control
    async def _control(self, conexion):
        datos = await _autenticar(_llave(conexion.request))
        if datos is None:
            await conexion.close(4401, 'Llave inválida o equipo desvinculado')
            return
        agente_id, nombre, schema, empresa = datos
        try:
            hola = json.loads(await asyncio.wait_for(conexion.recv(), SEGUNDOS_HOLA))
        except (asyncio.TimeoutError, ValueError):
            await conexion.close(4400, 'Se esperaba el saludo del agente')
            return
        anterior = self.controles.get(agente_id)
        if anterior is not None:
            await anterior.close(4409, 'El mismo equipo se conectó de nuevo')
        self.controles[agente_id] = conexion
        await _marcar(agente_id, True, version=str(hola.get('version', ''))[:20],
                      version_playwright=str(hola.get('playwright', ''))[:20], sistema=str(hola.get('sistema', ''))[:80],
                      navegador=str(hola.get('navegador', ''))[:40], ip=_ip(conexion))
        from core.tenants.agentes import version_playwright_local
        await conexion.send(json.dumps({
            'tipo': 'bienvenida', 'equipo': nombre, 'empresa': empresa,
            'playwright_servidor': version_playwright_local(), 'version_minima': settings.AGENTE_VERSION_MINIMA,
            'descarga': settings.AGENTE_DESCARGA_URL,
        }))
        logger.info('Agente #%s «%s» (%s) conectado desde %s', agente_id, nombre, schema, _ip(conexion))
        try:
            async for mensaje in conexion:
                try:
                    tipo = json.loads(mensaje).get('tipo')
                except (ValueError, AttributeError):
                    continue
                if tipo == 'latido':
                    if not await _marcar(agente_id, True):
                        await conexion.close(4401, 'Equipo desvinculado')
                        break
                    await conexion.send(json.dumps({'tipo': 'latido_ok'}))
        finally:
            if self.controles.get(agente_id) is conexion:
                del self.controles[agente_id]
                await _marcar(agente_id, False)
                for sid, (dueno, futuro) in list(self.pendientes.items()):
                    if dueno == agente_id and not futuro.done():
                        futuro.set_exception(ConnectionError('El agente se desconectó'))
            logger.info('Agente #%s «%s» desconectado', agente_id, nombre)

    # ---------------------------------------------------------------- agente: un navegador
    async def _datos(self, conexion, sid):
        datos = await _autenticar(_llave(conexion.request))
        pendiente = self.pendientes.get(sid)
        if datos is None or pendiente is None or pendiente[0] != datos[0] or pendiente[1].done():
            await conexion.close(4403, 'Sesión desconocida')
            return
        pendiente[1].set_result(conexion)
        await conexion.wait_closed()   # el bot la usa (ver _sesion_bot); esta tarea solo la mantiene viva

    # ---------------------------------------------------------------- bot: pide un navegador del agente
    async def _sesion_bot(self, conexion):
        agente_id = int(urlsplit(conexion.request.path).path.rsplit('/', 1)[-1])
        headless = parse_qs(urlsplit(conexion.request.path).query).get('headless', ['1'])[0] != '0'
        control = self.controles.get(agente_id)
        if control is None:
            await conexion.close(4404, 'El agente de la oficina no está conectado')
            return
        sid = secrets.token_urlsafe(16)
        futuro = asyncio.get_running_loop().create_future()
        self.pendientes[sid] = (agente_id, futuro)
        try:
            await control.send(json.dumps({'tipo': 'abrir', 'sid': sid, 'headless': headless}))
            datos = await asyncio.wait_for(futuro, SEGUNDOS_ESPERA_AGENTE)
        except (asyncio.TimeoutError, ConnectionError) as exc:
            logger.warning('Agente #%s no abrió el navegador (sesión %s): %s', agente_id, sid, exc or 'sin respuesta')
            await conexion.close(4408, 'El agente no abrió el navegador a tiempo')
            return
        finally:
            self.pendientes.pop(sid, None)
        logger.info('Sesión %s: bot unido con el agente #%s (headless=%s)', sid, agente_id, headless)
        await self._unir(conexion, datos)
        logger.info('Sesión %s terminada', sid)

    @staticmethod
    async def _unir(a, b):
        async def pasar(origen, destino):
            try:
                async for mensaje in origen:
                    await destino.send(mensaje)
            except Exception:
                pass
        tareas = [asyncio.ensure_future(pasar(a, b)), asyncio.ensure_future(pasar(b, a))]
        await asyncio.wait(tareas, return_when=asyncio.FIRST_COMPLETED)
        for tarea in tareas:
            tarea.cancel()
        await asyncio.gather(a.close(), b.close(), return_exceptions=True)

    # ---------------------------------------------------------------- mantenimiento
    async def vigilar(self):
        """Si el relevo se reinició o un agente quedó marcado sin conexión real, lo corrige cada minuto."""
        while True:
            try:
                await _apagar_todos(excepto=tuple(self.controles))
            except Exception:
                logger.exception('No se pudo actualizar el estado de los agentes')
            await asyncio.sleep(60)


class Command(BaseCommand):
    help = 'Relevo entre los bots y los Agente ASLAN de las oficinas (escucha solo en 127.0.0.1).'

    def add_arguments(self, parser):
        parser.add_argument('--puerto', type=int, default=settings.AGENTE_RELAY_PUERTO)

    def handle(self, *args, **opciones):
        logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)s %(name)s: %(message)s')
        asyncio.run(self._correr(opciones['puerto']))

    async def _correr(self, puerto):
        from websockets.asyncio.server import serve

        relevo = Relevo()
        await _apagar_todos()
        async with serve(relevo.atender, '127.0.0.1', puerto, process_request=relevo.filtrar, max_size=None,
                         ping_interval=20, ping_timeout=40, compression=None) as servidor:
            logger.info('Relevo de agentes escuchando en 127.0.0.1:%s', puerto)
            vigia = asyncio.ensure_future(relevo.vigilar())
            try:
                await servidor.serve_forever()
            finally:
                vigia.cancel()
