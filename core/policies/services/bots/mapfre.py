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

    def _abrir_navegador(self, playwright):
        """Visible: con el Google Chrome instalado (el Chrome de pruebas de Playwright se cierra al abrirse visible en
        macOS 26). Si no está instalado, el de Playwright."""
        if not self.headless:
            try:
                return playwright.chromium.launch(headless=False, channel='chrome')
            except Exception:
                logger.warning('Mapfre: no se encontró Google Chrome instalado; se usa el navegador de Playwright.')
        return playwright.chromium.launch(headless=self.headless)

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

    # Valores fijos que pidió Gali para todas las cotizaciones de Mapfre.
    PRODUCTOS = ('SUPER TREBOL 117', 'SUPER TREBOL')
    PRODUCTO_DESTACADO = 'Super Trebol 117'   # el que cuenta en el comparativo
    OFICINA = 'RESTREPO'
    OPCION_RCE = '(254)'                      # 4.000 Millones
    DEDUCIBLE_CERO_PERDIDA_TOTAL = 'SI (S)'
    DEDUCIBLE_PERDIDA_PARCIAL = '1.200.000'

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
        for producto in self.PRODUCTOS:
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

        self._elegir(page, marco, 'COD_NIVEL3', self.OFICINA)
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
        self._elegir(page, marco, 'NUM_OPCION_RC', self.OPCION_RCE)
        self._elegir(page, marco, 'MCA_DEDCBLE_CERO_PERD_TOT', self.DEDUCIBLE_CERO_PERDIDA_TOTAL)
        self._elegir(page, marco, 'MCA_DEDCBLE_UNICO_PERD_PAR', self.DEDUCIBLE_PERDIDA_PARCIAL)
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
    BOTON_PDF_JS = """(producto) => {
        const tabla = [...document.querySelectorAll('table')].find(t => /Vlr\\.?\\s*prima/i.test(t.innerText));
        if (!tabla) return {estado: 'sin_tabla'};
        const filas = [...tabla.querySelectorAll('tbody tr')];
        const fila = filas.find(tr => tr.innerText.toLowerCase().includes(producto)) || filas[0];
        if (!fila) return {estado: 'sin_filas'};
        const atributos = e => [e.className && e.className.baseVal === undefined ? e.className : '', e.id, e.title, e.getAttribute('alt'),
            e.getAttribute('src'), e.getAttribute('href'), e.getAttribute('onclick'), e.getAttribute('aria-label')].join(' ');
        const candidatos = [...fila.querySelectorAll('a, button, img, i, span, input[type=image], [onclick]')]
            .filter(e => /pdf/i.test(atributos(e) + ' ' + (e.innerText || '')) && !/emitir|recotizar/i.test(e.innerText + ' ' + e.title));
        if (!candidatos.length) return {estado: 'sin_boton', html: fila.outerHTML.slice(0, 6000)};
        const boton = candidatos[0].closest('a, button, [onclick]') || candidatos[0];
        document.querySelectorAll('[data-aslan-pdf]').forEach(e => e.removeAttribute('data-aslan-pdf'));
        boton.setAttribute('data-aslan-pdf', '1');
        return {estado: 'ok'};
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
