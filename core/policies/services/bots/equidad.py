"""Bot de cotización para La Equidad Seguros (portal «Póliza E», producto Auto protegido).

Flujo (mapeado con una sesión real exploratoria, no a ciegas):
  1. Inicio de sesión: «Tipo persona» = Intermediario + email + contraseña.
  2. Elegir el producto «Auto protegido».
  3. Asistente de 4 pasos:
       Asegurado  -> tipo y número de documento; luego los datos personales
                     (el portal los trae si ya conoce a la persona; solo se
                     completan los que vengan vacíos).
       Vehículo   -> placa; el portal trae marca, modelo, referencia, uso y
                     valores; solo se escribe la zona de circulación.
       Descuentos -> se captura el «descuento aplicado».
       Cobertura  -> tres tarjetas (Plan Full, Plan RCE, Plan Ligero); se
                     captura la «prima total anual» de cada una y el Plan
                     Full queda como `prima_total`.
  4. Avisos del portal que NO son una falla: el vehículo ya está asegurado con
     La Equidad, o el modelo es anterior a 2008 (solo asegura 2008 en adelante).

Sesiones: al terminar (bien o mal) SIEMPRE se cierra sesión (el portal pide
confirmar con «Aceptar»).
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
    dividir_nombre,
    escribir_verificado,
    exigir_clave_al_dia,
    normalizar_texto,
    parse_money,
)

logger = logging.getLogger(__name__)

TIPO_PERSONA = 'Intermediario'
PRODUCTO = 'Auto protegido'
MODELO_MINIMO = 2008
PLAN_PRINCIPAL = 'full'

# Abreviatura del tipo de documento del sistema -> opción del selector del portal.
DOCUMENTOS = {
    'CC': 'CEDULA CIUDADANIA',
    'CE': 'CEDULA EXTRANJERIA',
    'TI': 'TARJETA DE IDENTIDAD',
    'NIT': 'NIT',
}

LEE_VEHICULO_JS = """() => Object.fromEntries(
    ['marca', 'modelo', 'referencia', 'uso', 'zona', 'valorAsegurado', 'accesorio', 'blindaje']
        .map(n => { const e = document.querySelector('input[formcontrolname=' + n + ']'); return [n, e ? e.value : '']; }))"""

LEE_PLANES_JS = """() => [...document.querySelectorAll('mat-card')]
    .filter(c => c.querySelector('.titulo-plan'))
    .map(c => {
        const lineas = c.innerText.split('\\n').map(x => x.trim()).filter(Boolean);
        const valor = etiqueta => { const i = lineas.findIndex(l => l.toLowerCase().startsWith(etiqueta)); return i >= 0 ? (lineas[i + 1] || null) : null; };
        return {nombre: c.querySelector('.titulo-plan').innerText.trim(),
                anual: valor('valor prima total anual'), mensual: valor('valor prima total mensual')};
    })"""

DIALOGO_JS = """() => { const d = [...document.querySelectorAll('mat-dialog-container')]
    .find(e => e.getBoundingClientRect().width > 0 && (e.innerText || '').trim());
    return d ? d.innerText : null; }"""


def _limpiar_dialogo(texto):
    """Quita el «close» del botón y los espacios sobrantes de un aviso del portal."""
    texto = re.sub(r'\s+', ' ', texto or '').strip()
    return re.sub(r'^close\s+', '', texto, flags=re.I).strip()


class EquidadBot(RegistroErrorMixin):
    """Cotiza todo riesgo en La Equidad. Uso: EquidadBot(cotizacion, headless=True).run()"""

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
        self._datos_extra = {}

    def _get_credencial(self):
        credencial = self.cotizacion.aseguradora.credenciales.filter(is_active=True).order_by('-id').first()
        if credencial is None:
            raise BotAutenticacionError(
                f'No hay una credencial activa configurada para "{self.cotizacion.aseguradora}".',
                accion='Cree o active la credencial de La Equidad en Configuraciones › Aseguradoras y reenvíe la solicitud.',
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
        """Screenshot + textos visibles al fallar. Nunca vuelca valores de inputs
        (podrían ser la contraseña)."""
        try:
            debug_dir = os.path.join(settings.MEDIA_ROOT, 'bot_debug')
            os.makedirs(debug_dir, exist_ok=True)
            stamp = timezone.now().strftime('%Y%m%d_%H%M%S')
            base = os.path.join(debug_dir, f'equidad_{self.cotizacion.pk}_{stamp}')
            page.screenshot(path=f'{base}.png', full_page=True)
            logger.warning('Diagnóstico del bot La Equidad guardado en %s.png', base)
        except Exception:
            logger.exception('No se pudo capturar el diagnóstico de La Equidad tras la falla')

    @staticmethod
    def _dialogo(page):
        try:
            return _limpiar_dialogo(page.evaluate(DIALOGO_JS)) or None
        except Exception:
            return None

    @staticmethod
    def _cerrar_dialogo(page):
        try:
            page.get_by_label('Cerrar cuadro de informacion').first.click(timeout=3000)
            page.wait_for_timeout(600)
        except Exception:
            pass

    def _error_de_aviso(self, texto, paso):
        """Convierte un aviso (modal) del portal en el error que explica qué pasó."""
        normal = normalizar_texto(texto)
        if 'asegurado con la compania' in normal:
            return BotNoCotizableError(
                f'La Equidad no cotiza este vehículo: «{texto}».',
                accion='El vehículo ya tiene póliza con La Equidad: debe gestionarse directamente con su oficina de La '
                       'Equidad. Cotice con las demás aseguradoras.',
            )
        if 'no es posible cotizar' in normal:
            return BotPortalError(
                f'La Equidad no pudo cotizar en este momento: «{texto}».',
                accion='Reenvíe la solicitud a La Equidad. Si se repite, comuníquese con el área técnica de La Equidad '
                       '(Soporte.autos@laequidadseguros.coop).',
            )
        return BotPortalError(f'La Equidad mostró un aviso en el paso «{paso}»: «{texto}».')

    def _esperar_visible(self, page, selector, paso, timeout=40, sondeo_ms=700):
        """Espera a que `selector` aparezca; si antes sale un aviso del portal, lo explica."""
        for _ in range(int(timeout * 1000 / sondeo_ms)):
            if page.locator(selector).first.is_visible():
                return
            aviso = self._dialogo(page)
            if aviso:
                raise self._error_de_aviso(aviso, paso)
            page.wait_for_timeout(sondeo_ms)
        raise BotPortalError(
            f'La Equidad no mostró la pantalla esperada en el paso «{paso}» después de {timeout} segundos.')

    @staticmethod
    def _continuar(page):
        # El asistente conserva en el DOM los botones de los pasos anteriores y, al avanzar,
        # el del paso que sale sigue visible un instante mientras se anima. Los pasos van en
        # orden en el DOM, así que el «Continuar» del paso actual es siempre el último visible.
        return page.locator('button:visible', has_text=re.compile(r'^\s*Continuar\s*$', re.I)).last

    def _cerrar_sesion(self, page):
        """Cierra sesión SIEMPRE, sin lanzar excepción: cierra avisos abiertos, menú de
        usuario > Cerrar sesión > Aceptar (el portal pide confirmar)."""
        if page is None:
            return
        try:
            if page.is_closed():
                return
            self._cerrar_dialogo(page)
            if page.locator('mat-select[formcontrolname="tipoLogin"]').count():
                return  # ya está en la pantalla de ingreso
            page.locator('div.mat-menu-trigger.etiquetas').first.click(timeout=5000)
            page.get_by_text('Cerrar sesión', exact=True).first.click(timeout=5000)
            page.get_by_role('button', name=re.compile(r'^Aceptar$', re.I)).first.click(timeout=5000)
            page.locator('mat-select[formcontrolname="tipoLogin"]').first.wait_for(timeout=10000)
        except Exception:
            logger.warning('La Equidad: no se pudo confirmar que la sesión quedó cerrada (revisar).')

    # ------------------------------------------------------------------
    # Orquestación
    # ------------------------------------------------------------------

    def run(self):
        self._set_estado('en_proceso', mensaje=None)
        with schema_context(self.schema_name):
            self.cotizacion.ejecutado_en = timezone.now()
            self.cotizacion.save(update_fields=['ejecutado_en'])

        try:
            self._validar_antes_de_abrir_portal()
            with sync_playwright() as playwright:
                browser = playwright.chromium.launch(headless=self.headless)
                contexto = browser.new_context(viewport={'width': 1366, 'height': 900})
                page = contexto.new_page()
                try:
                    self._paso(PASO_LOGIN)
                    self._login(page)
                    self._paso('Elegir producto Auto protegido')
                    self._elegir_producto(page)
                    self._paso('Asegurado (documento)')
                    self._documento(page)
                    self._paso('Asegurado (datos personales)')
                    self._datos_personales(page)
                    self._paso('Vehículo (placa)')
                    self._placa(page)
                    self._paso('Vehículo (datos y zona de circulación)')
                    self._datos_vehiculo(page)
                    self._paso('Descuentos')
                    self._descuento(page)
                    self._paso('Cobertura (planes)')
                    self._capturar_planes(page)
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
            logger.exception('Error cotizando %s en La Equidad', self.vehiculo.placa)
            self._registrar_error(e)

    # ------------------------------------------------------------------
    # Pasos
    # ------------------------------------------------------------------

    def _validar_antes_de_abrir_portal(self):
        """Reglas conocidas que no requieren abrir el portal (ahorra una sesión)."""
        self._paso('Validación del vehículo')
        if self.vehiculo.modelo and self.vehiculo.modelo < MODELO_MINIMO:
            raise self._error_modelo(self.vehiculo.modelo)

    @staticmethod
    def _error_modelo(modelo):
        return BotNoCotizableError(
            f'La Equidad solo asegura vehículos modelo {MODELO_MINIMO} en adelante; este vehículo es modelo {modelo}.',
            accion='No se puede cotizar este vehículo con La Equidad: cotice con las demás aseguradoras.',
        )

    def _login(self, page):
        page.goto(self.credencial.portal_url, wait_until='domcontentloaded')
        tipo = page.locator('mat-select[formcontrolname="tipoLogin"]')
        tipo.wait_for(timeout=30000)
        tipo.click()
        page.locator('mat-option').filter(has_text=re.compile(rf'^\s*{TIPO_PERSONA}\s*$', re.I)).first.click(timeout=10000)
        escribir_verificado(page, page.locator('input[formcontrolname="USUARIO"]'), self.credencial.username, delay=50)
        escribir_verificado(page, page.locator('input[formcontrolname="PASSWORD"]'), self.credencial.password, delay=50)
        page.get_by_role('button', name=re.compile(r'^Ingresar$', re.I)).first.click()
        for _ in range(35):
            if page.get_by_text(PRODUCTO, exact=True).first.is_visible():
                return
            aviso = self._dialogo(page) or self._mensaje_visible(page)
            if aviso:
                raise BotAutenticacionError(
                    f'La Equidad no permitió el ingreso: «{aviso}».',
                    accion='Verifique el usuario y la contraseña de La Equidad en Configuraciones › Aseguradoras y que la '
                           'cuenta no esté bloqueada; luego reenvíe la solicitud.',
                )
            page.wait_for_timeout(1000)
        raise BotAutenticacionError(
            'No se pudo iniciar sesión en La Equidad: después de ingresar no apareció la lista de productos '
            '(¿contraseña vencida o cuenta bloqueada?).')

    @staticmethod
    def _mensaje_visible(page):
        """Mensaje de error de formulario o aviso emergente de Angular Material, si hay uno."""
        try:
            texto = page.evaluate(
                """() => { const e = [...document.querySelectorAll('mat-error, .mat-snack-bar-container, .mat-simple-snackbar')]
                    .find(x => x.getBoundingClientRect().width > 0 && (x.innerText || '').trim());
                    return e ? e.innerText : null; }""")
            return _limpiar_dialogo(texto) or None
        except Exception:
            return None

    def _elegir_producto(self, page):
        page.get_by_text(PRODUCTO, exact=True).first.click()
        self._esperar_visible(page, 'mat-select[formcontrolname="tipoDocumento"]', 'Elegir producto Auto protegido', timeout=30)

    def _opcion_documento(self):
        abreviatura = (self.tomador.document_type.abbreviation or '').upper()
        opcion = DOCUMENTOS.get(abreviatura)
        if opcion is None:
            raise BotDatosError(
                f'La Equidad no ofrece el tipo de documento «{self.tomador.document_type.name}» para el asegurado '
                f'(solo: {", ".join(DOCUMENTOS.values())}).',
                accion='Cotice este caso directamente en el portal de La Equidad.',
            )
        return opcion

    def _documento(self, page):
        opcion = self._opcion_documento()
        page.locator('mat-select[formcontrolname="tipoDocumento"]').click()
        page.locator('mat-option').filter(has_text=re.compile(rf'^\s*{re.escape(opcion)}\s*$', re.I)).first.click(timeout=10000)
        escribir_verificado(page, page.locator('input[formcontrolname="numeroDocumento"]'), self.tomador.dni, delay=45)
        self._continuar(page).click(timeout=15000)
        self._esperar_visible(page, 'input[formcontrolname="primerNombre"]', 'Asegurado (documento)', timeout=40)
        page.wait_for_timeout(2000)  # el portal carga los datos de la persona justo después

    def _campo_vacio(self, page, nombre):
        campo = page.locator(f'input[formcontrolname="{nombre}"]')
        return campo.is_enabled() and not campo.input_value().strip()

    def _datos_personales(self, page):
        """El portal trae los datos de las personas que ya conoce; solo se completan
        los que vengan vacíos con los registrados al inicio de la solicitud."""
        primer_nombre, primer_apellido = dividir_nombre(self.tomador.names)
        for nombre, valor in (('primerNombre', primer_nombre), ('primerApellido', primer_apellido)):
            if self._campo_vacio(page, nombre):
                escribir_verificado(page, page.locator(f'input[formcontrolname="{nombre}"]'), valor.upper(), delay=45)

        genero = page.locator('mat-select[formcontrolname="genero"]')
        if 'mat-select-empty' in (genero.get_attribute('class') or ''):
            etiqueta = 'Masculino' if (self.tomador.gender or 'male') == 'male' else 'Femenino'
            genero.click()
            page.locator('mat-option').filter(has_text=re.compile(rf'^\s*{etiqueta}\s*$', re.I)).first.click(timeout=8000)
            page.wait_for_timeout(400)

        if self._campo_vacio(page, 'fechaNacimiento'):
            nac = self.tomador.birthdate
            campo = page.locator('input[formcontrolname="fechaNacimiento"]')
            campo.click()
            campo.press_sequentially(f'{nac.day}/{nac.month}/{nac.year}', delay=60)
            page.wait_for_timeout(400)

        continuar = self._continuar(page)
        if not continuar.is_enabled():
            raise BotDatosError(
                'La Equidad dejó deshabilitado «Continuar» en los datos del asegurado: falta o es inválido algún dato '
                f'(nombre «{primer_nombre} {primer_apellido}», nacimiento {self.tomador.birthdate:%d/%m/%Y}).',
                accion='Revise el nombre, el género y la fecha de nacimiento del tomador en la solicitud y reenvíe a La Equidad.',
            )
        continuar.click()
        self._esperar_visible(page, 'input[formcontrolname="placa"]', 'Asegurado (datos personales)', timeout=30)

    def _placa(self, page):
        escribir_verificado(page, page.locator('input[formcontrolname="placa"]'), self.placa_portal, delay=45)
        self._continuar(page).click(timeout=15000)
        self._esperar_visible(page, 'input[formcontrolname="marca"]', 'Vehículo (placa)', timeout=45)
        # Un indicador de espera tapa la pantalla mientras el portal trae los datos del vehículo.
        for _ in range(30):
            if page.locator('input[formcontrolname="marca"]').input_value():
                break
            page.wait_for_timeout(500)
        page.wait_for_timeout(1200)

    def _datos_vehiculo(self, page):
        valores = page.evaluate(LEE_VEHICULO_JS)
        self._guardar_vehiculo(valores)

        modelo = self._entero(valores.get('modelo'))
        if modelo is None:
            # Con vehículos anteriores a 2008 La Equidad NO precarga marca ni modelo (sí trae
            # la referencia y el valor). El modelo se toma entonces de lo que ya capturaron las
            # otras aseguradoras para esta placa, esperándolas si todavía están cotizando.
            modelo = self._modelo_de_otras_fuentes(page)
            if modelo is None:
                raise BotNoCotizableError(
                    f'La Equidad no cargó el modelo del vehículo (así responde con vehículos anteriores a {MODELO_MINIMO}) '
                    f'y ninguna otra aseguradora lo reportó: se asume que es anterior a {MODELO_MINIMO}, que La Equidad no cotiza.',
                    accion='Cotice con las demás aseguradoras. Si el vehículo es modelo 2008 o posterior, cotícelo '
                           'directamente en el portal de La Equidad.',
                )
            if modelo >= MODELO_MINIMO:
                raise BotPortalError(
                    f'La Equidad no cargó el modelo del vehículo aunque en nuestros datos es {modelo}.',
                    accion='Reenvíe la solicitud a La Equidad; si se repite, cotice directamente en su portal.',
                )
        if modelo < MODELO_MINIMO:
            raise self._error_modelo(modelo)

        self._escribir_zona(page)
        self._continuar(page).click(timeout=15000)
        self._esperar_visible(page, 'input[formcontrolname="descuento"]', 'Vehículo (datos y zona de circulación)', timeout=45)

    def _modelo_de_otras_fuentes(self, page, timeout=180):
        """Modelo (año) del vehículo según la BD. Si aún no está, espera a que otra aseguradora
        que cotiza el mismo vehículo lo capture; deja de esperar cuando ninguna sigue en curso."""
        from core.policies.models import Cotizacion, Vehiculo  # import local: evita ciclo al cargar el módulo

        limite = time.time() + timeout
        while True:
            with schema_context(self.schema_name):
                modelo = Vehiculo.objects.filter(pk=self.vehiculo.pk).values_list('modelo', flat=True).first()
                siguen = Cotizacion.objects.filter(
                    vehiculo=self.vehiculo,
                    estado_bot__in=('pendiente', 'en_proceso'),
                    created_at__gte=timezone.now() - timedelta(minutes=20),
                ).exclude(pk=self.cotizacion.pk).exists()
            if modelo:
                return modelo
            if not siguen or time.time() > limite:
                return None
            page.wait_for_timeout(4000)

    @staticmethod
    def _entero(texto):
        digitos = re.sub(r'\D', '', texto or '')
        return int(digitos) if digitos else None

    def _guardar_vehiculo(self, valores):
        """Guarda en Vehiculo lo que La Equidad resolvió por placa."""
        referencia = (valores.get('referencia') or '').strip()
        codigo, _, descripcion = referencia.partition(' - ')
        if not codigo.strip().isdigit():
            codigo, descripcion = '', referencia
        uso = normalizar_texto(valores.get('uso'))
        valor_asegurado = parse_money(valores.get('valorAsegurado'))
        accesorios = parse_money(valores.get('accesorio'))
        blindaje = parse_money(valores.get('blindaje'))
        self._valor_asegurado = valor_asegurado
        self._datos_extra = {'accesorios': accesorios, 'blindaje': blindaje}

        with schema_context(self.schema_name):
            v = self.vehiculo
            if valores.get('marca'):
                v.marca = valores['marca'].strip().upper()
            modelo = self._entero(valores.get('modelo'))
            if modelo:
                self._fijar_modelo(modelo)
            if descripcion.strip():
                v.referencia = descripcion.strip()
            if codigo.strip() and not v.codigo_fasecolda:
                v.codigo_fasecolda = codigo.strip()
            if uso in ('particular', 'publico'):
                v.servicio = uso
            if accesorios:
                v.valor_accesorios = accesorios
            if valor_asegurado and not v.valor_comercial:
                v.valor_comercial = valor_asegurado
            self._guardar_vehiculo_cambios()

    @staticmethod
    def _sin_signos(texto):
        """Minúsculas, sin tildes ni puntuación: «Bogotá, D.c.» y «BOGOTA D.C.» quedan iguales."""
        return re.sub(r'[^a-z0-9]+', ' ', normalizar_texto(texto)).strip()

    def _escribir_zona(self, page):
        """Zona de circulación: se escribe el municipio registrado y se elige la opción exacta
        (no la primera sugerencia: «Cali» también sugiere «San Calixto», «California»...).
        Los nombres con coma («Bogotá, D.c.») se buscan por lo anterior a la coma y sin tilde, y se
        comparan ignorando tildes y puntuación (el portal los muestra como «BOGOTA D.C.»)."""
        municipio = self.vehiculo.zona_circulacion
        campo = page.locator('input[formcontrolname="zona"]')
        campo.click()
        campo.press('Control+A')
        campo.press('Delete')
        termino = normalizar_texto(municipio.nombre.split(',')[0].strip()) or municipio.nombre
        campo.press_sequentially(termino, delay=70)
        page.wait_for_timeout(1800)
        opciones = page.locator('mat-option')
        textos = [t.strip() for t in opciones.all_inner_texts()]
        buscado = self._sin_signos(municipio.nombre)
        elegido = next((i for i, t in enumerate(textos) if self._sin_signos(t) == buscado), None)
        if elegido is None:
            elegido = next((i for i, t in enumerate(textos) if self._sin_signos(t).startswith(buscado)), None)
        if elegido is None:
            raise BotDatosError(
                f'La Equidad no ofreció el municipio «{municipio.nombre}» en «Zona de circulación» '
                f'(sugerencias: {", ".join(textos) or "ninguna"}).',
                accion='Revise la ciudad de circulación de la solicitud y reenvíe a La Equidad.',
            )
        opciones.nth(elegido).click()
        page.wait_for_timeout(700)

    def _descuento(self, page):
        page.wait_for_timeout(1200)  # termina la animación del asistente
        texto = (page.locator('input[formcontrolname="descuento"]').input_value() or '').strip()
        self._datos_extra['descuento'] = texto
        porcentaje = re.search(r'(\d+(?:[.,]\d+)?)\s*%', texto)
        if porcentaje:
            with schema_context(self.schema_name):
                self.cotizacion.porcentaje_descuento = porcentaje.group(1).replace(',', '.')
                self.cotizacion.save(update_fields=['porcentaje_descuento'])
        self._continuar(page).click(timeout=15000)

    def _capturar_planes(self, page):
        """Tres tarjetas de planes; el Plan Full es la prima_total."""
        planes = []
        for _ in range(90):
            planes = page.evaluate(LEE_PLANES_JS)
            if planes:
                break
            aviso = self._dialogo(page)
            if aviso:
                raise self._error_de_aviso(aviso, 'Cobertura (planes)')
            page.wait_for_timeout(1000)
        else:
            raise BotPortalError('La Equidad no mostró los planes de cobertura después de 90 segundos.')
        page.wait_for_timeout(1000)
        planes = page.evaluate(LEE_PLANES_JS)

        from core.policies.models import CotizacionPlan  # import local: evita ciclo al cargar el módulo

        principal = None
        with schema_context(self.schema_name):
            self.cotizacion.planes.all().delete()
            for plan in planes:
                nombre = re.sub(r'^AUTO P\.\s*', '', plan['nombre'], flags=re.I).strip().title().replace('Rce', 'RCE')
                prima = parse_money(plan.get('anual'))
                CotizacionPlan.objects.create(cotizacion=self.cotizacion, nombre_plan=nombre, prima_total=prima)
                if PLAN_PRINCIPAL in nombre.lower():
                    principal = prima
            if principal is None:
                raise BotPortalError('La Equidad cotizó, pero ninguno de los planes es «Plan Full», así que no hay prima principal que guardar.')
            self.cotizacion.prima_total = principal
            if getattr(self, '_valor_asegurado', None):
                self.cotizacion.valor_asegurado = self._valor_asegurado
            self.cotizacion.moneda = 'Pesos'
            self.cotizacion.mensaje_bot = self._nota()
            self.cotizacion.save()

    def _nota(self):
        """Datos que La Equidad mostró y que no tienen campo propio en la cotización."""
        extra = self._datos_extra
        partes = []
        if extra.get('descuento'):
            partes.append(f'Descuento aplicado: {extra["descuento"]}')
        for etiqueta, clave in (('Valor accesorios', 'accesorios'), ('Valor blindaje', 'blindaje')):
            if clave in extra:
                partes.append(f'{etiqueta}: ${int(extra[clave]):,}'.replace(',', '.'))
        return ' · '.join(partes) or None
