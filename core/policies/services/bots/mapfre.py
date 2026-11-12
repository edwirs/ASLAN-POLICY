"""Bot de cotización para Mapfre (portal de intermediarios, ofiVirtualWeb, JSF/PrimeFaces).

Flujo mapeado con una sesión real el 2026-10-28 (DIU679: Super Trebol 117 $1.451.800, Super Trebol $1.486.170):
ingreso › código SMS › «Cotización Emisión» (iframe iFramePpal) › Autos cotización múltiple (SUPER TREBOL 117 y SUPER
TREBOL) › Cotizar - Emitir › placa (Mapfre trae del RUNT vehículo y tomador) › oficina, asegurado, ciudad, RCE y
deducibles fijos › Cotizar › tabla de resultados. Nunca se pulsa «Emitir».

Lo que el portal exige a una persona (el bot NO lo hace por su cuenta):
  1. reCAPTCHA «No soy un robot»: lo marca el asesor en la ventana de Mapfre (por eso este bot corre con navegador
     VISIBLE, ver REQUIERE_NAVEGADOR_VISIBLE). El bot solo espera a que quede marcado y entonces pulsa «Ingresar».
  2. Código de 6 dígitos que Mapfre envía por SMS al celular registrado: el asesor lo escribe directamente en la
     ventana de Mapfre (Cotizacion.verificacion_bot = 'portal': la plataforma solo muestra el aviso, sin modal).

Sesiones: las solicitudes de Mapfre se cotizan en una SESIÓN COMPARTIDA (services/bots/sesion_compartida.py): el asesor
resuelve el captcha y el código una vez y el bot cotiza ahí, una tras otra, las que lleguen; a los «minutos_sesion» de
haber entrado (10 por defecto) se cierra sesión y la siguiente vuelve a pedir el ingreso. Siempre se cierra sesión al
final (por tiempo, por falla del ingreso o si el trabajador termina).
"""
import logging
import os
import re
import sys
import time

from django.conf import settings
from django.db import connection
from django.utils import timezone
from django_tenants.utils import schema_context
from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeoutError

os.environ.setdefault('DJANGO_ALLOW_ASYNC_UNSAFE', 'true')

from core.policies.services.credenciales import lista
from core.policies.services.bots.base import (  # noqa: E402
    PASO_LOGIN,
    BotAutenticacionError,
    BotCancelado,
    BotNoCotizableError,
    BotPortalError,
    BotTimeout,
    RegistroErrorMixin,
    exigir_clave_al_dia,
    normalizar_texto,
    parse_money,
)

logger = logging.getLogger(__name__)

SEGUNDOS_PARA_CAPTCHA = 240
SEGUNDOS_PARA_CODIGO = 300


class MapfreBot(RegistroErrorMixin):
    """Cotiza en Mapfre. Uso: MapfreBot(cotizacion, headless=False).run()"""

    # El reCAPTCHA lo marca una persona: el navegador tiene que verse (lo lee el runner).
    REQUIERE_NAVEGADOR_VISIBLE = True

    # Las solicitudes van a la fila de la sesión compartida (lo lee el runner).
    SESION_COMPARTIDA = True

    def __init__(self, cotizacion, headless=False, schema_name=None):
        self.cotizacion = cotizacion
        self.vehiculo = cotizacion.vehiculo
        self._foto_vehiculo()
        self.tomador = self.vehiculo.tomador
        self.headless = headless
        self.credencial = self._get_credencial()
        # Dentro de sync_playwright Django usa otra conexión (schema public): el trabajador de la sesión compartida
        # construye el bot ahí dentro, por eso puede pasar el schema explícito.
        self.schema_name = schema_name or connection.schema_name

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
                browser = self._abrir_navegador(playwright)
                contexto = browser.new_context(viewport={'width': 1366, 'height': 900})
                page = contexto.new_page()
                try:
                    self._paso(PASO_LOGIN)
                    self._login(page)
                    self._paso('Verificación por código')
                    self._verificar_codigo(page)
                    self._paso('Cotización')
                    nota = self._cotizar(page)
                    self._mapear_documentos(page)
                    self._descargar_cotizacion(page)
                except (BotCancelado, BotTimeout):
                    raise
                except Exception as e:
                    if self._ventana_cerrada(page, e):
                        raise BotPortalError(
                            'Se cerró la ventana de Mapfre antes de que el bot terminara de cotizar.',
                            accion='Reenvíe la solicitud a Mapfre (botón «Reenviar a Mapfre») y deje abierta la ventana '
                                   'hasta que se cierre sola; puede minimizarla mientras tanto.') from e
                    self._guardar_pantalla(page)
                    self._capturar_diagnostico(page)
                    raise
                finally:
                    self._cerrar_sesion(page)
                    try:
                        browser.close()
                    except Exception:
                        pass  # el asesor ya la había cerrado

            self._set_estado('completado', mensaje=nota)

        except BotCancelado:
            self._set_estado('cancelado', mensaje='El asesor canceló la cotización en Mapfre.')
        except BotTimeout:
            self._set_estado('error', mensaje='Se agotó el tiempo esperando la verificación del asesor en Mapfre.')
        except Exception as e:
            logger.exception('Error cotizando %s en Mapfre', self.vehiculo.placa)
            self._registrar_error(e)

    # ------------------------------------------------------------------
    # Sesión compartida (ver services/bots/sesion_compartida.py)
    # ------------------------------------------------------------------

    def minutos_sesion(self):
        try:
            return max(0, min(int(str(self.parametro('minutos_sesion')).strip()), 60))
        except (TypeError, ValueError):
            return 10

    def _entrar(self, playwright, sesion):
        """Abre el navegador y entra a Mapfre (captcha y código los hace el asesor). Deja la sesión lista en el menú."""
        sesion.cerrar(self, 'se vuelve a entrar')
        sesion.browser = self._abrir_navegador(playwright)
        sesion.page = sesion.browser.new_context(viewport={'width': 1366, 'height': 900}).new_page()
        self._paso(PASO_LOGIN)
        self._login(sesion.page)
        self._paso('Verificación por código')
        self._verificar_codigo(sesion.page)
        sesion.inicio = time.time()
        sesion.minutos = self.minutos_sesion()
        sesion.credencial_id = self.credencial.pk
        sesion.url_menu = sesion.page.url
        logger.info('Sesión de Mapfre abierta por la cotización #%s (se cierra en %s min).', self.cotizacion.pk, sesion.minutos)

    def _volver_al_menu(self, sesion):
        """Para la siguiente cotización en la misma sesión: vuelve a la página del menú en la que quedó al entrar. False
        si el portal ya no tiene la sesión (muestra el ingreso o el código) o no carga el menú: hay que volver a entrar."""
        page = sesion.page
        try:
            page.goto(sesion.url_menu, wait_until='domcontentloaded', timeout=40000)
            page.wait_for_timeout(1500)
            if page.locator('[id="form_login:TXT_USER"]').count() or 'VerificarCodigoMfa' in page.url:
                logger.info('Mapfre: la sesión ya había vencido en el portal (cotización #%s).', self.cotizacion.pk)
                return False
            for _ in range(30):
                marco = page.frame(name='iFramePpal')
                if marco is not None and marco.get_by_text(re.compile(r'Cotizaci.n\s*Emisi.n', re.I)).count():
                    return True
                page.wait_for_timeout(1000)
            logger.warning('Mapfre: al volver al menú no apareció «Cotización Emisión» (cotización #%s, %s).',
                           self.cotizacion.pk, page.url)
        except Exception:
            logger.warning('Mapfre: no se pudo volver al menú de la sesión abierta (cotización #%s).', self.cotizacion.pk,
                           exc_info=True)
        return False

    def cotizar_en_sesion(self, playwright, sesion):
        """Cotiza esta solicitud en la sesión compartida: la reutiliza si sigue abierta y le queda tiempo; si no, entra
        (captcha + código). Nunca lanza: deja la cotización completada o con su error."""
        self._set_estado('en_proceso', mensaje=None)
        with schema_context(self.schema_name):
            self.cotizacion.ejecutado_en = timezone.now()
            self.cotizacion.save(update_fields=['ejecutado_en'])
        if self.vehiculo.es_cero_km:  # se resuelve sin tocar el portal (no gasta la sesión)
            try:
                self._cotizar(None)
            except Exception as e:
                self._registrar_error(e)
            return

        page = None
        try:
            reutiliza = sesion.sirve_para(self.credencial.pk)
            if reutiliza:
                self._paso('Sesión de Mapfre ya abierta (sin captcha)')
                reutiliza = self._volver_al_menu(sesion)
            if not reutiliza:
                self._entrar(playwright, sesion)
            page = sesion.page
            self._paso('Cotización')
            nota = self._cotizar(page)
            sesion.cotizaciones += 1
            self._mapear_documentos(page)
            self._descargar_cotizacion(page)
            if reutiliza:
                nota = ((nota or '') + ' Cotizado en la sesión de Mapfre que ya estaba abierta.').strip()
            self._set_estado('completado', mensaje=nota)
        except BotCancelado:
            sesion.cerrar(self, 'el asesor canceló')
            self._set_estado('cancelado', mensaje='El asesor canceló la cotización en Mapfre.')
        except BotTimeout:
            sesion.cerrar(self, 'nadie hizo la verificación')
            self._set_estado('error', mensaje='Se agotó el tiempo esperando la verificación del asesor en Mapfre.')
        except Exception as e:
            logger.exception('Error cotizando %s en Mapfre', self.vehiculo.placa)
            actual = sesion.page
            if actual is not None and self._ventana_cerrada(actual, e):
                sesion.cerrar(None, 'cerraron la ventana')
                e = BotPortalError(
                    'Se cerró la ventana de Mapfre antes de que el bot terminara de cotizar.',
                    accion='Reenvíe la solicitud a Mapfre (botón «Reenviar a Mapfre») y deje abierta la ventana; se cierra '
                           'sola unos minutos después. Puede minimizarla mientras tanto.')
            else:
                if actual is not None:
                    self._guardar_pantalla(actual)
                    self._capturar_diagnostico(actual)
                if page is None:
                    # Falló el ingreso: se cierra todo. Si falló la cotización, la sesión sigue para la siguiente (antes de
                    # usarla se comprueba que el portal la mantenga).
                    sesion.cerrar(self, 'falló el ingreso')
            self._registrar_error(e)

    @staticmethod
    def _sigue_abierta(page):
        """Mientras el bot espera al asesor: si cerraron la ventana de Mapfre no tiene sentido seguir esperando."""
        if page.is_closed():
            raise BotPortalError('La ventana de Mapfre se cerró mientras se esperaba al asesor.')
        return True

    @staticmethod
    def _ventana_cerrada(page, error):
        """True si la falla es porque la persona cerró la ventana de Mapfre mientras el bot trabajaba."""
        try:
            if page.is_closed():
                return True
        except Exception:
            return True
        return 'has been closed' in str(error) or 'Target closed' in str(error)

    @staticmethod
    def _hay_pantalla():
        """Linux sin X ni Wayland (un VPS) no puede abrir la ventana que necesita el asesor. macOS y Windows siempre."""
        if not sys.platform.startswith('linux'):
            return True
        return bool(os.environ.get('DISPLAY') or os.environ.get('WAYLAND_DISPLAY'))

    def _abrir_navegador(self, playwright):
        """El navegador tiene que verse (captcha). Con el Agente ASLAN la ventana sale en el PC de la oficina; en este
        equipo, con el Google Chrome instalado (el Chrome de pruebas de Playwright se cierra al abrirse visible en
        macOS 26) o, si no está, con el de Playwright."""
        modo = self._modo_ejecucion()
        if modo != 'servidor':
            agente = self._agente_para_bot()
            if agente is not None:
                return self._conectar_agente(playwright, agente, self.headless)
            if modo == 'agente':
                return self._lanzar_navegador(playwright, headless=self.headless)  # avisa que el agente está apagado
        if not self.headless and not self._hay_pantalla():
            raise BotPortalError(
                'Mapfre no se pudo cotizar: su portal pide el captcha «No soy un robot» y el código SMS en una ventana '
                'visible, el servidor no tiene pantalla y no hay ningún Agente ASLAN encendido en la oficina.',
                accion='Encienda el PC de la oficina que tiene el Agente ASLAN (o ábralo desde el escritorio) y reenvíe a '
                       'Mapfre; la ventana saldrá en ese equipo. Mientras tanto, cotice Mapfre a mano y cargue el valor '
                       'con «Cotizar a mano».',
            )
        return self._lanzar_navegador(playwright, headless=self.headless, canal=None if self.headless else 'chrome')

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
                timeout=SEGUNDOS_PARA_CAPTCHA, listo=lambda: self._sigue_abierta(page) and self._captcha_marcado(page))

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
        """Mapfre envía un código de 6 dígitos por SMS al celular registrado. El asesor lo escribe DIRECTAMENTE en la
        ventana de Mapfre y pulsa «INGRESAR CÓDIGO»; el bot espera a que el portal entre al menú y sigue solo."""
        try:
            page.wait_for_url(re.compile(r'VerificarCodigoMfa|menuIntermediarios', re.I), timeout=30000)
        except PlaywrightTimeoutError:
            raise BotPortalError('Mapfre no mostró la pantalla del código de verificación después de ingresar.')
        if 'menuIntermediarios' in page.url:
            return  # no pidió código esta vez
        self._esperar_al_asesor(
            'portal',
            'Mapfre envió un código de 6 dígitos al celular registrado: escríbelo en la ventana de Mapfre y pulsa '
            '«INGRESAR CÓDIGO». El proceso continúa solo.',
            timeout=SEGUNDOS_PARA_CODIGO,
            listo=lambda: self._entro_al_menu(page))

    def _entro_al_menu(self, page):
        """¿Ya pasó del código al menú? El API síncrono de Playwright solo se entera de una navegación (o de que cerraron
        la ventana) cuando se le llama: sin esta pausa corta `page.url` se queda en la del código para siempre."""
        page.wait_for_timeout(300)
        return self._sigue_abierta(page) and 'menuIntermediarios' in page.url

    # ------------------------------------------------------------------
    # Cotización (Cotización Emisión › Autos cotización múltiple, mapeado el 2026-10-28 con DIU679)
    # ------------------------------------------------------------------

    # Oficina, productos, RCE y deducibles son opciones de cada empresa (Configuraciones › Aseguradoras › Mapfre):
    # ver services/credenciales.PARAMETROS_POR_ASEGURADORA (los valores por defecto son los que pidió Gali).
    @property
    def PRODUCTO_DESTACADO(self):
        return self.parametro('producto_destacado')

    def _marco(self, page):
        marco = page.frame(name='iFramePpal')
        if marco is None:
            raise BotPortalError('Mapfre no cargó el área de trabajo (iFramePpal) del portal.')
        return marco

    def _elegir(self, page, marco, campo, texto, obligatorio=True):
        """Lista de PrimeFaces (selectOneMenu): se abre, se filtra si tiene buscador y se pulsa la opción."""
        marco.locator(f'[id="{campo}"]').click()
        page.wait_for_timeout(500)
        filtro = marco.locator(f'[id="{campo}_filter"]')
        if filtro.count() and filtro.is_visible():
            filtro.fill(texto)
            page.wait_for_timeout(700)
        opcion = marco.locator(f'[id="{campo}_items"] li:visible').filter(has_text=re.compile(re.escape(texto), re.I)).first
        try:
            opcion.click(timeout=6000)
        except PlaywrightTimeoutError:
            page.keyboard.press('Escape')
            if obligatorio:
                raise BotPortalError(f'Mapfre no ofrece «{texto}» en el campo {campo}.')
            return
        page.wait_for_timeout(1500)

    def _esperar_portal(self, page, marco, segundos=90):
        """Espera a que desaparezca el aviso «Estamos trabajando para ti…»."""
        for _ in range(segundos):
            page.wait_for_timeout(1000)
            try:
                ocupado = marco.evaluate("""() => [...document.querySelectorAll('.ui-dialog, .ui-blockui')]
                    .some(e => e.getBoundingClientRect().width > 0 && /trabajando/i.test(e.innerText || ''))""")
            except Exception:
                ocupado = True
            if not ocupado:
                return
        raise BotPortalError('Mapfre tardó demasiado en responder («Estamos trabajando para ti»).')

    def _mensajes_marco(self, marco):
        try:
            return marco.evaluate("""() => [...document.querySelectorAll(
                '.ui-messages-error, .ui-growl-message-error, .ui-message-error, .ui-messages-warn, .ui-growl-message-warn')]
                .filter(e => e.getBoundingClientRect().width > 0 && (e.innerText || '').trim())
                .map(e => e.innerText.trim().replace(/\\s+/g, ' '))""")
        except Exception:
            return []

    def _cotizar(self, page):
        if self.vehiculo.es_cero_km:
            raise BotNoCotizableError(
                'El bot de Mapfre todavía no cotiza vehículos 0 km (sin placa el portal no trae los datos del vehículo).',
                accion='Cotice este 0 km a mano en el portal de Mapfre con «Cotizar a mano» y registre el valor.')
        marco = self._marco(page)
        marco.get_by_text(re.compile(r'Cotizaci.n\s*Emisi.n', re.I)).first.click()
        page.wait_for_timeout(4000)
        marco = self._marco(page)
        marco.get_by_text(re.compile(r'Autos cotizaci.n m.ltiple', re.I)).first.wait_for(timeout=30000)

        # Productos: SUPER TREBOL 117 y SUPER TREBOL (casillas de PrimeFaces).
        for producto in lista(self.parametro('productos')):
            fila = marco.locator('tr').filter(has=marco.get_by_text(re.compile(r'^\s*' + re.escape(producto) + r'\s*$')))
            caja = fila.first.locator('.ui-chkbox-box')
            if caja.get_attribute('aria-checked') != 'true':
                caja.click()
                page.wait_for_timeout(400)
        # «Cotizar - Emitir» de la tabla de cotización múltiple (el primero de la página).
        marco.get_by_role('button', name=re.compile(r'Cotizar\s*-\s*Emitir', re.I)).first.click()
        page.wait_for_timeout(3000)
        marco = self._marco(page)

        placa = marco.locator('[id="COD_PLACA_NIVEL_POLIZA"]')
        placa.wait_for(timeout=40000)
        placa.click()
        placa.press_sequentially(self.vehiculo.placa, delay=60)
        placa.press('Tab')
        self._esperar_portal(page, marco)
        for _ in range(20):  # la placa trae del RUNT el vehículo y el tomador
            if marco.locator('[id="COD_FASECOLDA"]').input_value():
                break
            page.wait_for_timeout(1000)
        else:
            mensajes = self._mensajes_marco(marco)
            raise BotPortalError('Mapfre no trajo los datos del vehículo con la placa'
                                 + (f': «{mensajes[0]}»' if mensajes else '.'))

        self._elegir(page, marco, 'COD_NIVEL3', self.parametro('oficina'))
        asegurado = marco.locator('[id="COD_DOCUM_ASEG"]')
        asegurado.click()
        asegurado.press_sequentially(self.tomador.dni, delay=50)
        asegurado.press('Tab')
        self._esperar_portal(page, marco)
        page.wait_for_timeout(2000)
        genero = {'male': 'MASCULINO', 'female': 'FEMENINO'}.get(self.tomador.gender)
        if genero:
            self._elegir(page, marco, 'MCA_SEXO', genero, obligatorio=False)
        nacimiento = marco.locator('[id="FEC_NACIMIENTO_input"]')
        if self.tomador.birthdate and not nacimiento.input_value():
            nacimiento.click()
            nacimiento.press_sequentially(self.tomador.birthdate.strftime('%d%m%Y'), delay=50)
            nacimiento.press('Tab')
        municipio = self.vehiculo.zona_circulacion
        self._elegir(page, marco, 'COD_POSTAL_RADIC', f'({municipio.codigo})')
        self._esperar_portal(page, marco)
        self._elegir(page, marco, 'NUM_OPCION_RC', self.parametro('opcion_rce'))
        self._elegir(page, marco, 'MCA_DEDCBLE_CERO_PERD_TOT', self.parametro('deducible_cero_perdida_total'))
        self._elegir(page, marco, 'MCA_DEDCBLE_UNICO_PERD_PAR', self.parametro('deducible_perdida_parcial'))
        page.keyboard.press('Escape')
        self._capturar_vehiculo(marco)

        marco.get_by_role('button', name=re.compile(r'^\s*Cotizar\s*$', re.I)).last.click()
        page.wait_for_timeout(1500)
        self._esperar_portal(page, marco, segundos=150)
        return self._leer_resultado(marco)

    def _capturar_vehiculo(self, marco):
        """Datos que Mapfre trajo del RUNT: solo se completan los que el vehículo no tenía."""
        valores = {campo: marco.locator(f'[id="{id_}"]').input_value() for campo, id_ in (
            ('chasis', 'COD_CHASIS'), ('motor', 'COD_MOTOR'), ('codigo_fasecolda', 'COD_FASECOLDA'))}
        comercial = parse_money(marco.locator('[id="IMP_VLR_COMERCIAL"]').input_value())
        cambio = False
        for campo, valor in valores.items():
            if valor and not getattr(self.vehiculo, campo):
                setattr(self.vehiculo, campo, valor.strip())
                cambio = True
        if comercial and not self.vehiculo.valor_comercial:
            self.vehiculo.valor_comercial = comercial
            cambio = True
        if cambio:
            with schema_context(self.schema_name):
                self._guardar_vehiculo_cambios()

    def _leer_resultado(self, marco):
        """Tabla de resultados: una fila por producto con Nro. cotización, Estado, Vlr. prima y Observaciones."""
        filas = marco.evaluate("""() => {
            const tabla = [...document.querySelectorAll('table')].find(t => /Vlr\\.?\\s*prima/i.test(t.innerText));
            if (!tabla) return null;
            const cab = [...tabla.querySelectorAll('thead th, tr:first-child th')].map(th => th.innerText.trim().toLowerCase());
            // Orden visto el 2026-10-28: Nro. cotización, Nro. póliza, Emitir, Producto, Estado, Vlr. prima, Observaciones…
            const col = (n, d) => { const i = cab.findIndex(c => c.includes(n)); return i >= 0 ? i : d; };
            return [...tabla.querySelectorAll('tbody tr')].map(tr => {
                const td = [...tr.querySelectorAll('td')].map(c => c.innerText.trim());
                return {numero: td[col('nro. cotiz', 0)] || '', producto: (td[col('producto', 3)] || '').replace(/\\s*\\/\\s*$/, ''),
                        estado: td[col('estado', 4)] || '', prima: td[col('prima', 5)] || '', observaciones: td[col('observ', 6)] || ''};
            }).filter(f => f.producto);
        }""")
        if not filas:
            mensajes = self._mensajes_marco(marco)
            if mensajes:
                raise BotNoCotizableError(f'Mapfre no cotizó: «{mensajes[0]}».',
                                          accion='Revise el mensaje de Mapfre; si aplica, cotice a mano y registre el valor.')
            raise BotPortalError('Mapfre no mostró la tabla de resultados después de cotizar.')

        planes = [(f['producto'].strip(), parse_money(f['prima'])) for f in filas]
        planes = [(nombre, valor) for nombre, valor in planes if valor and valor > 0]
        if not planes:
            observacion = next((f['observaciones'] for f in filas if f['observaciones']), '')
            raise BotNoCotizableError(f'Mapfre no dio valor para este vehículo{": «" + observacion + "»" if observacion else ""}.',
                                      accion='Revise la observación de Mapfre; si aplica, cotice a mano y registre el valor.')

        from core.policies.models import CotizacionPlan  # import local: evita ciclo al cargar el módulo
        destacado = next((v for n, v in planes if normalizar_texto(n) == normalizar_texto(self.PRODUCTO_DESTACADO)), planes[0][1])
        with schema_context(self.schema_name):
            self.cotizacion.planes.all().delete()
            for nombre, valor in planes:
                CotizacionPlan.objects.create(cotizacion=self.cotizacion, nombre_plan=nombre, prima_total=valor)
            self.cotizacion.prima_total = destacado
            self.cotizacion.save(update_fields=['prima_total'])
        notas = [f"{f['producto'].strip()} Nº {f['numero']}" + (f" — {f['observaciones']}" if f['observaciones'] else '')
                 for f in filas if f['numero']]
        return ('Cotizaciones en Mapfre: ' + '; '.join(notas) + '.') if notas else None

    # Busca, en la fila del producto destacado de la tabla de resultados, el botón con ícono de PDF (más a la derecha).
    # Lo marca con data-aslan-pdf para pulsarlo con Playwright. Nunca toma «Emitir» ni «Recotizar».
    # El PDF de la cotización está en la columna «Carátula» de la tabla de resultados (ícono rojo de PDF), en la fila del
    # producto que cuenta (Super Trebol 117). Se ubica la columna por su título, como lo haría una persona; si no
    # aparece, se busca un ícono de PDF en la fila. Nunca se toca «Emitir» ni «SimuCrediMapfre».
    BOTON_PDF_JS = """(producto) => {
        const norm = t => (t || '').normalize('NFD').replace(/[\\u0300-\\u036f]/g, '').replace(/\\s+/g, ' ').trim().toLowerCase();
        const tabla = [...document.querySelectorAll('table')].find(t => /vlr\\.?\\s*prima/.test(norm(t.innerText)));
        if (!tabla) return {estado: 'sin_tabla'};
        const filas = [...tabla.querySelectorAll('tr')];
        const esTitulo = c => norm(c.innerText) === 'caratula';
        const cabecera = filas.find(tr => [...tr.children].some(esTitulo));
        const datos = filas.filter(tr => tr !== cabecera && tr.querySelectorAll('td').length > 1);
        // Primero la celda de producto exacta («Super Trebol 117 /» = super trebol 117); si no, la que lo contenga.
        const exacta = tr => [...tr.children].some(c => norm(c.innerText).replace(/\\s*\\/\\s*$/, '') === producto);
        const fila = datos.find(exacta) || datos.find(tr => norm(tr.innerText).includes(producto)) || datos[0];
        if (!fila) return {estado: 'sin_filas'};
        const prohibido = e => /emitir|recotizar|simucredi/i.test((e.innerText || '') + ' ' + (e.title || '') + ' ' + (e.getAttribute('onclick') || ''));
        const clicable = e => e.closest('a, button, [onclick], input[type=image]') || e;
        let boton = null, como = '';
        if (cabecera) {
            const indice = [...cabecera.children].findIndex(esTitulo);
            const celda = fila.children[indice];
            const el = celda && celda.querySelector('a, button, input[type=image], [onclick], img, svg, i, span');
            if (el && !prohibido(clicable(el))) { boton = clicable(el); como = 'columna Carátula'; }
        }
        if (!boton) {
            const atributos = e => [e.className && e.className.baseVal === undefined ? e.className : '', e.id, e.title, e.getAttribute('alt'),
                e.getAttribute('src'), e.getAttribute('href'), e.getAttribute('onclick'), e.getAttribute('aria-label')].join(' ');
            const candidatos = [...fila.querySelectorAll('a, button, img, i, span, input[type=image], [onclick]')]
                .filter(e => /pdf|caratula/i.test(atributos(e) + ' ' + (e.innerText || '')) && !prohibido(e));
            if (candidatos.length) { boton = clicable(candidatos[0]); como = 'ícono de PDF en la fila'; }
        }
        if (!boton) return {estado: 'sin_boton', html: fila.outerHTML.slice(0, 6000)};
        document.querySelectorAll('[data-aslan-pdf]').forEach(e => e.removeAttribute('data-aslan-pdf'));
        boton.setAttribute('data-aslan-pdf', '1');
        return {estado: 'ok', como: como};
    }"""

    def _descargar_cotizacion(self, page):
        """PDF de la cotización: botón con ícono de PDF en la tabla de resultados, en la fila del producto destacado
        (Super Trebol 117). Puede tardar unos segundos en aparecer después de la tabla."""
        self._paso('PDF de la cotización')
        try:
            marco = self._marco(page)
            resultado = {}
            for _ in range(60):
                resultado = marco.evaluate(self.BOTON_PDF_JS, self.PRODUCTO_DESTACADO.lower())
                if resultado.get('estado') == 'ok':
                    break
                page.wait_for_timeout(1000)
            if resultado.get('estado') != 'ok':
                self._guardar_fila_sin_pdf(resultado)
                return
            logger.info('Mapfre: PDF de la cotización #%s por la %s.', self.cotizacion.pk, resultado.get('como'))
            boton = marco.locator('[data-aslan-pdf="1"]').first
            boton.scroll_into_view_if_needed(timeout=10000)
        except Exception:
            logger.warning('Mapfre: no se encontró el botón del PDF (cotización #%s).', self.cotizacion.pk, exc_info=True)
            return

        def pulsar():
            try:
                boton.click(timeout=8000)
            except PlaywrightTimeoutError:
                boton.evaluate('e => e.click()')  # ícono sin tamaño visible (p. ej. de fondo CSS): el clic va directo al elemento
        self._descargar_pdf(page, pulsar)

    def _guardar_fila_sin_pdf(self, resultado):
        """Si el botón del PDF no aparece, guarda cómo venía la fila para ajustar el bot (sin datos de campos)."""
        try:
            carpeta = os.path.join(settings.MEDIA_ROOT, 'bot_debug')
            os.makedirs(carpeta, exist_ok=True)
            ruta = os.path.join(carpeta, f'mapfre_pdf_{self.cotizacion.pk}.html')
            with open(ruta, 'w', encoding='utf-8') as archivo:
                archivo.write(f'<!-- estado: {resultado.get("estado")} -->\n{resultado.get("html", "")}')
            logger.warning('Mapfre: no apareció el botón del PDF (%s). Fila guardada en %s', resultado.get('estado'), ruta)
        except Exception:
            logger.warning('Mapfre: no se pudo guardar la fila sin botón de PDF.', exc_info=True)

    # ------------------------------------------------------------------
    # Cierre de sesión
    # ------------------------------------------------------------------

    def _cerrar_sesion(self, page):
        """Cierra sesión SIEMPRE, sin lanzar excepción: avatar (arriba a la derecha) › «Cerrar sesión» › «Salir» en la
        ventana de confirmación. Se verifica que el portal vuelva a la pantalla de ingreso."""
        if page is None:
            return
        try:
            if page.is_closed() or page.locator('[id="form_login:TXT_USER"]').count():
                return  # no hay sesión abierta
            if 'VerificarCodigoMfa' in page.url:
                return  # no alcanzó a entrar: el código no se validó
            page.keyboard.press('Escape')
            page.locator('#dropdownMenuLink').click(timeout=6000)
            page.wait_for_timeout(700)
            page.locator('a[href="#sesionModal"]').filter(has_text=re.compile('Cerrar sesi', re.I)).first.click(timeout=6000)
            page.wait_for_timeout(1000)
            page.locator('#sesionModal a').filter(has_text=re.compile(r'^\s*Salir\s*$', re.I)).first.click(timeout=6000)
            page.locator('[id="form_login:TXT_USER"]').wait_for(timeout=15000)
        except Exception:
            logger.warning('Mapfre: no se pudo confirmar que la sesión quedó cerrada (revisar la cuenta).', exc_info=True)
