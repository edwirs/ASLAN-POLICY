"""Bot de cotización para Seguros Mundial (portal «Expedidores», línea Movilidad › Rodando contigo).

Flujo (mapeado con una sesión real exploratoria, no a ciegas):
  1. Inicio de sesión en dos pantallas: usuario + CONTINUAR, contraseña + INGRESAR.
  2. Línea de negocio «Movilidad» › producto «Rodando contigo» › acción «Nueva cotización».
  3. Nueva cotización: tipo y número de documento, placa, modelo y zona de circulación («Municipio - Departamento»).
     Placa REAL siempre (Mundial no acepta la placa de 0 km TL123A: exige formato de carro).
     Si el vehículo es 0 km el portal abre un modal «¿Tu vehículo es 0 Km?»: se pasa a SI, se escribe el valor
     comercial, y luego un segundo modal pide el código Fasecolda.
  4. Información del vehículo: se captura (modelo, marca, clase, tipo, color, motor, chasis, serie, valor comercial,
     código Fasecolda y combustible) y se confirma con SI.
  5. Información del propietario: género, fecha de nacimiento (calendario), ciudad de residencia, y datos fijos de
     contacto; se marcan las dos autorizaciones y los canales E-mail y WhatsApp.
  6. Coberturas básicas y adicionales: se deja todo como viene y se continúa.
  7. Resumen: se captura hasta cuándo vale la cotización y el valor de «Pago de contado» (= TOTAL A PAGAR).

Cuidados propios de este portal:
  - La validación de documento + placa + modelo + zona solo permite 3 intentos («Quedan N intentos de validación»):
    ante un rechazo NO se reintenta nada dentro del bot; se explica al asesor.
  - Si el portal responde «amplio volumen de consultas, intenta más tarde» es una alerta naranja (BotSaturadoError)
    que se puede reenviar después.

Sesiones: al terminar (bien o mal) SIEMPRE se cierra sesión (el portal pide confirmar el cierre).
"""
import logging
import os
import re
import time
from datetime import date, datetime, timedelta
from decimal import Decimal

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
    BotPortalError,
    BotSaturadoError,
    BotTimeout,
    RegistroErrorMixin,
    exigir_clave_al_dia,
    normalizar_texto,
    parse_money,
)

logger = logging.getLogger(__name__)

LINEA = 'Movilidad'
PRODUCTO = 'Rodando contigo'
ACCION = 'Nueva cotización'

# Abreviatura del tipo de documento del sistema -> opción del selector del portal.
DOCUMENTOS = {
    'CC': 'Cédula de ciudadanía',
    'CE': 'Cédula de extranjería',
    'NIT': 'NIT',
    'PA': 'Pasaporte',
    'PP': 'Pasaporte',
}

# Datos fijos que el negocio pide para TODAS las cotizaciones (la credencial puede traer los suyos).
DIRECCION_RESIDENCIA = 'cll 6 20 33'
CELULAR_POR_DEFECTO = '3227354638'
CORREO_POR_DEFECTO = 'lilianmq@galiseguros.com'

MESES = ['ene', 'feb', 'mar', 'abr', 'may', 'jun', 'jul', 'ago', 'sep', 'oct', 'nov', 'dic']

ETIQUETAS_VEHICULO = ('Modelo', 'Marca', 'Clase', 'Tipo', 'Color', 'Motor', 'Chasis', 'Serie', 'Valor comercial',
                      'Zona de circulación', 'Código fasecolda', 'Tipo de combustible')

MODALES_JS = """() => [...new Set([...document.querySelectorAll('.ant-modal, [role=dialog]')]
    .filter(e => e.getBoundingClientRect().width > 0 && (e.innerText || '').trim())
    .map(e => (e.innerText || '').trim().replace(/\\s+/g, ' ').slice(0, 400)))]"""


def _limpio(texto):
    return re.sub(r'\s+', ' ', texto or '').strip()


def _digitos(texto):
    return re.sub(r'\D', '', texto or '')


class MundialBot(RegistroErrorMixin):
    """Cotiza todo riesgo en Seguros Mundial. Uso: MundialBot(cotizacion, headless=True).run()"""

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
        self._credenciales_enviadas = False

    def _get_credencial(self):
        credencial = self.cotizacion.aseguradora.credenciales.filter(is_active=True).order_by('-id').first()
        if credencial is None:
            raise BotAutenticacionError(
                f'No hay una credencial activa configurada para "{self.cotizacion.aseguradora}".',
                accion='Cree o active la credencial de Seguros Mundial en Configuraciones › Aseguradoras y reenvíe la solicitud.',
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
            base = os.path.join(debug_dir, f'mundial_{self.cotizacion.pk}_{stamp}')
            page.screenshot(path=f'{base}.png', full_page=True)
            logger.warning('Diagnóstico del bot Seguros Mundial guardado en %s.png', base)
        except Exception:
            logger.exception('No se pudo capturar el diagnóstico de Seguros Mundial tras la falla')

    @staticmethod
    def _modales(page):
        try:
            return page.evaluate(MODALES_JS)
        except Exception:
            return []

    @staticmethod
    def _hash(page):
        try:
            return page.evaluate('location.hash') or ''
        except Exception:
            return ''

    def _error_de_aviso(self, texto, paso):
        """Convierte un aviso del portal en el error que explica qué pasó."""
        normal = normalizar_texto(texto)
        if 'amplio volumen' in normal or 'intenta mas tarde' in normal:
            return BotSaturadoError(
                'Seguros Mundial tiene demasiadas consultas en este momento: «Lo sentimos… estamos teniendo un amplio '
                'volumen de consultas, por favor intenta más tarde».',
            )
        if 'ya tiene una cotizacion en curso' in normal:
            return BotPortalError(
                'Seguros Mundial ya tiene una cotización en curso para esta placa y no deja crear otra: «Dentro de 24 '
                'horas podrás volver a intentarlo».',
                accion='Espere 24 horas y reenvíe a Seguros Mundial, o consulte la cotización ya hecha entrando al portal '
                       'de Seguros Mundial › Cotizaciones y buscándola por la placa.',
            )
        if 'validacion fallida' in normal:
            quedan = re.search(r'quedan\s+(\d+)\s+intentos?', normal)
            restantes = f' Quedan {quedan.group(1)} intentos de validación.' if quedan else ''
            return BotDatosError(
                'Seguros Mundial no pudo validar los datos (tipo y número de documento, placa, modelo y zona de '
                f'circulación).{restantes}',
                accion='Mundial solo permite 3 intentos de validación: NO reenvíe sin revisar antes en la solicitud el '
                       'número de documento, la placa, el modelo y la ciudad de circulación (el modelo debe ser el real '
                       'del vehículo, y para un 0 km el del año siguiente). Corrija el dato y reenvíe a Seguros Mundial.',
            )
        return BotPortalError(f'Seguros Mundial mostró un aviso en el paso «{paso}»: «{texto}».')

    def _revisar_avisos(self, page, paso, ignorar=()):
        """Si el portal muestra un aviso (modal) que no es del flujo, lo explica. `ignorar`: fragmentos
        (sin tildes) de modales esperados que no son errores."""
        for texto in self._modales(page):
            normal = normalizar_texto(texto)
            if any(f in normal for f in ignorar):
                continue
            raise self._error_de_aviso(texto, paso)
        try:
            cuerpo = normalizar_texto(page.evaluate('document.body.innerText') or '')
        except Exception:
            return
        if 'amplio volumen de consultas' in cuerpo:
            raise self._error_de_aviso('amplio volumen de consultas', paso)

    def _esperar_hash(self, page, fragmento, paso, timeout=60, ignorar=()):
        """Espera a que la URL del portal (SPA) contenga `fragmento`; si antes sale un aviso, lo explica."""
        for _ in range(timeout * 2):
            if fragmento in self._hash(page):
                return
            self._revisar_avisos(page, paso, ignorar)
            page.wait_for_timeout(500)
        raise BotPortalError(f'Seguros Mundial no mostró la pantalla esperada en el paso «{paso}» después de {timeout} segundos.')

    @staticmethod
    def _escribir(campo, valor, comparar='texto', intentos=3):
        """Teclea `valor` de verdad y confirma que el campo lo tiene (los campos con máscara, como el documento o los
        valores en pesos, se comparan solo por sus dígitos). Sin incluir el valor en el error."""
        for _ in range(intentos):
            campo.click()
            campo.press('Meta+a')
            campo.press('Control+a')
            campo.press('Backspace')
            if campo.input_value():
                campo.fill('')
            campo.press_sequentially(valor, delay=45)
            campo.page.wait_for_timeout(250)
            actual = campo.input_value(timeout=2000)
            if (_digitos(actual) == _digitos(valor)) if comparar == 'digitos' else (actual == valor):
                return
        raise BotPortalError('No se pudo escribir el valor esperado en un campo del portal tras varios intentos.')

    def _elegir_en_select(self, page, indice, opcion, buscar=None):
        """Selector de Ant Design (nz-select) número `indice`: lo abre, opcionalmente busca y elige la opción cuyo
        texto coincide (sin tildes) con `opcion` (función o texto)."""
        page.locator('nz-select').nth(indice).click()
        page.wait_for_timeout(500)
        if buscar:
            page.keyboard.type(buscar, delay=110)
            page.wait_for_timeout(2200)
        opciones = page.locator('.ant-select-item-option')
        for _ in range(10):
            if opciones.count():
                break
            page.wait_for_timeout(500)
        textos = [t.strip() for t in opciones.all_inner_texts()]
        coincide = opcion if callable(opcion) else (lambda t: normalizar_texto(t) == normalizar_texto(opcion))
        for i, t in enumerate(textos):
            if coincide(t):
                opciones.nth(i).click()
                page.wait_for_timeout(500)
                return t
        raise BotDatosError(
            f'Seguros Mundial no ofrece la opción esperada en este campo (opciones: {", ".join(textos[:8]) or "ninguna"}).',
            accion='Revise el dato en la solicitud y reenvíe a Seguros Mundial.',
        )

    def _opcion_zona(self):
        """Función que reconoce, entre las opciones «Municipio - Departamento», la de la zona de circulación."""
        municipio = normalizar_texto(self.vehiculo.zona_circulacion.nombre)
        departamento = normalizar_texto(self.vehiculo.zona_circulacion.departamento.nombre)

        def coincide(texto):
            normal = normalizar_texto(texto)
            nombre, _, depto = normal.partition(' - ')
            return nombre.strip() == municipio and (not depto or departamento in depto or depto in departamento)
        return coincide

    def _dato_de_otras_fuentes(self, page, campo, timeout=180):
        """Valor de `campo` del vehículo según la BD. Si aún no está, espera a que otra aseguradora que cotiza el
        mismo vehículo lo capture; deja de esperar cuando ninguna sigue en curso."""
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
            self._validar_antes_de_abrir_portal()
            with sync_playwright() as playwright:
                browser = playwright.chromium.launch(headless=self.headless)
                contexto = browser.new_context(viewport={'width': 1366, 'height': 900})
                page = contexto.new_page()
                try:
                    self._paso(PASO_LOGIN)
                    self._login(page)
                    self._paso('Línea de negocio y producto')
                    self._elegir_producto(page)
                    self._paso('Nueva cotización (documento, placa, modelo y zona)')
                    self._nueva_cotizacion(page)
                    self._paso('Información del vehículo')
                    self._informacion_vehiculo(page)
                    self._paso('Información del propietario')
                    self._informacion_propietario(page)
                    self._paso('Coberturas básicas y adicionales')
                    self._coberturas(page)
                    self._paso('Resumen de la cotización')
                    nota = self._capturar_resumen(page)
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
            self._set_estado('cancelado', mensaje='El asesor canceló tras una alerta de confirmación.')
        except BotTimeout:
            self._set_estado('error', mensaje='Se agotó el tiempo esperando la confirmación del asesor.')
        except Exception as e:
            logger.exception('Error cotizando %s en Seguros Mundial', self.vehiculo.placa)
            self._registrar_error(e)

    # ------------------------------------------------------------------
    # Pasos
    # ------------------------------------------------------------------

    def _validar_antes_de_abrir_portal(self):
        """Reglas conocidas que no requieren abrir el portal (ahorra una sesión y un intento de validación)."""
        self._paso('Validación de datos de la solicitud')
        abreviatura = (self.tomador.document_type.abbreviation or '').upper()
        if abreviatura not in DOCUMENTOS:
            raise BotDatosError(
                f'Seguros Mundial solo acepta cédula de ciudadanía, cédula de extranjería, NIT y pasaporte; el tomador '
                f'tiene «{self.tomador.document_type.name}».',
                accion='Cotice este caso directamente en el portal de Seguros Mundial.',
            )
        if self.vehiculo.es_cero_km and not (self.vehiculo.valor_comercial and self.vehiculo.codigo_fasecolda):
            raise BotDatosError(
                'Para cotizar un 0 km en Seguros Mundial hacen falta el valor comercial y el código Fasecolda del '
                'vehículo, y la solicitud no los tiene.',
                accion='Registre la solicitud con el código Fasecolda y el valor comercial del 0 km y reenvíe.',
            )

    def _login(self, page):
        page.goto(self.credencial.portal_url, wait_until='domcontentloaded')
        usuario = page.locator('#usuario')
        usuario.wait_for(timeout=40000)
        self._escribir(usuario, self.credencial.username)
        page.get_by_role('button', name=re.compile(r'^\s*CONTINUAR\s*$', re.I)).click()
        clave = page.locator('#password')
        clave.wait_for(timeout=30000)
        self._escribir(clave, self.credencial.password)
        page.get_by_role('button', name=re.compile(r'^\s*INGRESAR\s*$', re.I)).click()
        self._credenciales_enviadas = True
        for _ in range(60):
            if '/login' not in self._hash(page) and page.get_by_text('Cerrar sesión').count():
                return
            for aviso in self._modales(page):
                raise BotAutenticacionError(
                    f'Seguros Mundial no permitió el ingreso: «{aviso}».',
                    accion='Verifique el usuario y la contraseña de Seguros Mundial en Configuraciones › Aseguradoras y que '
                           'la cuenta no esté bloqueada; luego reenvíe la solicitud.',
                )
            mensaje = page.evaluate("""() => [...document.querySelectorAll('.error, .invalid-feedback, .text-danger, [class*=error]')]
                .filter(e => e.getBoundingClientRect().width > 0 && (e.innerText || '').trim()).map(e => e.innerText.trim())[0] || null""")
            if mensaje:
                raise BotAutenticacionError(
                    f'Seguros Mundial no permitió el ingreso: «{_limpio(mensaje)}».',
                    accion='Verifique el usuario y la contraseña de Seguros Mundial en Configuraciones › Aseguradoras y que '
                           'la cuenta no esté bloqueada; luego reenvíe la solicitud.',
                )
            page.wait_for_timeout(1000)
        raise BotAutenticacionError(
            'No se pudo iniciar sesión en Seguros Mundial: después de ingresar no apareció la selección de línea de '
            'negocio (¿contraseña vencida o cuenta bloqueada?).')

    def _elegir_producto(self, page):
        for texto in (LINEA, PRODUCTO, ACCION):
            elemento = page.get_by_text(texto, exact=True).first
            elemento.wait_for(timeout=45000)  # las tarjetas cargan después de un esqueleto de carga
            elemento.click()
            page.wait_for_timeout(1200)
        self._esperar_hash(page, 'nueva-cotizacion', 'Línea de negocio y producto', timeout=40)

    def _nueva_cotizacion(self, page):
        page.locator('#numDocumento').wait_for(timeout=40000)
        abreviatura = (self.tomador.document_type.abbreviation or '').upper()
        self._elegir_en_select(page, 0, DOCUMENTOS[abreviatura])
        self._escribir(page.locator('#numDocumento'), self.tomador.dni, comparar='digitos')
        self._escribir(page.locator('#placa'), self.vehiculo.placa)  # siempre la real (ver nota del módulo)
        modelo = self._modelo_vigente() or self._dato_de_otras_fuentes(page, 'modelo')
        if not modelo:
            raise BotDatosError(
                'Seguros Mundial pide el modelo del vehículo para validarlo y no se tiene (ninguna otra aseguradora lo '
                'capturó a tiempo).',
                accion='Reenvíe a Seguros Mundial cuando otra aseguradora haya leído el vehículo, o complete el modelo '
                       'en la solicitud.',
            )
        self._escribir(page.locator('#modelo'), str(modelo), comparar='digitos')
        municipio = self.vehiculo.zona_circulacion.nombre
        self._elegir_en_select(page, 1, self._opcion_zona(), buscar=municipio[:6])

        page.get_by_role('button', name=re.compile(r'COMENZAR COTIZACI', re.I)).click()
        cero_km_hecho = False
        for _ in range(240):  # hasta ~2 min: el portal valida contra el RUNT y puede tardar
            if 'informacion-vehiculo' in self._hash(page):
                return
            modales = [normalizar_texto(m) for m in self._modales(page)]
            if any('tu vehiculo es 0 km' in m for m in modales):
                if not self.vehiculo.es_cero_km:
                    raise BotDatosError(
                        'Seguros Mundial preguntó si el vehículo es 0 km, pero la solicitud no está marcada como 0 km '
                        '(el modelo suele ser del año siguiente cuando es nuevo).',
                        accion='Si el vehículo es 0 km, regístrelo así en la solicitud; si no, revise el modelo y reenvíe.',
                    )
                if not cero_km_hecho:
                    self._cero_km(page)
                    cero_km_hecho = True
            else:
                self._revisar_avisos(page, 'Nueva cotización', ignorar=('codigo fasecolda', 'valor factura'))
            page.wait_for_timeout(500)
        raise BotPortalError('Seguros Mundial no mostró la información del vehículo después de 2 minutos.')

    def _cero_km(self, page):
        """Modal «¿Tu vehículo es 0 Km?»: pasa a SI, valor comercial y, en el segundo modal, código Fasecolda."""
        page.locator('label[for="cerokm"]').click()
        valor = page.locator('#valorComercial')
        valor.wait_for(timeout=15000)
        self._escribir(valor, str(int(self.vehiculo.valor_comercial)), comparar='digitos')
        page.locator('.ant-modal-wrap').get_by_role('button', name=re.compile(r'^\s*SIGUIENTE\s*$', re.I)).click()
        codigo = page.locator('#codigo')
        for _ in range(80):
            if codigo.count() and codigo.first.is_visible():
                break
            self._revisar_avisos(page, 'Datos del 0 km', ignorar=('tu vehiculo es 0 km', 'valor factura', 'cargando'))
            page.wait_for_timeout(500)
        else:
            raise BotPortalError('Seguros Mundial no pidió el código Fasecolda después de indicar el valor comercial.')
        self._escribir(codigo, self.vehiculo.codigo_fasecolda, comparar='digitos')
        page.locator('.ant-modal-wrap').get_by_role('button', name=re.compile(r'^\s*SIGUIENTE\s*$', re.I)).click()

    def _leer_vehiculo(self, page):
        """{etiqueta: valor} de la sección «Información del vehículo» (el texto viene en líneas etiqueta/valor)."""
        lineas = [l.strip() for l in (page.evaluate('document.body.innerText') or '').split('\n') if l.strip()]
        inicio = next((i for i, l in enumerate(lineas) if re.fullmatch(r'Información del vehículo', l, re.I)
                       and i + 1 < len(lineas) and lineas[i + 1] in ETIQUETAS_VEHICULO), None)
        datos = {}
        if inicio is None:
            return datos
        i = inicio + 1
        while i < len(lineas) - 1:
            if lineas[i] in ETIQUETAS_VEHICULO and lineas[i + 1] not in ETIQUETAS_VEHICULO:
                datos[lineas[i]] = lineas[i + 1]
                i += 2
            else:
                i += 1
        return datos

    def _informacion_vehiculo(self, page):
        page.get_by_role('button', name='SI', exact=True).wait_for(timeout=30000)
        datos = self._leer_vehiculo(page)
        if not datos:
            raise BotPortalError('Seguros Mundial no mostró los datos del vehículo para confirmarlos.')
        self._guardar_vehiculo(datos)
        page.get_by_role('button', name='SI', exact=True).click()
        self._esperar_hash(page, 'informacion-asegurado', 'Información del vehículo', timeout=40)

    @staticmethod
    def _valido(texto):
        return bool(texto) and normalizar_texto(texto) not in ('n/a', 'na', 'ninguno', 'no aplica', '-')

    def _guardar_vehiculo(self, datos):
        """Guarda en Vehiculo lo que Mundial muestra. Lo que ya tenía el sistema solo se reemplaza si el portal trae un
        dato válido (nunca con vacíos ni «N/A»); la zona de circulación se queda como la registró el asesor."""
        v = self.vehiculo
        asignaciones = {
            'Marca': ('marca', lambda t: t.strip().upper()),
            'Clase': ('clase', lambda t: t.strip()),
            'Tipo': ('tipo_vehiculo', lambda t: t.strip()),
            'Color': ('color', lambda t: t.strip()),
            'Motor': ('motor', lambda t: t.strip()),
            'Chasis': ('chasis', lambda t: t.strip()),
            'Serie': ('serie', lambda t: t.strip()),
            'Código fasecolda': ('codigo_fasecolda', lambda t: _digitos(t).zfill(8) if len(_digitos(t)) <= 8 else _digitos(t)),
            'Tipo de combustible': ('combustible', lambda t: t.strip()),
        }
        with schema_context(self.schema_name):
            for etiqueta, (campo, convertir) in asignaciones.items():
                valor = datos.get(etiqueta)
                if self._valido(valor):
                    setattr(v, campo, convertir(valor))
            # Mundial valida el modelo contra el RUNT con la placa: es la fuente que más pesa (ver `_fijar_modelo`).
            self._fijar_modelo(datos.get('Modelo'))
            precio = parse_money(datos.get('Valor comercial'))
            if precio and precio > 0:
                v.valor_comercial = precio
            self._guardar_vehiculo_cambios()
            if precio and precio > 0:
                self.cotizacion.valor_asegurado = precio
                self.cotizacion.save(update_fields=['valor_asegurado'])

    def _elegir_fecha(self, page, fecha):
        """Calendario de Ant Design: año (por décadas) › mes › día. El campo no admite teclear."""
        campo = page.locator('input[placeholder="Seleccionar fecha"]')
        campo.click()
        panel = page.locator('.ant-picker-dropdown:not(.ant-picker-dropdown-hidden)').last
        panel.locator('.ant-picker-header-year-btn').click(timeout=10000)
        page.wait_for_timeout(500)
        for _ in range(20):
            cabecera = panel.locator('.ant-picker-header-decade-btn, .ant-picker-header-view button').first.inner_text()
            anios = [int(x) for x in re.findall(r'\d{4}', cabecera)]
            if len(anios) >= 2 and anios[0] <= fecha.year <= anios[1]:
                break
            panel.locator('.ant-picker-header-super-prev-btn' if anios and fecha.year < anios[0]
                          else '.ant-picker-header-super-next-btn').click()
            page.wait_for_timeout(300)
        panel.locator('.ant-picker-cell-in-view .ant-picker-cell-inner', has_text=str(fecha.year)).first.click(timeout=8000)
        page.wait_for_timeout(500)
        panel.locator('.ant-picker-header-month-btn').click(timeout=8000)
        page.wait_for_timeout(500)
        panel.locator('.ant-picker-cell .ant-picker-cell-inner',
                      has_text=re.compile(rf'^\s*{MESES[fecha.month - 1]}', re.I)).first.click(timeout=8000)
        page.wait_for_timeout(500)
        panel.locator('.ant-picker-cell-in-view .ant-picker-cell-inner',
                      has_text=re.compile(rf'^\s*{fecha.day}\s*$')).first.click(timeout=8000)
        page.wait_for_timeout(700)
        if campo.input_value() != fecha.isoformat():
            raise BotPortalError('Seguros Mundial no dejó registrada la fecha de nacimiento del tomador en el calendario.')

    def _informacion_propietario(self, page):
        page.locator('#direccionPropietario').wait_for(timeout=40000)
        etiqueta_genero = 'Hombre' if (self.tomador.gender or 'male') == 'male' else 'Mujer'
        page.locator('.alz-cont-radios', has_text=etiqueta_genero).locator('label.alz-radio').first.click()
        self._elegir_fecha(page, self.tomador.birthdate)
        municipio = self.vehiculo.zona_circulacion.nombre
        self._elegir_en_select(page, 1, self._opcion_zona(), buscar=municipio[:6])
        self._escribir(page.locator('#direccionPropietario'), DIRECCION_RESIDENCIA)
        self._escribir(page.locator('#celularPropietario'), self.credencial.telefono_contacto or CELULAR_POR_DEFECTO,
                       comparar='digitos')
        self._escribir(page.locator('#correoPropietario'), self.credencial.correo_contacto or CORREO_POR_DEFECTO)

        # Autorizaciones: se marca el círculo de la izquierda (no el texto: tiene enlaces que abren documentos).
        for etiqueta in ('condiciones', 'comunicaciones'):
            page.locator(f'label[for="{etiqueta}"]').scroll_into_view_if_needed()
            page.locator(f'label[for="{etiqueta}"]').click(position={'x': 12, 'y': 12})
            page.wait_for_timeout(600)
        # Al aceptarlas se habilitan los canales de contacto: E-mail y WhatsApp.
        page.get_by_text('E-mail', exact=True).wait_for(timeout=15000)
        for canal in ('E-mail', 'WhatsApp'):
            page.get_by_text(canal, exact=True).click()
            page.wait_for_timeout(500)
        marcados = page.evaluate("""() => ({
            datos: document.querySelector('input[formcontrolname=tratamiento_datos]').checked,
            comunicaciones: document.querySelector('input[formcontrolname=comunicaciones]').checked,
            canales: [...document.querySelectorAll('input[formcontrolname=activo]')].filter(i => i.checked).length})""")
        if not (marcados['datos'] and marcados['comunicaciones'] and marcados['canales'] >= 2):
            raise BotPortalError('Seguros Mundial no dejó marcadas las autorizaciones y los canales de contacto.')

        page.get_by_role('button', name=re.compile(r'^\s*CONTINUAR\s*$', re.I)).click()
        try:
            self._esperar_hash(page, 'coberturas-basicas', 'Información del propietario', timeout=45)
        except BotPortalError:
            raise BotDatosError(
                'Seguros Mundial no dejó continuar en la información del propietario: algún campo quedó sin diligenciar '
                'o inválido.',
                accion='Revise en la solicitud la fecha de nacimiento, el género y la ciudad del tomador y reenvíe a '
                       'Seguros Mundial.',
            )

    def _coberturas(self, page):
        """Coberturas básicas y adicionales: se dejan tal cual vienen."""
        for actual, siguiente in (('coberturas-basicas', 'coberturas-opcionales'), ('coberturas-opcionales', 'resumen-cotizacion')):
            boton = page.get_by_role('button', name=re.compile(r'^\s*CONTINUAR\s*$', re.I))
            boton.wait_for(timeout=30000)
            page.wait_for_timeout(1500)
            boton.click()
            self._esperar_hash(page, siguiente, 'Coberturas básicas y adicionales', timeout=45)

    def _capturar_resumen(self, page):
        """Hasta cuándo vale la cotización y el valor de «Pago de contado» (igual a «TOTAL A PAGAR»)."""
        page.get_by_text('Resumen de pago').first.wait_for(timeout=45000)
        page.wait_for_timeout(1500)
        texto = page.evaluate('document.body.innerText') or ''

        vigente = None
        m = re.search(r'vigente hasta el d[ií]a:\s*(\d{2})-(\d{2})-(\d{4})', texto, re.I)
        if m:
            vigente = date(int(m.group(3)), int(m.group(2)), int(m.group(1)))
        contado = re.search(r'Pago de contado\s*\n\s*(\$[\d.,]+)', texto, re.I)
        mensual = re.search(r'Pago mensual\*?\s*\n\s*(\$[\d.,]+)', texto, re.I)
        neta = re.search(r'Prima neta\s*[\t ]+(\$[\d.,]+)', texto, re.I)
        total = re.search(r'TOTAL A PAGAR\s*[\t ]+(\$[\d.,]+)', texto, re.I)
        valor_contado = parse_money((contado or total).group(1)) if (contado or total) else Decimal('0')
        if valor_contado <= 0:
            raise BotPortalError('Seguros Mundial no mostró el valor de «Pago de contado» en el resumen de la cotización.')

        from core.policies.models import CotizacionPlan  # import local: evita ciclo al cargar el módulo
        with schema_context(self.schema_name):
            self.cotizacion.planes.all().delete()
            CotizacionPlan.objects.create(cotizacion=self.cotizacion, nombre_plan='Pago de contado', prima_total=valor_contado)
            if mensual:
                CotizacionPlan.objects.create(cotizacion=self.cotizacion, nombre_plan='Pago mensual (12 cuotas)',
                                              prima_total=parse_money(mensual.group(1)))
            self.cotizacion.prima_total = valor_contado
            if neta:
                self.cotizacion.valor_sin_iva = parse_money(neta.group(1))
            self.cotizacion.cotizacion_vigente_hasta = vigente
            self.cotizacion.save(update_fields=['prima_total', 'valor_sin_iva', 'cotizacion_vigente_hasta'])
        if vigente:
            return f'Cotización vigente hasta el {vigente:%d/%m/%Y}.'
        return None

    # ------------------------------------------------------------------
    # Cierre de sesión
    # ------------------------------------------------------------------

    def _cerrar_sesion(self, page):
        """Cierra sesión SIEMPRE y verifica que el portal ya no la reconoce, sin lanzar excepción:
        «Cerrar sesión» › confirmar en el modal. Se reintenta una vez."""
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
                    page.wait_for_timeout(4000)
                except Exception:
                    return
        logger.warning('Seguros Mundial: NO se pudo confirmar que la sesión quedó cerrada (revisar la cuenta).')

    @staticmethod
    def _salir_sin_guardar(page):
        """Si hay una cotización abierta, sale de ella SIN guardar. Importante: si se cierra sesión con la cotización
        abierta, Mundial deja la placa «en curso» y no permite cotizarla de nuevo durante 24 horas."""
        try:
            salir = page.get_by_text('Salir de la cotización actual', exact=False).first
            if salir.count() and salir.is_visible():
                salir.click(timeout=6000)
                page.get_by_role('button', name=re.compile(r'^\s*SALIR SIN GUARDAR\s*$', re.I)).click(timeout=8000)
                page.wait_for_timeout(3000)
        except Exception:
            logger.warning('Seguros Mundial: no se pudo salir de la cotización abierta sin guardar.')

    def _cerrar_una_vez(self, page):
        """Un intento de cierre. True si queda verificado (o no había sesión que cerrar)."""
        if page.locator('#usuario').count() and page.locator('#usuario').first.is_visible():
            return True  # ya está en la pantalla de ingreso
        self._salir_sin_guardar(page)
        enlace = page.get_by_text('Cerrar sesión', exact=False).first
        if enlace.count():
            enlace.click(timeout=8000)
            page.get_by_role('button', name=re.compile(r'^\s*CERRAR SESI', re.I)).click(timeout=8000)
            page.wait_for_timeout(3000)
        elif not self._credenciales_enviadas:
            return True  # nunca llegó a ingresar
        page.goto('https://expedidores.mundialseguros.com.co/#/movilidad/livianos/dashboard', wait_until='domcontentloaded')
        page.wait_for_timeout(3500)
        return page.locator('#usuario').count() > 0 and not page.get_by_text('Cerrar sesión').count()
