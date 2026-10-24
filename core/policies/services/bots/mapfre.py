"""Bot de cotización para Mapfre (portal de intermediarios, ofiVirtualWeb, JSF/PrimeFaces).

ESTADO: EN CONSTRUCCIÓN. Solo el inicio de sesión está verificado contra la pantalla pública; lo que ocurre después de
entrar (código SMS, «Cotización Emisión», «Autos cotización múltiple», formulario) se mapea con una sesión real y NO está
conectado todavía. Por eso este bot no está en BOTS_DISPONIBLES: no se lanza desde «Cotizar» hasta que esté probado de
punta a punta (se prueba con `manage.py cotizar_mapfre`).

Lo que el portal exige a una persona (el bot NO lo hace por su cuenta):
  1. reCAPTCHA «No soy un robot»: lo marca el asesor en la ventana de Mapfre (por eso este bot corre con navegador
     VISIBLE, ver REQUIERE_NAVEGADOR_VISIBLE). El bot solo espera a que quede marcado y entonces pulsa «Ingresar».
  2. Código de 6 dígitos que Mapfre envía por SMS al celular registrado: el asesor lo escribe en la modal de la
     plataforma (Cotizacion.verificacion_bot = 'codigo') y el bot lo digita en el portal.

Sesiones: al terminar (bien o mal) SIEMPRE se cierra sesión.
"""
import logging
import os
import re

from django.conf import settings
from django.db import connection
from django.utils import timezone
from django_tenants.utils import schema_context
from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeoutError

os.environ.setdefault('DJANGO_ALLOW_ASYNC_UNSAFE', 'true')

from core.policies.services.bots.base import (  # noqa: E402
    PASO_LOGIN,
    BotAutenticacionError,
    BotCancelado,
    BotPortalError,
    BotTimeout,
    RegistroErrorMixin,
    exigir_clave_al_dia,
    normalizar_texto,
)

logger = logging.getLogger(__name__)

SEGUNDOS_PARA_CAPTCHA = 240
SEGUNDOS_PARA_CODIGO = 300


class MapfreBot(RegistroErrorMixin):
    """Cotiza en Mapfre. Uso: MapfreBot(cotizacion, headless=False).run()"""

    # El reCAPTCHA lo marca una persona: el navegador tiene que verse (lo lee el runner).
    REQUIERE_NAVEGADOR_VISIBLE = True

    def __init__(self, cotizacion, headless=False):
        self.cotizacion = cotizacion
        self.vehiculo = cotizacion.vehiculo
        self._foto_vehiculo()
        self.tomador = self.vehiculo.tomador
        self.headless = headless
        self.credencial = self._get_credencial()
        # Dentro de sync_playwright Django usa otra conexión (schema public).
        self.schema_name = connection.schema_name

    def _get_credencial(self):
        credencial = self.cotizacion.aseguradora.credenciales.filter(is_active=True).order_by('-id').first()
        if credencial is None:
            raise BotAutenticacionError(
                f'No hay una credencial activa configurada para "{self.cotizacion.aseguradora}".',
                accion='Cree o active la credencial de Mapfre en Configuraciones › Aseguradoras y reenvíe la solicitud.',
            )
        exigir_clave_al_dia(credencial, self.cotizacion.aseguradora)
        return credencial

    def _set_estado(self, estado_bot, mensaje=None):
        with schema_context(self.schema_name):
            self.cotizacion.estado_bot = estado_bot
            if mensaje is not None:
                self.cotizacion.mensaje_bot = mensaje
            self.cotizacion.save(update_fields=['estado_bot', 'mensaje_bot'])

    def _capturar_diagnostico(self, page):
        """Screenshot al fallar. Nunca vuelca valores de inputs (podrían ser la contraseña ni el código)."""
        try:
            debug_dir = os.path.join(settings.MEDIA_ROOT, 'bot_debug')
            os.makedirs(debug_dir, exist_ok=True)
            base = os.path.join(debug_dir, f'mapfre_{self.cotizacion.pk}_{timezone.now().strftime("%Y%m%d_%H%M%S")}')
            page.screenshot(path=f'{base}.png', full_page=True)
            logger.warning('Diagnóstico del bot Mapfre guardado en %s.png', base)
        except Exception:
            logger.exception('No se pudo capturar el diagnóstico de Mapfre tras la falla')

    # ------------------------------------------------------------------
    # Orquestación
    # ------------------------------------------------------------------

    def run(self):
        self._set_estado('en_proceso', mensaje=None)
        with schema_context(self.schema_name):
            self.cotizacion.ejecutado_en = timezone.now()
            self.cotizacion.save(update_fields=['ejecutado_en'])

        try:
            with sync_playwright() as playwright:
                browser = playwright.chromium.launch(headless=self.headless)
                contexto = browser.new_context(viewport={'width': 1366, 'height': 900})
                page = contexto.new_page()
                try:
                    self._paso(PASO_LOGIN)
                    self._login(page)
                    self._paso('Verificación por código')
                    self._verificar_codigo(page)
                    self._paso('Cotización')
                    nota = self._cotizar(page)
                except (BotCancelado, BotTimeout):
                    raise
                except Exception:
                    self._guardar_pantalla(page)
                    self._capturar_diagnostico(page)
                    raise
                finally:
                    self._cerrar_sesion(page)
                    browser.close()

            self._set_estado('completado', mensaje=nota)

        except BotCancelado:
            self._set_estado('cancelado', mensaje='El asesor canceló la cotización en Mapfre.')
        except BotTimeout:
            self._set_estado('error', mensaje='Se agotó el tiempo esperando la verificación del asesor en Mapfre.')
        except Exception as e:
            logger.exception('Error cotizando %s en Mapfre', self.vehiculo.placa)
            self._registrar_error(e)

    # ------------------------------------------------------------------
    # Pasos
    # ------------------------------------------------------------------

    @staticmethod
    def _captcha_marcado(page):
        """True si el reCAPTCHA «No soy un robot» ya está marcado (lo marcó una persona)."""
        try:
            for frame in page.frames:
                if 'recaptcha/api2/anchor' in frame.url or 'recaptcha/enterprise/anchor' in frame.url:
                    return frame.locator('#recaptcha-anchor').get_attribute('aria-checked', timeout=1500) == 'true'
        except Exception:
            pass
        return False

    def _login(self, page):
        page.goto(self.credencial.portal_url, wait_until='domcontentloaded')
        usuario = page.locator('[id="form_login:TXT_USER"]')
        usuario.wait_for(timeout=40000)
        clave = page.locator('[id="form_login:TXT_PASS"]')
        usuario.click()
        usuario.press_sequentially(self.credencial.username, delay=40)
        clave.click()
        clave.press_sequentially(self.credencial.password, delay=40)

        # El reCAPTCHA es una prueba para distinguir personas de programas: lo marca el asesor, no el bot.
        if not self._captcha_marcado(page):
            self._esperar_al_asesor(
                'captcha',
                'Mapfre pide demostrar que eres una persona: marca «No soy un robot» en la ventana de Mapfre que se abrió '
                'en este equipo. El proceso continúa solo cuando lo marques.',
                timeout=SEGUNDOS_PARA_CAPTCHA, listo=lambda: self._captcha_marcado(page))

        page.locator('[id="form_login:btnLogin"]').click()
        page.wait_for_timeout(2500)
        mensaje = self._mensaje_de_error(page)
        if mensaje:
            raise BotAutenticacionError(
                f'Mapfre no permitió el ingreso: «{mensaje}».',
                accion='Verifique el usuario y la contraseña de Mapfre en Configuraciones › Aseguradoras y que la cuenta no '
                       'esté bloqueada; luego reenvíe la solicitud a Mapfre.',
            )

    @staticmethod
    def _mensaje_de_error(page):
        """Mensaje de error visible del portal (PrimeFaces: ui-messages / growl / ui-message)."""
        try:
            return page.evaluate("""() => [...document.querySelectorAll(
                '.ui-messages-error, .ui-growl-message-error, .ui-message-error, .ui-messages-error-summary, .ui-messages-error-detail')]
                .filter(e => e.getBoundingClientRect().width > 0 && (e.innerText || '').trim())
                .map(e => e.innerText.trim().replace(/\\s+/g, ' '))[0] || null""")
        except Exception:
            return None

    def _verificar_codigo(self, page):
        """Pide al asesor el código de 6 dígitos (llega por SMS al celular registrado) y lo digita en el portal.
        PENDIENTE DE MAPEAR: selectores de la ventana de verificación (se ajustan con una sesión real)."""
        codigo = self._esperar_al_asesor(
            'codigo',
            'Mapfre envió un código de 6 dígitos al celular registrado. Escríbelo en la plataforma para continuar.',
            timeout=SEGUNDOS_PARA_CODIGO)
        self._digitar_codigo_en_portal(page, codigo)

    def _digitar_codigo_en_portal(self, page, codigo):
        raise BotPortalError(
            'El paso del código de verificación de Mapfre todavía no está conectado al portal (falta mapear su ventana).',
            accion='Avise a soporte: el bot de Mapfre está en construcción.')

    def _cotizar(self, page):
        raise BotPortalError(
            'El bot de Mapfre todavía no cotiza: falta mapear el formulario después del ingreso.',
            accion='Cotice en el portal de Mapfre mientras tanto y avise a soporte.')

    # ------------------------------------------------------------------
    # Cierre de sesión
    # ------------------------------------------------------------------

    def _cerrar_sesion(self, page):
        """Cierra sesión SIEMPRE, sin lanzar excepción. PENDIENTE: selector real del botón de salida (se confirma en la
        sesión de mapeo); mientras tanto se prueba por texto."""
        if page is None:
            return
        try:
            if page.is_closed() or page.locator('[id="form_login:TXT_USER"]').count():
                return  # no hay sesión abierta
            for texto in ('Cerrar sesión', 'Cerrar Sesión', 'Salir'):
                enlace = page.get_by_text(texto, exact=False).first
                if enlace.count() and enlace.is_visible():
                    enlace.click(timeout=6000)
                    page.wait_for_timeout(3000)
                    return
            logger.warning('Mapfre: no se encontró el botón para cerrar sesión (revisar la cuenta).')
        except Exception:
            logger.warning('Mapfre: no se pudo confirmar que la sesión quedó cerrada (revisar la cuenta).', exc_info=True)
