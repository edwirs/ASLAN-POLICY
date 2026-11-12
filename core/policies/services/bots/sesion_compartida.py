"""Sesión compartida de un portal que pide una persona para entrar (Mapfre: captcha «No soy un robot» + código SMS).

Una persona resuelve el captcha y el código UNA vez; el bot aprovecha esa misma sesión para cotizar, una tras otra, las
solicitudes que lleguen mientras está abierta, como haría un asesor que deja el portal abierto. Nada del ingreso se
automatiza: cuando la sesión vence se vuelve a pedir el captcha y el código.

Reglas:
- Una sola sesión por empresa (schema). Las solicitudes hacen fila (estado «pendiente», paso PASO_EN_FILA) y se cotizan
  por orden de llegada.
- La sesión se cierra (con «Cerrar sesión» del portal) a los N minutos de haber entrado: parámetro «minutos_sesion» de
  la credencial (10 por defecto; 0 = cerrar después de cada cotización). Una cotización no empieza en una sesión a la
  que le quedan menos de MARGEN_SEGUNDOS: se cierra y se vuelve a entrar.
- Si el portal la cerró antes (o cerraron la ventana), se detecta al volver al menú y se vuelve a pedir el ingreso.

Gunicorn puede tener varios procesos: para que no abran dos sesiones a la vez, el que atiende la fila toma un candado de
PostgreSQL (pg_try_advisory_lock) por empresa. La fila vive en la base de datos, así que la atiende quien tenga el
candado sin importar qué proceso recibió la solicitud.
"""
import logging
import threading
import time
import zlib
from datetime import timedelta

from django.db import connection
from django.utils import timezone
from django_tenants.utils import schema_context

logger = logging.getLogger(__name__)

PASO_EN_FILA = 'En fila: esperando la sesión de Mapfre'
MARGEN_SEGUNDOS = 120        # no empezar a cotizar en una sesión que está por vencer
SONDEO_SEGUNDOS = 2          # cada cuánto mira la fila mientras la sesión sigue abierta
CANDADO_CLASE = 73110        # primer número del candado de PostgreSQL (el segundo sale del schema)


def encolar(cotizacion_id, schema_name):
    """Pone la cotización en la fila de Mapfre de su empresa y se asegura de que alguien la esté atendiendo."""
    from core.policies.models import Cotizacion
    with schema_context(schema_name):
        Cotizacion.objects.filter(pk=cotizacion_id).update(
            estado_bot='pendiente', paso_bot=PASO_EN_FILA,
            mensaje_bot='En fila: se cotiza en cuanto termine la solicitud anterior de Mapfre.')
    asegurar_trabajador(schema_name)


def asegurar_trabajador(schema_name):
    threading.Thread(target=TrabajadorMapfre(schema_name).correr, daemon=True,
                     name=f'mapfre-{schema_name}').start()


class Candado:
    """Candado de PostgreSQL por empresa, en una conexión propia (dura lo que dure el trabajador)."""

    def __init__(self, schema_name):
        self.clave = zlib.crc32(f'mapfre:{schema_name}'.encode()) & 0x7FFFFFFF
        self.conexion = None

    def tomar(self):
        try:
            self.conexion = connection.get_new_connection(connection.get_connection_params())
            self.conexion.autocommit = True
            with self.conexion.cursor() as cursor:
                cursor.execute('SELECT pg_try_advisory_lock(%s, %s)', (CANDADO_CLASE, self.clave))
                if cursor.fetchone()[0]:
                    return True
        except Exception:
            logger.exception('Sesión de Mapfre: no se pudo pedir el candado.')
        self.soltar()
        return False

    def soltar(self):
        if self.conexion is None:
            return
        try:
            self.conexion.close()  # al cerrar la conexión PostgreSQL suelta el candado
        except Exception:
            pass
        self.conexion = None


class Sesion:
    """El navegador con la sesión abierta en el portal (vive dentro del hilo del trabajador)."""

    def __init__(self):
        self.browser = None
        self.page = None
        self.inicio = None          # time.time() en que se entró al portal
        self.minutos = 0
        self.credencial_id = None
        self.url_menu = None
        self.cotizaciones = 0

    @property
    def abierta(self):
        try:
            return self.page is not None and not self.page.is_closed() and self.inicio is not None
        except Exception:
            return False

    def segundos_restantes(self):
        if not self.abierta:
            return 0
        return self.inicio + self.minutos * 60 - time.time()

    def sirve_para(self, credencial_id):
        return self.abierta and self.credencial_id == credencial_id and self.segundos_restantes() >= MARGEN_SEGUNDOS

    def cerrar(self, bot=None, motivo=''):
        if self.browser is None:
            return
        if bot is not None and self.page is not None:
            bot._cerrar_sesion(self.page)
        try:
            self.browser.close()
        except Exception:
            pass
        if self.inicio is not None:
            logger.info('Sesión de Mapfre cerrada (%s) tras %s cotización(es) y %.0f s.', motivo or 'fin',
                        self.cotizaciones, time.time() - self.inicio)
        self.__init__()


class TrabajadorMapfre:
    def __init__(self, schema_name):
        self.schema_name = schema_name

    # ------------------------------------------------------------------ fila
    def _siguiente(self):
        """La solicitud más antigua de la fila. Las que llevan demasiado esperando no se toman: el listado las marca como
        interrumpidas (services/proceso.py) para que el asesor las reenvíe."""
        from core.policies.models import Cotizacion
        from core.policies.services.proceso import MINUTOS_INTERRUMPIDA
        with schema_context(self.schema_name):
            limite = timezone.now() - timedelta(minutes=MINUTOS_INTERRUMPIDA)
            return (Cotizacion.objects.filter(estado_bot='pendiente', paso_bot=PASO_EN_FILA, created_at__gte=limite)
                    .order_by('created_at', 'pk').values_list('pk', flat=True).first())

    # ------------------------------------------------------------------ bucle
    def correr(self):
        candado = Candado(self.schema_name)
        while candado.tomar():
            try:
                self._atender()
            except Exception:
                logger.exception('Sesión de Mapfre (%s): el trabajador falló.', self.schema_name)
            finally:
                candado.soltar()
            # Pudo llegar una solicitud justo mientras se soltaba el candado: si hay, se vuelve a tomar.
            if self._siguiente() is None:
                return

    def _atender(self):
        from playwright.sync_api import sync_playwright

        sesion = Sesion()
        with sync_playwright() as playwright:
            try:
                while True:
                    cotizacion_id = self._siguiente()
                    if cotizacion_id is None:
                        if not sesion.abierta:
                            return
                        if sesion.segundos_restantes() <= 0:
                            sesion.cerrar(self._ultimo_bot, 'venció el tiempo de la sesión')
                            return
                        time.sleep(SONDEO_SEGUNDOS)
                        continue
                    self._cotizar(playwright, sesion, cotizacion_id)
                    if sesion.minutos <= 0:
                        sesion.cerrar(self._ultimo_bot, 'sesión de una sola cotización')
            finally:
                sesion.cerrar(self._ultimo_bot, 'fin del trabajador')

    _ultimo_bot = None

    def _cotizar(self, playwright, sesion, cotizacion_id):
        from core.policies.models import Cotizacion
        from core.policies.services.bots.base import registrar_error
        from core.policies.services.bots.mapfre import MapfreBot

        with schema_context(self.schema_name):
            cotizacion = Cotizacion.objects.get(pk=cotizacion_id)
            # Se marca enseguida: así no la vuelve a tomar la fila aunque el bot falle al construirse.
            Cotizacion.objects.filter(pk=cotizacion_id).update(estado_bot='en_proceso', paso_bot='Preparación del bot',
                                                                mensaje_bot=None)
            try:
                bot = MapfreBot(cotizacion, headless=False, schema_name=self.schema_name)
            except Exception as exc:
                logger.exception('Sesión de Mapfre: no se pudo preparar la cotización #%s', cotizacion_id)
                registrar_error(cotizacion, exc, 'Preparación del bot', self.schema_name)
                return
        self._ultimo_bot = bot
        bot.cotizar_en_sesion(playwright, sesion)
