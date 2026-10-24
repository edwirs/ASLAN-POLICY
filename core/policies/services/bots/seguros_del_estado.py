"""Bot de cotización para el portal web de Seguros del Estado.

IMPORTANTE — estado de este archivo: se escribió a partir de la descripción
paso a paso dada por el usuario, sin haber inspeccionado el HTML real del
portal (Claude no puede iniciar sesión con credenciales reales por política).
Los selectores usan texto visible (más resistentes a cambios de maquetado que
IDs/clases, pero no infalibles). Es muy probable que la primera corrida real
falle en algún paso puntual — correr con headless=False para ver dónde y
ajustar ese paso específico en lugar de reescribir el bot completo.
"""
import logging
import os
import re
import time
from datetime import datetime

from django.conf import settings
from django.db import connection
from django.utils import timezone
from django_tenants.utils import schema_context
from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeoutError

from core.policies.choices import SERVICIO_VEHICULO
from core.policies.services.bots.base import (
    PASO_LOGIN,
    BotAutenticacionError,
    BotCancelado,
    BotDatosError,
    BotNoCotizableError,
    BotPortalError,
    BotTimeout,
    RegistroErrorMixin,
    _accent_insensitive_pattern,
    click_by_text,
    click_select,
    exigir_clave_al_dia,
    normalizar_texto,
    parse_money,
    wait_visible,
)

logger = logging.getLogger(__name__)

CONFIRMACION_POLL_SECONDS = 5
CONFIRMACION_TIMEOUT_SECONDS = 15 * 60  # 15 minutos esperando al asesor

SERVICIO_LABEL_TO_CODE = {label.lower(): code for code, label in SERVICIO_VEHICULO}


class SegurosDelEstadoBot(RegistroErrorMixin):
    """Automatiza una cotización de todo riesgo en el portal de Seguros del Estado.

    Uso:
        bot = SegurosDelEstadoBot(cotizacion, headless=True)
        bot.run()
    """

    def __init__(self, cotizacion, headless=True):
        self.cotizacion = cotizacion
        self.vehiculo = cotizacion.vehiculo
        self._foto_vehiculo()
        self.tomador = self.vehiculo.tomador
        self.headless = headless
        self.credencial = self._get_credencial()
        # Dentro de sync_playwright Django usa otra conexión (schema public): el
        # bloque de Playwright re-entra a este schema para poder escribir en la BD.
        self.schema_name = connection.schema_name

    def _get_credencial(self):
        credencial = self.cotizacion.aseguradora.credenciales.filter(is_active=True).order_by('-id').first()
        if credencial is None:
            raise BotAutenticacionError(
                f'No hay una credencial activa configurada para "{self.cotizacion.aseguradora}".',
                accion='Cree o active la credencial de Seguros del Estado en Credenciales de Aseguradora y reenvíe la solicitud.',
            )
        exigir_clave_al_dia(credencial, self.cotizacion.aseguradora)
        return credencial

    def _set_estado(self, estado_bot, mensaje=None):
        self.cotizacion.estado_bot = estado_bot
        if mensaje is not None:
            self.cotizacion.mensaje_bot = mensaje
        self.cotizacion.save(update_fields=['estado_bot', 'mensaje_bot'])

    def _capturar_diagnostico(self, page):
        """Guarda un screenshot y los textos de botones/enlaces visibles al
        momento de una falla, para poder ajustar el selector que no calzó sin
        necesidad de iniciar sesión de nuevo. Nunca vuelca el HTML completo ni
        valores de inputs (evita exponer la contraseña ya tecleada en el DOM)."""
        try:
            debug_dir = os.path.join(settings.MEDIA_ROOT, 'bot_debug')
            os.makedirs(debug_dir, exist_ok=True)
            stamp = timezone.now().strftime('%Y%m%d_%H%M%S')
            base = os.path.join(debug_dir, f'cotizacion_{self.cotizacion.pk}_{stamp}')

            page.screenshot(path=f'{base}.png', full_page=True)

            textos = page.eval_on_selector_all(
                'button, a, [role="button"], input[type="submit"], input[type="button"], label',
                'els => els.map(e => (e.innerText || e.value || "").trim()).filter(Boolean)'
            )
            with open(f'{base}.txt', 'w', encoding='utf-8') as f:
                f.write(f'URL: {page.url}\n\n')
                f.write('Textos visibles (botones/enlaces/labels):\n')
                for texto in textos:
                    f.write(f'- {texto}\n')

            logger.warning('Diagnóstico del bot guardado en %s.png / %s.txt', base, base)
        except Exception:
            logger.exception('No se pudo capturar el diagnóstico de la página tras la falla')

    def _cerrar_sesion(self, page):
        """Cierra la sesión SIEMPRE y verifica que el portal volvió al ingreso, sin lanzar
        excepción. El portal no tiene botón «Cerrar sesión» con texto: es un ícono de apagado
        en la barra superior, sin texto ni etiqueta (junto a las notificaciones y el avatar),
        y cierra directo. Dejar sesiones abiertas acumula sesiones en la cuenta."""
        try:
            if page.is_closed():
                return
            if self._en_pantalla_de_ingreso(page):
                return
            # Un aviso del portal abierto (con botón ACEPTAR) tapa la barra superior y el ícono de
            # apagado no recibe el clic: primero se aceptan los avisos que haya.
            for _ in range(3):
                try:
                    aceptar = page.get_by_role('button', name=re.compile(r'^Aceptar$', re.I)).and_(page.locator(':visible'))
                    if not aceptar.count():
                        break
                    aceptar.first.click(timeout=3000)
                    page.wait_for_timeout(800)
                except Exception:
                    break
            try:
                page.keyboard.press('Escape')  # cierra menús abiertos
            except Exception:
                pass
            candidatos = (
                # Ícono de apagado: botón con svg, sin texto y sin aria-label (las notificaciones
                # llevan contador y el avatar tiene aria-label «open drawer»).
                page.locator('header button:not([aria-label])').filter(has=page.locator('svg')).filter(has_not_text=re.compile(r'\S')),
                page.get_by_role('button', name=re.compile(r'cerrar sesi|salir|logout', re.I)),
                page.locator('[aria-label*="cerrar" i], [aria-label*="salir" i], [aria-label*="logout" i]'),
            )
            for candidato in candidatos:
                try:
                    if candidato.count():
                        candidato.first.click(timeout=3000)
                        break
                except Exception:
                    continue
            page.locator('input#password').first.wait_for(timeout=10000)
        except Exception:
            logger.warning('Seguros del Estado: NO se pudo confirmar que la sesión quedó cerrada (revisar la cuenta).')

    @staticmethod
    def _en_pantalla_de_ingreso(page):
        try:
            return page.locator('input#email').count() > 0 and page.locator('input#password').count() > 0
        except Exception:
            return False

    def run(self):
        self._set_estado('en_proceso', mensaje=None)
        self.cotizacion.ejecutado_en = timezone.now()
        self.cotizacion.save(update_fields=['ejecutado_en'])

        try:
            with sync_playwright() as playwright, schema_context(self.schema_name):
                browser = playwright.chromium.launch(headless=self.headless)
                page = browser.new_page()
                try:
                    self._paso(PASO_LOGIN)
                    self._login(page)
                    self._paso('Apertura del cotizador')
                    self._abrir_cotizador(page)
                    self._paso('Ramo, tipo de seguro y sucursal')
                    self._paso_ramo_y_tipo_seguro(page)
                    self._paso('Placa')
                    self._paso_placa(page)
                    self._paso('Datos del vehículo')
                    self._capturar_datos_auto(page)
                    self._paso('Datos del asegurado')
                    self._paso_datos_asegurado(page)
                    self._paso('Cotización')
                    self._cotizar_y_aceptar(page)
                    self._paso('Planes cotizados')
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
            self._set_estado('cancelado', mensaje='El asesor canceló tras la alerta de fecha de nacimiento.')

        except BotTimeout:
            self._set_estado(
                'error',
                mensaje='Se agotó el tiempo esperando la confirmación del asesor (fecha de nacimiento no coincide).'
            )

        except Exception as e:
            logger.exception('Error cotizando %s en Seguros del Estado', self.vehiculo.placa)
            self._registrar_error(e)

    # ------------------------------------------------------------------
    # Pasos del flujo (numerados según la descripción original)
    # ------------------------------------------------------------------

    def _login(self, page):
        """Paso 1: iniciar sesión."""
        page.goto(self.credencial.portal_url, wait_until='domcontentloaded')
        page.get_by_label('Correo', exact=False).or_(page.get_by_placeholder('Correo', exact=False)).first.fill(self.credencial.username)
        page.get_by_label('Contraseña', exact=False).or_(page.get_by_placeholder('Contraseña', exact=False)).first.fill(self.credencial.password)
        click_by_text(page, 'Iniciar sesión', role='button')
        wait_visible(page, 'Cotizador')

    def _abrir_cotizador(self, page):
        """Paso 2: menú izquierdo -> Cotizador."""
        click_by_text(page, 'Cotizador')
        wait_visible(page, 'Ramo')

    def _paso_ramo_y_tipo_seguro(self, page):
        """Pasos 3-5: Ramo, Tipo de seguro, Sucursal, Siguiente (valores fijos por aseguradora).

        Los combos son de Material-UI (label flotante superpuesto por el botón
        real), por eso se usa click_select en vez de get_by_label/click_by_text.
        """
        click_select(page, 'Ramo', self.credencial.ramo)
        click_select(page, 'Tipo de Seguro', self.credencial.tipo_seguro)

        if self.credencial.sucursal:
            self._elegir_sucursal(page)

        click_by_text(page, 'Siguiente', role='button')
        wait_visible(page, 'Placa')

    def _elegir_sucursal(self, page):
        """«Sucursal» es un buscador (react-select-search), no un combo como Ramo y Tipo de Seguro:
        se abre la lista y se pulsa la opción por su texto."""
        campo = page.locator('label[for="userBranchs"]').locator('xpath=following::input[contains(@class,"select-search__input")][1]')
        campo.wait_for(timeout=10000)
        campo.click()
        opcion = page.locator('button.select-search__option').filter(has_text=_accent_insensitive_pattern(self.credencial.sucursal)).first
        try:
            opcion.click(timeout=8000)
        except PlaywrightTimeoutError:
            opciones = [t.strip() for t in page.locator('button.select-search__option').all_inner_texts()]
            raise BotDatosError(
                f'Seguros del Estado no ofrece la sucursal «{self.credencial.sucursal}» (opciones: {", ".join(opciones) or "ninguna"}).',
                accion='Corrija la sucursal en Configuraciones › Aseguradoras y reenvíe a Seguros del Estado.',
            )
        if not (campo.input_value() or '').strip():
            raise BotPortalError('Seguros del Estado no dejó seleccionada la sucursal después de elegirla.')

    def _paso_placa(self, page):
        """Pasos 6-8: placa, checkbox 0km si aplica, Buscar. Después de Buscar el portal muestra
        los datos del vehículo o un aviso (ej. «condiciones especiales», código 007)."""
        campo = page.locator('input[name="placa"]')
        campo.wait_for(timeout=20000)
        campo.click()
        campo.press('Control+A')
        campo.press('Delete')
        campo.press_sequentially(self.placa_portal, delay=50)

        if self.vehiculo.es_cero_km:
            page.get_by_label(re.compile(r'cero\s*k', re.I)).first.check()

        click_by_text(page, 'Buscar', role='button')
        self._esperar_vehiculo_o_aviso(page)

    def _esperar_vehiculo_o_aviso(self, page, timeout=60):
        """Espera los datos del vehículo; si antes sale un aviso del portal, lo explica."""
        for _ in range(timeout):
            aviso = self._aviso_visible(page)
            if aviso:
                raise self._error_de_aviso(aviso)
            if page.get_by_text(_accent_insensitive_pattern('Clase')).and_(page.locator(':visible')).count():
                return
            page.wait_for_timeout(1000)
        raise BotPortalError(
            f'Seguros del Estado no mostró los datos del vehículo de placa «{self.vehiculo.placa}» después de {timeout} segundos.')

    @staticmethod
    def _aviso_visible(page):
        try:
            texto = page.evaluate(
                """() => { const m = [...document.querySelectorAll('.modal.show,[role=dialog]')]
                    .find(e => e.getBoundingClientRect().width > 0 && (e.innerText || '').trim());
                    return m ? m.innerText : null; }""")
        except Exception:
            return None
        texto = re.sub(r'\s+', ' ', texto or '').strip()
        return re.sub(r'\s*ACEPTAR$', '', texto, flags=re.I).strip() or None

    @staticmethod
    def _error_de_aviso(texto):
        """Convierte un aviso del portal en el error que explica qué pasó."""
        normal = normalizar_texto(texto)
        if 'condiciones especiales' in normal or 'comunicate con la sucursal' in normal:
            return BotNoCotizableError(
                f'Seguros del Estado no cotiza este riesgo en línea: «{texto}».',
                accion='Comuníquese con la sucursal de Seguros del Estado para cotizar este riesgo; mientras tanto '
                       'cotice con las demás aseguradoras.',
            )
        return BotPortalError(f'Seguros del Estado mostró un aviso: «{texto}».')

    def _capturar_datos_auto(self, page):
        """Pasos 9-10: leer la sección Autos y guardarla en Vehiculo/Cotizacion."""
        def leer(campo):
            try:
                return page.get_by_label(campo, exact=False).first.input_value(timeout=5000)
            except PlaywrightTimeoutError:
                # Fallback: buscar el texto de la etiqueta y tomar el valor contiguo.
                return page.locator(f'text={campo}').locator('xpath=following::*[1]').first.inner_text(timeout=5000)

        clase = leer('Clase')
        marca = leer('Marca')
        linea_version = leer('Línea y versión')
        modelo = leer('Modelo')
        codigo_fasecolda = leer('Código Fasecolda') or leer('Fasecolda')

        servicio_texto = None
        try:
            servicio_texto = leer('Servicio')
        except Exception:
            servicio_texto = None

        if not servicio_texto:
            # Paso 9: si no trae servicio, se elige "Particular" manualmente.
            click_select(page, 'Servicio', 'Particular')
            servicio_texto = 'Particular'

        valor_asegurado = parse_money(leer('Valor asegurado'))
        valor_accesorios = parse_money(leer('Valor accesorios'))
        total_valor_asegurado = parse_money(leer('Total valor asegurado'))

        self.vehiculo.clase = clase or self.vehiculo.clase
        self.vehiculo.marca = marca or self.vehiculo.marca
        self.vehiculo.referencia = linea_version or self.vehiculo.referencia
        if modelo:
            self._fijar_modelo(modelo)
        self.vehiculo.codigo_fasecolda = codigo_fasecolda or self.vehiculo.codigo_fasecolda
        self.vehiculo.servicio = SERVICIO_LABEL_TO_CODE.get((servicio_texto or '').strip().lower(), self.vehiculo.servicio)
        self.vehiculo.valor_accesorios = valor_accesorios
        self._guardar_vehiculo_cambios()

        self.cotizacion.valor_asegurado = valor_asegurado
        self.cotizacion.total_valor_asegurado = total_valor_asegurado
        self.cotizacion.save(update_fields=['valor_asegurado', 'total_valor_asegurado'])

        click_by_text(page, 'Siguiente', role='button')
        wait_visible(page, 'Número de documento')

    def _paso_datos_asegurado(self, page):
        """Pasos 11-14: documento, búsqueda, ubicación y validación de fecha de nacimiento."""
        click_select(page, 'Tipo de documento', 'CC')

        page.get_by_label('Número de documento', exact=False).or_(
            page.get_by_placeholder('Número de documento', exact=False)
        ).first.fill(self.tomador.dni)

        click_by_text(page, 'Buscar', role='button')
        wait_visible(page, 'Ubicación')

        # ¿La aseguradora ya tenía el documento registrado?
        try:
            nombre_campo = page.get_by_label('Nombre', exact=False).first
            self.cotizacion.documento_verificado = bool(nombre_campo.input_value(timeout=3000).strip())
        except PlaywrightTimeoutError:
            self.cotizacion.documento_verificado = False
        self.cotizacion.save(update_fields=['documento_verificado'])

        # Paso 13: ubicación = solo el departamento del vehículo.
        departamento = self.vehiculo.zona_circulacion.departamento.nombre
        click_select(page, 'Ubicación', departamento)

        # Paso 14: comparar fecha de nacimiento mostrada vs. la registrada.
        self._validar_fecha_nacimiento(page)

    def _validar_fecha_nacimiento(self, page):
        try:
            valor = page.get_by_label('Fecha de nacimiento', exact=False).first.input_value(timeout=5000)
        except PlaywrightTimeoutError:
            self.cotizacion.fecha_nacimiento_coincide = None
            self.cotizacion.save(update_fields=['fecha_nacimiento_coincide'])
            return

        fecha_portal = self._parsear_fecha(valor)
        coincide = fecha_portal is not None and fecha_portal == self.tomador.birthdate
        self.cotizacion.fecha_nacimiento_coincide = coincide
        self.cotizacion.save(update_fields=['fecha_nacimiento_coincide'])

        if not coincide:
            self._esperar_confirmacion_asesor(
                f'La fecha de nacimiento en el portal ({valor}) no coincide con la registrada '
                f'en el sistema ({self.tomador.birthdate.strftime("%Y-%m-%d")}).'
            )

    @staticmethod
    def _parsear_fecha(texto):
        for formato in ('%d/%m/%Y', '%Y-%m-%d', '%d-%m-%Y'):
            try:
                return datetime.strptime(texto.strip(), formato).date()
            except (ValueError, AttributeError):
                continue
        return None

    def _esperar_confirmacion_asesor(self, mensaje):
        """Pausa el bot (sin cerrar el navegador) hasta que el asesor decida
        continuar o cancelar desde la interfaz de ASLAN-POLICY."""
        from core.policies.models import Cotizacion  # import local: evita ciclo al cargar el módulo

        self.cotizacion.confirmacion_bot = None
        self._set_estado('esperando_confirmacion', mensaje=mensaje)

        elapsed = 0
        while elapsed < CONFIRMACION_TIMEOUT_SECONDS:
            time.sleep(CONFIRMACION_POLL_SECONDS)
            elapsed += CONFIRMACION_POLL_SECONDS
            decision = Cotizacion.objects.filter(pk=self.cotizacion.pk).values_list('confirmacion_bot', flat=True).first()
            if decision is True:
                self._set_estado('en_proceso', mensaje=None)
                return
            if decision is False:
                raise BotCancelado()

        raise BotTimeout()

    def _cotizar_y_aceptar(self, page):
        """Pasos 15-16: si hubo alerta de fecha, dar continuar; luego cotizar y aceptar."""
        try:
            click_by_text(page, 'Continuar', role='button', timeout=3000)
        except PlaywrightTimeoutError:
            pass  # no había alerta pendiente en pantalla

        click_by_text(page, 'Cotizar', role='button')
        wait_visible(page, 'Aceptar')

        click_by_text(page, 'Aceptar', role='button')
        wait_visible(page, 'Prima total')

    def _capturar_planes(self, page):
        """Paso 17: capturar la prima total de cada plan de preferencia."""
        from core.policies.models import CotizacionPlan  # import local: evita ciclo al cargar el módulo

        self.cotizacion.planes.all().delete()
        for nombre_plan in ('Elite', 'Clásico', 'Escencial'):
            try:
                bloque = page.get_by_text(nombre_plan, exact=False).first
                prima_texto = bloque.locator('xpath=following::*[contains(translate(text(),'
                                              '"ABCDEFGHIJKLMNOPQRSTUVWXYZÁÉÍÓÚ","abcdefghijklmnopqrstuvwxyzáéíóú"),'
                                              '"prima total")]/following::*[1]').first.inner_text(timeout=5000)
                prima_total = parse_money(prima_texto)
            except PlaywrightTimeoutError:
                logger.warning('No se pudo leer la prima total del plan %s', nombre_plan)
                prima_total = None

            if prima_total is not None:
                CotizacionPlan.objects.create(
                    cotizacion=self.cotizacion,
                    nombre_plan=nombre_plan,
                    prima_total=prima_total,
                )
