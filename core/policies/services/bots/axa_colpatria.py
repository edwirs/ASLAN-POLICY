"""Bot de cotización para AXA Colpatria (Sucursal en línea de intermediarios, cotizador de Autos).

Flujo (mapeado con una sesión real exploratoria, no a ciegas):
  1. axacolpatria.co: menú «Ingresa a tu cuenta» (al pasar el mouse) > «Acceso a
     intermediarios» > INICIAR SESIÓN > tipo y número de documento + contraseña.
  2. Seleccionar perfil: «Administrador» (empresa y clave asesor vienen preseleccionadas) > INGRESAR.
  3. Menú HERRAMIENTAS > Gestor de ventas > Autos. El cotizador es un iframe (pws.axacolpatria.co).
  4. Paso 1 del cotizador: documento, género, fecha de nacimiento (AAAA/MM/DD), ¿0 km?, placa.
       - Si el portal conoce la placa, trae marca, línea, modelo y precio.
       - Si no, se marca «¿Tienes el código Fasecolda? Sí» y se digitan código Fasecolda,
         año del vehículo y placa; entonces trae marca, línea, modelo y precio.
       - Color = NEGRO, servicio = Particular, zona de circulación, tipo de vehículo = Familiar.
  5. Paso 2: tarjetas de productos (PLUS, ESENCIAL…), cada una con cuatro niveles de asistencia
     (Ninguna, Esencial, VIP, Plus). Se guardan los valores de la tarjeta PLUS y el nivel «Plus»
     de esa tarjeta queda como `prima_total`.
  6. Avisos del portal: «El vehículo tiene una póliza vigente» (no es una falla: AXA no cotiza ese
     vehículo) y «el servicio de cotización falló» (se devuelve tal cual).

Sesiones: al terminar (bien o mal) SIEMPRE se cierra sesión (menú del usuario > CERRAR SESIÓN) y se
verifica que el portal ya no reconoce la sesión.
"""
import logging
import os
import re
import time
from datetime import timedelta

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
    BotDatosError,
    BotNoCotizableError,
    BotPortalError,
    BotTimeout,
    RegistroErrorMixin,
    escribir_verificado,
    exigir_clave_al_dia,
    normalizar_texto,
)

logger = logging.getLogger(__name__)

URL_HOME_AUTENTICADO = 'https://sucursalenlinea.axacolpatria.co/group/site-sucursal-en-linea/home'
URL_AUTOS = 'https://sucursalenlinea.axacolpatria.co/group/site-sucursal-en-linea/herramientas/gestor-de-ventas/autos'
URL_LOGOUT_AUTENTICACION = ('https://autenticacion.axacolpatria.co/v2/logout?client_id=4ZRArYjkYfXTt1oAYEiLaswiCuxhgH51'
                            '&returnTo=https%3A%2F%2Fsucursalenlinea.axacolpatria.co')
PERFIL = 'Administrador'
COLOR = 'NEGRO'
SERVICIO = 'Particular'
TIPO_VEHICULO_PARTICULAR = 'Familiar'
TARJETA_PRINCIPAL = 'PLUS'
NIVEL_PRINCIPAL = 'PLUS'
NIVELES = ('NINGUNA', 'ESENCIAL', 'VIP', 'PLUS')

# Tipo de documento del sistema (abreviatura) -> opción del combo del cotizador.
DOCUMENTOS = {'CC': 'Cedula Ciudadanía', 'NIT': 'Nit'}

# Nombre del departamento (normalizado) -> opción de «Zona de circulación» cuando difiere.
ZONAS_ABREVIADAS = {
    'cundinamarca': 'C/MARCA',
    'norte de santander': 'N.SANTANDER',
    'santander': 'S/TANDER',
    'la guajira': 'GUAJIRA',
    'bogota- d.c.': 'BOGOTA',
    'bogota d.c.': 'BOGOTA',
    'bogota': 'BOGOTA',
}
ZONA_SIN_OPCION = 'OTRAS CIUDADES'

# Textos de las pantallas de carga de AXA (no son avisos ni errores: desaparecen solas al terminar de calcular).
PANTALLAS_DE_CARGA = ('espere un momento', 'estamos realizando la cotizacion', 'puede tardar mas de un minuto')

AVISO_JS = """() => { const m = [...document.querySelectorAll('.modal, [role=dialog]')]
    .find(e => e.getBoundingClientRect().width > 0 && getComputedStyle(e).visibility !== 'hidden' && (e.innerText || '').trim());
    return m ? m.innerText : null; }"""

LEE_VEHICULO_JS = """() => { const s = document.querySelector('#Marca');
    return {marca_valor: s ? s.value : '', marca: s && s.selectedIndex >= 0 ? s.options[s.selectedIndex].text : '',
            linea: (document.querySelector('#input_DDlinea') || {}).value || '',
            modelo: (document.querySelector('#input_SelectModel') || {}).value || '',
            precio: (document.querySelector('#VehiculeData_Price') || {}).value || ''}; }"""


def _dinero(texto):
    """Valor monetario de AXA: usa la coma como separador de miles (\$2,499,140) y no trae decimales."""
    from decimal import Decimal
    digitos = re.sub(r'\D', '', str(texto or ''))
    return Decimal(digitos) if digitos else Decimal('0')


def _limpiar_aviso(texto):
    """Quita la «×» inicial y el botón «CERRAR» final de un aviso del portal."""
    texto = re.sub(r'\s+', ' ', texto or '').strip()
    texto = re.sub(r'^[×x]\s*', '', texto)
    texto = re.sub(r'\s*CERRAR$', '', texto, flags=re.I)
    return re.sub(r'^Estimado usuario\.?\s*', '', texto, flags=re.I).strip()


class AxaColpatriaBot(RegistroErrorMixin):
    """Cotiza todo riesgo en AXA Colpatria. Uso: AxaColpatriaBot(cotizacion, headless=True).run()"""

    def __init__(self, cotizacion, headless=True):
        self.cotizacion = cotizacion
        self.vehiculo = cotizacion.vehiculo
        self._foto_vehiculo()
        self.tomador = self.vehiculo.tomador
        self.headless = headless
        self.credencial = self._get_credencial()
        # Dentro de sync_playwright Django usa otra conexión (schema public):
        # toda escritura a BD desde un paso del bot re-entra a este schema.
        self.schema_name = connection.schema_name
        self._precio = None
        self._credenciales_enviadas = False

    def _get_credencial(self):
        credencial = self.cotizacion.aseguradora.credenciales.filter(is_active=True).order_by('-id').first()
        if credencial is None:
            raise BotAutenticacionError(
                f'No hay una credencial activa configurada para "{self.cotizacion.aseguradora}".',
                accion='Cree o active la credencial de AXA Colpatria en Configuraciones › Aseguradoras y reenvíe la solicitud.',
            )
        exigir_clave_al_dia(credencial, self.cotizacion.aseguradora)
        return credencial

    # ------------------------------------------------------------------
    # Utilidades
    # ------------------------------------------------------------------

    def _set_estado(self, estado_bot, mensaje=None):
        with schema_context(self.schema_name):
            self.cotizacion.estado_bot = estado_bot
            if mensaje is not None:
                self.cotizacion.mensaje_bot = mensaje
            self.cotizacion.save(update_fields=['estado_bot', 'mensaje_bot'])

    def _capturar_diagnostico(self, page):
        """Screenshot al fallar. Nunca vuelca valores de inputs (podrían ser la contraseña)."""
        try:
            debug_dir = os.path.join(settings.MEDIA_ROOT, 'bot_debug')
            os.makedirs(debug_dir, exist_ok=True)
            stamp = timezone.now().strftime('%Y%m%d_%H%M%S')
            base = os.path.join(debug_dir, f'axa_{self.cotizacion.pk}_{stamp}')
            page.screenshot(path=f'{base}.png', full_page=True)
            logger.warning('Diagnóstico del bot AXA Colpatria guardado en %s.png', base)
        except Exception:
            logger.exception('No se pudo capturar el diagnóstico de AXA Colpatria tras la falla')

    @staticmethod
    def _marco(page):
        """El cotizador vive en un iframe de pws.axacolpatria.co (se vuelve a buscar tras cada envío)."""
        for frame in page.frames:
            if 'pws.axacolpatria.co' in frame.url.lower():
                return frame
        return None

    def _guardar_pantalla(self, page):
        """Antes de cerrar el navegador: guarda el aviso (modal) visible, también el del iframe."""
        super()._guardar_pantalla(page)
        if not self.ultima_alerta:
            try:
                marco = self._marco(page)
                if marco:
                    self.ultima_alerta = marco.evaluate(AVISO_JS)
            except Exception:
                pass

    @staticmethod
    def _aviso(marco):
        """Texto del aviso (modal) visible del portal, o None. «Espere un momento...» NO es un aviso: es la pantalla de
        carga de AXA mientras calcula (oscurece el formulario y desaparece sola), así que se sigue esperando."""
        try:
            texto = _limpiar_aviso(marco.evaluate(AVISO_JS)) or None
        except Exception:
            return None
        if texto and any(f in normalizar_texto(texto) for f in PANTALLAS_DE_CARGA):
            return None
        return texto

    def _error_de_aviso(self, texto, paso):
        """Convierte un aviso del portal en el error que explica qué pasó."""
        normal = normalizar_texto(texto)
        if 'poliza vigente' in normal:
            return BotNoCotizableError(
                f'AXA Colpatria no cotiza este vehículo: «{texto}».',
                accion='El vehículo ya tiene póliza vigente con AXA Colpatria: debe gestionarse directamente con AXA. '
                       'Cotice con las demás aseguradoras.',
            )
        if 'fallo' in normal:
            return BotPortalError(
                f'AXA Colpatria respondió: «{texto}».',
                accion='Reenvíe la solicitud a AXA Colpatria. Si se repite, cotice directamente en su portal.',
            )
        return BotPortalError(f'AXA Colpatria mostró un aviso en el paso «{paso}»: «{texto}».')

    def _dato_de_otras_fuentes(self, page, campo, timeout=180):
        """Valor de `campo` del vehículo según la BD. Si aún no está, espera a que otra aseguradora
        que cotiza el mismo vehículo lo capture; deja de esperar cuando ninguna sigue en curso."""
        from core.policies.models import Cotizacion, Vehiculo  # import local: evita ciclo al cargar el módulo

        limite = time.time() + timeout
        while True:
            with schema_context(self.schema_name):
                valor = Vehiculo.objects.filter(pk=self.vehiculo.pk).values_list(campo, flat=True).first()
                siguen = Cotizacion.objects.filter(
                    vehiculo=self.vehiculo,
                    estado_bot__in=('pendiente', 'en_proceso'),
                    created_at__gte=timezone.now() - timedelta(minutes=20),
                ).exclude(pk=self.cotizacion.pk).exists()
            if valor:
                return valor
            if not siguen or time.time() > limite:
                return None
            page.wait_for_timeout(4000)

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
                    self._paso('Perfil Administrador')
                    self._perfil_administrador(page)
                    self._paso('Herramientas > Gestor de ventas > Autos')
                    self._abrir_autos(page)
                    self._paso('Datos personales y placa')
                    self._datos_personales_y_placa(page)
                    self._paso('Datos del vehículo')
                    self._datos_vehiculo(page)
                    self._paso('Color, servicio y zona de circulación')
                    self._color_servicio_zona(page)
                    self._paso('Cotización (tarjetas)')
                    self._capturar_tarjetas(page)
                except (BotCancelado, BotTimeout):
                    raise
                except Exception:
                    self._guardar_pantalla(page)
                    self._capturar_diagnostico(page)
                    raise
                finally:
                    self._cerrar_sesion(page)
                    browser.close()

            self._set_estado('completado', mensaje=None)

        except BotCancelado:
            self._set_estado('cancelado', mensaje='El asesor canceló tras una alerta de confirmación.')
        except BotTimeout:
            self._set_estado('error', mensaje='Se agotó el tiempo esperando la confirmación del asesor.')
        except Exception as e:
            logger.exception('Error cotizando %s en AXA Colpatria', self.vehiculo.placa)
            self._registrar_error(e)

    # ------------------------------------------------------------------
    # Ingreso
    # ------------------------------------------------------------------

    def _login(self, page):
        page.goto(self.credencial.portal_url, wait_until='domcontentloaded')
        self._cerrar_aviso_inicial(page)
        try:
            page.locator('a.btnSignInText:visible', has_text='Ingresa a tu cuenta').first.hover(timeout=15000)
            page.wait_for_timeout(1200)
            page.locator('a:visible', has_text='Acceso a intermediarios').first.click(timeout=10000)
        except PlaywrightTimeoutError:
            # Si el menú que se despliega con el mouse no responde, se va directo a la misma dirección.
            page.goto('https://sucursalenlinea.axacolpatria.co', wait_until='domcontentloaded')
        # La página intermedia de la sucursal en línea (botón INICIAR SESIÓN) puede tardar mucho en cargar, y
        # los servidores de AXA a veces responden 502/503/504: ante un error se reintenta la entrada (hasta 3 veces).
        boton = page.locator('a, button', has_text=re.compile(r'iniciar sesi', re.I))
        pulsado = False
        reintentos = 0
        for _ in range(150):
            if page.locator('#docNumber').count():
                break
            if page.locator('#_ProfileSelector_profileSelection').count():
                return  # el portal ya traía una sesión: va directo a la selección de perfil
            caido = self._error_de_servidor(page)
            if caido:
                reintentos += 1
                if reintentos > 3:
                    raise self._servidor_caido(caido)
                page.wait_for_timeout(8000)
                page.goto('https://sucursalenlinea.axacolpatria.co', wait_until='domcontentloaded')
                pulsado = False
                continue
            if not pulsado and boton.count():
                try:
                    boton.first.click(timeout=5000, force=True)
                    pulsado = True
                except Exception:
                    pass
            page.wait_for_timeout(1000)
        page.locator('#docNumber').wait_for(timeout=5000)
        self._tipo_documento_login(page)
        # Se teclea de verdad (el formulario de ingreso no avanza con valores puestos por código).
        escribir_verificado(page, page.locator('#docNumber'), self.credencial.username, delay=50)
        escribir_verificado(page, page.locator('#password'), self.credencial.password, delay=50)
        page.locator('#btn-login').click()
        self._credenciales_enviadas = True

        for _ in range(240):  # el ingreso de este portal es lento (puede pasar de 2 minutos)
            if page.locator('#_ProfileSelector_profileSelection').count() or 'Seleccionar perfil' in page.title():
                return
            caido = self._error_de_servidor(page)
            if caido:
                raise self._servidor_caido(caido)
            error = self._error_de_ingreso(page)
            if error:
                raise BotAutenticacionError(
                    f'AXA Colpatria no permitió el ingreso: «{error}».',
                    accion='Verifique el número de documento y la contraseña de AXA Colpatria en Configuraciones › '
                           'Aseguradoras y que la cuenta no esté bloqueada (el portal tiene «Desbloquear usuario»); '
                           'luego reenvíe la solicitud.',
                )
            page.wait_for_timeout(1000)
        raise BotAutenticacionError(
            'No se pudo iniciar sesión en AXA Colpatria: después de ingresar no apareció la selección de perfil '
            '(¿contraseña vencida o cuenta bloqueada?).')

    @staticmethod
    def _error_de_servidor(page):
        """Texto de la página de error cuando la sucursal en línea de AXA está caída o colgada
        (503 «Application is not available», 504 «Gateway Time-out», «Not found.»), o None."""
        try:
            cuerpo = re.sub(r'\s+', ' ', page.evaluate('document.body ? document.body.innerText : ""') or '').strip()
            titulo = page.title().strip().lower()
        except Exception:
            return None
        minus = cuerpo.lower()
        if ('application is not available' in minus or 'gateway time-out' in minus or 'bad gateway' in minus
                or 'service unavailable' in minus or titulo in ('error', '502 bad gateway', '503 service unavailable', '504 gateway time-out')
                or minus in ('not found.', 'not found')):
            return cuerpo[:160] or titulo or 'página de error'
        return None

    def _servidor_caido(self, texto):
        return BotPortalError(
            f'La sucursal en línea de AXA Colpatria no está respondiendo (error del servidor de AXA: «{texto}»).',
            accion='No es un problema de los datos ni de la cuenta. Reenvíe a AXA Colpatria en unos minutos; si persiste, '
                   'avise a AXA Colpatria o a soporte.',
        )

    @staticmethod
    def _cerrar_aviso_inicial(page):
        """El home de axacolpatria.co abre un aviso informativo que tapa la página."""
        try:
            page.locator('.modal-dialog [class*=close]:visible').first.click(timeout=6000)
            page.wait_for_timeout(800)
        except Exception:
            pass

    def _tipo_documento_login(self, page):
        tipo = normalizar_texto(self.credencial.tipo_documento or 'Cédula de ciudadanía')
        opciones = page.evaluate("() => [...document.querySelectorAll('#docType option')].map(o => [o.value, o.text])")
        elegido = next((v for v, t in opciones if normalizar_texto(t) == tipo), None) or \
            next((v for v, t in opciones if tipo and tipo in normalizar_texto(t)), None) or 'CC'
        page.select_option('#docType', value=elegido)

    @staticmethod
    def _error_de_ingreso(page):
        """Texto de error visible en la pantalla de ingreso, si hay (solo mientras sigue en el login)."""
        try:
            if 'autenticacion.axacolpatria.co' not in page.url:
                return None
            texto = page.evaluate(
                """() => { const e = [...document.querySelectorAll('[class*=error], [class*=alert], [role=alert], .invalid-feedback')]
                    .find(x => x.getBoundingClientRect().width > 0 && (x.innerText || '').trim());
                    return e ? e.innerText : null; }""")
            return re.sub(r'\s+', ' ', texto or '').strip()[:200] or None
        except Exception:
            return None

    def _perfil_administrador(self, page):
        selector = page.locator('#_ProfileSelector_profileSelection')
        selector.wait_for(timeout=45000)
        selector.select_option(label=PERFIL)
        page.locator('#_ProfileSelector_companySelection:visible').wait_for(timeout=20000)
        page.locator('[id*="ProfileSelector"]:visible', has_text=re.compile(r'^\s*INGRESAR\s*$', re.I)).first.click()
        for _ in range(270):
            if 'Seleccionar perfil' not in page.title() and page.locator('#dropdownMenuUser:visible').count():
                return
            caido = self._error_de_servidor(page)
            if caido:
                raise self._servidor_caido(caido)
            page.wait_for_timeout(1000)
        raise BotPortalError('AXA Colpatria no abrió la sucursal en línea después de elegir el perfil Administrador.')

    def _abrir_autos(self, page):
        try:
            page.locator('a:visible', has_text='HERRAMIENTAS').first.hover(timeout=15000)
            page.wait_for_timeout(1200)
            page.locator('a:visible[href$="gestor-de-ventas/autos"]').first.click(timeout=10000)
        except PlaywrightTimeoutError:
            page.goto(URL_AUTOS, wait_until='domcontentloaded')
        # El iframe muestra el formulario (botón Continuar) mucho antes de terminar de cargar: sus scripts pueden
        # tardar ~45 s o más, y los combos (flechas `a_<id>`) solo se arman al final. Se espera a que existan; si
        # no, el primer clic en un combo expira y parece una falla de datos.
        formulario = False
        for _ in range(240):
            marco = self._marco(page)
            try:
                if marco and marco.locator('#btnContinuar').count():
                    formulario = True
                    if marco.locator('#a_People_IdDocumentType').count():
                        page.wait_for_timeout(1500)
                        return
            except Exception:
                pass
            caido = self._error_de_servidor(page)
            if caido:
                raise self._servidor_caido(caido)
            page.wait_for_timeout(1000)
        if formulario:
            raise BotPortalError(
                'AXA Colpatria mostró el cotizador de Autos pero no terminó de cargarlo (sus campos no se activaron) '
                'después de 240 segundos.')
        raise BotPortalError('AXA Colpatria no mostró el cotizador de Autos después de 240 segundos.')

    # ------------------------------------------------------------------
    # Cotizador: paso 1
    # ------------------------------------------------------------------

    def _elegir_en_combo(self, page, base, texto):
        """Combos de jQuery UI del cotizador: se abren con la flecha (`a_<id>`) y la lista es `ul.ui-autocomplete`."""
        marco = self._marco(page)
        marco.locator(f'#a_{base}').click(timeout=15000)
        page.wait_for_timeout(700)
        patron = re.compile(rf'^\s*{re.escape(texto)}\s*$', re.I)
        opcion = marco.locator('ul.ui-autocomplete:visible li').filter(has_text=patron).first
        try:
            opcion.click(timeout=6000)
        except PlaywrightTimeoutError:
            opciones = [t.strip() for t in marco.locator('ul.ui-autocomplete:visible li').all_inner_texts()]
            raise BotDatosError(
                f'AXA Colpatria no ofrece «{texto}» en este campo del cotizador (opciones: {", ".join(opciones) or "ninguna"}).',
                accion='Revise el dato en la solicitud y reenvíe a AXA Colpatria; si el valor fijo ya no existe, avise a soporte.',
            )
        page.wait_for_timeout(700)

    def _datos_personales_y_placa(self, page):
        marco = self._marco(page)
        abreviatura = (self.tomador.document_type.abbreviation or '').upper()
        opcion_documento = DOCUMENTOS.get(abreviatura)
        if opcion_documento is None:
            raise BotDatosError(
                f'AXA Colpatria solo ofrece cédula de ciudadanía y NIT; el tomador tiene «{self.tomador.document_type.name}».',
                accion='Cotice este caso directamente en el portal de AXA Colpatria.',
            )
        self._elegir_en_combo(page, 'People_IdDocumentType', opcion_documento)

        marco.locator('#People_DocumentNumber:visible').first.fill(self.tomador.dni)
        etiqueta_genero = 'MASCULINO' if (self.tomador.gender or 'male') == 'male' else 'FEMENINO'
        marco.locator('label:visible', has_text=etiqueta_genero).first.click()
        fecha = marco.locator('#People_BirthDate:visible').first
        fecha.fill(self.tomador.birthdate.strftime('%Y/%m/%d'))  # formato del portal: año/mes/día
        fecha.dispatch_event('change')
        fecha.press('Tab')
        page.keyboard.press('Escape')

        cero_km = 'SI' if self.vehiculo.es_cero_km else 'NO'
        marco.locator('label:visible', has_text=re.compile(rf'^\s*{cero_km}\s*$')).first.click()
        marco.locator('#VehiculeData_Plaque:visible').first.fill(self.placa_portal)
        self._rellenar_email(page)

        marco.locator('#btnContinuar:visible').first.click()
        self._esperar_vehiculo(page, 'Datos personales y placa')

    def _rellenar_email(self, page):
        """Si el portal pide el correo (personas que no conoce), se completa con el del tomador."""
        marco = self._marco(page)
        correo = marco.locator('#People_Email:visible')
        if correo.count() and not correo.first.input_value() and self.tomador.email:
            correo.first.fill(self.tomador.email)

    def _esperar_vehiculo(self, page, paso, timeout=150):
        """Espera la sección de datos del vehículo; si antes sale un aviso del portal, lo explica. El servidor de AXA
        puede tardar más de un minuto en validar la placa (y el aviso llega al final), por eso el plazo es largo."""
        for _ in range(timeout):
            marco = self._marco(page)
            if marco is not None:
                aviso = self._aviso(marco)
                if aviso:
                    raise self._error_de_aviso(aviso, paso)
                try:
                    if marco.locator('#input_VehiculeData_Color:visible').count():
                        self._esperar_aviso_tardio(page, paso)
                        return
                except PlaywrightTimeoutError:
                    pass
                except BotPortalError:
                    raise
                except Exception:
                    pass
            page.wait_for_timeout(1000)
        raise BotPortalError(f'AXA Colpatria no mostró los datos del vehículo en el paso «{paso}» después de {timeout} segundos.')

    def _esperar_aviso_tardio(self, page, paso, segundos=90):
        """Los campos del vehículo aparecen antes que el aviso «El vehículo tiene una póliza vigente» (que con el
        servidor lento de AXA puede tardar más de un minuto): se vigila hasta que el portal resuelva el vehículo
        (marca cargada, pasados unos segundos sin aviso) o se agote el plazo. Si el portal no conoce la placa, el
        vehículo nunca se resuelve y se espera todo el plazo antes de pasar a la búsqueda por código Fasecolda;
        así no se sigue llenando un formulario que el portal ya rechazó (y que reinicia al mostrar el aviso)."""
        resuelto = 0
        for _ in range(segundos):
            marco = self._marco(page)
            aviso = self._aviso(marco) if marco is not None else None
            if aviso:
                raise self._error_de_aviso(aviso, paso)
            try:
                resuelto = resuelto + 1 if marco is not None and self._vehiculo_resuelto(page) else 0
            except Exception:
                resuelto = 0
            if resuelto >= 10:
                return
            page.wait_for_timeout(1000)

    # ------------------------------------------------------------------
    # Cotizador: datos del vehículo
    # ------------------------------------------------------------------

    def _vehiculo_resuelto(self, page):
        return (self._marco(page).evaluate(LEE_VEHICULO_JS).get('marca_valor') or '0') not in ('0', '')

    def _datos_vehiculo(self, page):
        """Si el portal no conoce la placa hay que dárselo por código Fasecolda (y año del vehículo)."""
        if not self._vehiculo_resuelto(page):
            self._buscar_por_fasecolda(page)
        datos = self._marco(page).evaluate(LEE_VEHICULO_JS)
        self._precio = _dinero(datos.get('precio'))
        self._guardar_vehiculo(datos)

    def _buscar_por_fasecolda(self, page):
        codigo = self.vehiculo.codigo_fasecolda or self._dato_de_otras_fuentes(page, 'codigo_fasecolda')
        if not codigo:
            raise BotDatosError(
                f'AXA Colpatria no reconoció el vehículo de placa «{self.vehiculo.placa}» y no hay código Fasecolda para '
                'buscarlo (ninguna otra aseguradora lo capturó a tiempo).',
                accion='Reenvíe a AXA Colpatria cuando otra aseguradora haya leído el vehículo, o registre la solicitud '
                       'con el código Fasecolda y reenvíe.',
            )
        anio = self._modelo_vigente() or self._dato_de_otras_fuentes(page, 'modelo') or (timezone.now().year if self.vehiculo.es_cero_km else None)
        if not anio:
            raise BotDatosError(
                'AXA Colpatria pide el año del vehículo para buscarlo por código Fasecolda y no se tiene el modelo.',
                accion='Reenvíe cuando otra aseguradora haya leído el vehículo, o complete el modelo y reenvíe.',
            )
        marco = self._marco(page)
        marco.locator('label:visible', has_text=re.compile(r'^\s*Sí\s*$')).first.click()
        page.wait_for_timeout(1500)
        marco.locator('#CodFasecoldaInput:visible').first.fill(str(codigo))
        marco.locator('#AnioFasecoldaInput:visible').first.fill(str(anio))
        marco.locator('#VehiculeData_Plaque:visible').first.fill(self.placa_portal)
        self._rellenar_email(page)
        marco.locator('#btnContinuar:visible').first.click()
        for _ in range(90):
            page.wait_for_timeout(1000)
            marco = self._marco(page)
            aviso = self._aviso(marco)
            if aviso:
                raise self._error_de_aviso(aviso, 'Datos del vehículo')
            if self._vehiculo_resuelto(page):
                page.wait_for_timeout(1000)
                return
        raise BotDatosError(
            f'AXA Colpatria no reconoció el código Fasecolda «{codigo}» con año {anio} para la placa «{self.vehiculo.placa}».',
            accion='Revise el código Fasecolda y el modelo del vehículo y reenvíe a AXA Colpatria.',
        )

    def _guardar_vehiculo(self, datos):
        """Guarda en Vehiculo lo que AXA resolvió y el precio como valor asegurado de la cotización."""
        modelo = re.sub(r'\D', '', datos.get('modelo') or '')
        with schema_context(self.schema_name):
            v = self.vehiculo
            if datos.get('marca') and normalizar_texto(datos['marca']) != 'seleccione':
                v.marca = datos['marca'].strip().upper()
            if datos.get('linea'):
                v.referencia = datos['linea'].strip()
            if modelo:
                self._fijar_modelo(modelo)
            if self._precio and not v.valor_comercial:
                v.valor_comercial = self._precio
            self._guardar_vehiculo_cambios()
            if self._precio:
                self.cotizacion.valor_asegurado = self._precio
                self.cotizacion.save(update_fields=['valor_asegurado'])

    def _color_servicio_zona(self, page):
        self._elegir_en_combo(page, 'VehiculeData_Color', COLOR)
        self._elegir_en_combo(page, 'VehiculeData_VehicleServiceType', SERVICIO)
        page.wait_for_timeout(1200)
        self._elegir_en_combo(page, 'VehiculeData_IdCIrculationZone', self._opcion_zona(page))
        self._elegir_en_combo(page, 'VehiculeData_IdTypePrivateVehicle', TIPO_VEHICULO_PARTICULAR)

        marco = self._marco(page)
        marco.locator('#btnContinuar:visible').first.click()
        for _ in range(200):
            page.wait_for_timeout(1000)
            marco = self._marco(page)
            if marco is None:
                continue
            aviso = self._aviso(marco)
            if aviso:
                raise self._error_de_aviso(aviso, 'Color, servicio y zona de circulación')
            try:
                if 'Productos disponibles' in marco.evaluate('document.body.innerText'):
                    return
            except Exception:
                pass
        raise BotPortalError('AXA Colpatria no mostró los productos disponibles después de 200 segundos.')

    def _opcion_zona(self, page):
        """Zona de circulación: el municipio si el portal lo ofrece como zona propia (Cartago, Sevilla…);
        si no, el departamento (con las abreviaturas del portal: C/MARCA, N.SANTANDER…) y, si tampoco,
        «OTRAS CIUDADES»."""
        marco = self._marco(page)
        marco.locator('#a_VehiculeData_IdCIrculationZone').click(timeout=15000)
        page.wait_for_timeout(700)
        opciones = [t.strip() for t in marco.locator('ul.ui-autocomplete:visible li').all_inner_texts()]
        page.keyboard.press('Escape')
        page.wait_for_timeout(400)
        por_normal = {normalizar_texto(o): o for o in opciones}
        municipio = self.vehiculo.zona_circulacion
        depto = normalizar_texto(municipio.departamento.nombre)
        for candidato in (normalizar_texto(municipio.nombre), normalizar_texto(ZONAS_ABREVIADAS.get(depto, '')), depto):
            if candidato and candidato in por_normal:
                return por_normal[candidato]
        if normalizar_texto(ZONA_SIN_OPCION) in por_normal:
            return por_normal[normalizar_texto(ZONA_SIN_OPCION)]
        raise BotDatosError(
            f'AXA Colpatria no ofrece una zona de circulación para «{municipio}» (opciones: {", ".join(opciones) or "ninguna"}).',
            accion='Revise la ciudad de circulación de la solicitud y reenvíe a AXA Colpatria.',
        )

    # ------------------------------------------------------------------
    # Cotizador: paso 2 (tarjetas)
    # ------------------------------------------------------------------

    def _capturar_tarjetas(self, page):
        """Cada tarjeta (PLUS, ESENCIAL…) trae cuatro niveles de asistencia con su valor. Se guardan los de la
        tarjeta PLUS (o, si el vehículo no la ofrece, los de la primera) y el nivel «Plus» es la prima_total."""
        marco = self._marco(page)
        cuerpo = marco.evaluate('document.body.innerText') or ''
        patron = (r'([A-ZÁÉÍÓÚÑ][A-ZÁÉÍÓÚÑ ]{2,}?)\s+NINGUNA\s+\$\s*([\d.,]+)\s+ESENCIAL\s+\$\s*([\d.,]+)'
                  r'\s+VIP\s+\$\s*([\d.,]+)\s+PLUS\s+\$\s*([\d.,]+)')
        tarjetas = []
        for titulo, *valores in re.findall(patron, cuerpo):
            if titulo.strip() not in {t for t, _ in tarjetas}:
                tarjetas.append((titulo.strip(), dict(zip(NIVELES, valores))))
        if not tarjetas:
            raise BotPortalError(
                'No se pudieron leer las tarjetas de productos de AXA Colpatria. '
                f'La pantalla decía: «{re.sub(chr(10), " ", cuerpo)[-300:]}».')

        principal = next(((t, v) for t, v in tarjetas if t.upper() == TARJETA_PRINCIPAL), tarjetas[0])
        titulo, valores = principal

        from core.policies.models import CotizacionPlan  # import local: evita ciclo al cargar el módulo

        with schema_context(self.schema_name):
            self.cotizacion.planes.all().delete()
            for nivel in NIVELES:
                nombre = 'VIP' if nivel == 'VIP' else nivel.title()
                CotizacionPlan.objects.create(cotizacion=self.cotizacion, nombre_plan=nombre, prima_total=_dinero(valores[nivel]))
            self.cotizacion.prima_total = _dinero(valores[NIVEL_PRINCIPAL])
            self.cotizacion.moneda = 'Pesos'
            nota = f'Valores de la tarjeta {titulo} según el nivel de asistencia (Ninguna, Esencial, VIP, Plus).'
            if titulo.upper() != TARJETA_PRINCIPAL:
                nota = (f'Este vehículo no tiene tarjeta {TARJETA_PRINCIPAL.title()}: se guardaron los valores de la tarjeta {titulo}. '
                        'Niveles de asistencia: Ninguna, Esencial, VIP, Plus.')
            self.cotizacion.mensaje_bot = nota
            self.cotizacion.save()

    # ------------------------------------------------------------------
    # Cierre de sesión
    # ------------------------------------------------------------------

    def _cerrar_sesion(self, page):
        """Cierra sesión SIEMPRE y verifica que el portal ya no la reconoce, sin lanzar excepción.
        Según dónde haya quedado el bot: menú del usuario > CERRAR SESIÓN (dentro de la sucursal) o
        botón SALIR (en la selección de perfil); y, si las credenciales ya se enviaron, también se cierra
        la sesión de autenticación (existe aunque la sucursal no haya llegado a cargar). Se reintenta una vez."""
        if page is None:
            return
        for intento in (1, 2):
            try:
                if page.is_closed():
                    return
                if self._cerrar_una_vez(page):
                    return
            except Exception:
                pass
            if intento == 1:
                try:
                    page.wait_for_timeout(5000)
                except Exception:
                    return
        logger.warning('AXA Colpatria: NO se pudo confirmar que la sesión quedó cerrada (revisar la cuenta).')

    def _cerrar_una_vez(self, page):
        """Un intento de cierre. True si queda verificado (o no había sesión que cerrar)."""
        cerro_algo = False
        if page.locator('#dropdownMenuUser:visible').count():
            page.locator('#dropdownMenuUser:visible').first.click(timeout=8000)
            page.wait_for_timeout(1000)
            page.locator('a:visible', has_text=re.compile(r'^\s*CERRAR SESI', re.I)).first.click(timeout=8000)
            page.wait_for_timeout(5000)
            cerro_algo = True
        elif page.locator('#_ProfileSelector_profileSelection').count():
            page.locator('[id*="ProfileSelector"]:visible', has_text=re.compile(r'^\s*SALIR\s*$', re.I)).first.click(timeout=8000)
            page.wait_for_timeout(5000)
            cerro_algo = True
        if self._credenciales_enviadas:
            # La sesión de autenticación (Auth0) existe aunque la sucursal haya fallado: se cierra directo.
            page.goto(URL_LOGOUT_AUTENTICACION, wait_until='domcontentloaded', timeout=90000)
            page.wait_for_timeout(3000)
            cerro_algo = True
        if not cerro_algo:
            return True  # nunca llegó a ingresar
        page.goto(URL_HOME_AUTENTICADO, wait_until='domcontentloaded', timeout=90000)
        page.wait_for_timeout(4000)
        return not page.locator('#dropdownMenuUser:visible').count() and not page.locator('#_ProfileSelector_profileSelection').count()
