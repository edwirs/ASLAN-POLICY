"""Bot de cotización para el portal web de Qualitas Colombia.

IMPORTANTE — igual que con el bot de Seguros del Estado: se escribió a partir
de la descripción paso a paso del usuario, sin haber inspeccionado el HTML
real del portal (no se puede iniciar sesión con credenciales reales para
inspeccionar). Selectores por texto visible, con más de un patrón de
respaldo donde el tipo de control (combo/checkbox/autocompletar) no se
conocía con certeza. Es muy probable que la primera corrida real necesite
ajustes puntuales — correr con el comando de gestión, revisar el
diagnóstico (screenshot + textos) que se guarda en media/bot_debug/, y
ajustar solo el paso que falle en vez de reescribir todo.
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

# Este bot usa page.expect_popup() para capturar la ventana nueva que abre
# "Cotizar". Eso dispara internamente un loop de asyncio en el mismo hilo
# (aun usando la API "sync" de Playwright), y Django detecta ese loop y
# bloquea cualquier llamada al ORM después con SynchronousOnlyOperation. No
# hay concurrencia real que cuidar aquí (es un comando de gestión de un solo
# hilo), así que se usa la vía oficial de Django para este caso exacto.
os.environ.setdefault('DJANGO_ALLOW_ASYNC_UNSAFE', 'true')

from core.policies.services.bots.base import (
    PASO_LOGIN,
    BotAutenticacionError,
    BotCancelado,
    BotDatosError,
    BotPortalError,
    BotTimeout,
    RegistroErrorMixin,
    _accent_insensitive_pattern,
    buscar_y_seleccionar_autocompletar,
    check_option,
    click_by_text,
    click_resilient,
    close_icon_popup,
    close_known_modals,
    esperar_algun_visible,
    exigir_clave_al_dia,
    normalizar_texto,
    parse_money,
    remove_stray_backdrops,
    select_generic,
    wait_visible,
)

logger = logging.getLogger(__name__)

# IDs de modales informativos vistos en corridas reales (el portal mantiene
# varios montados a la vez, en distintos momentos, así que se cierran por ID
# conocido en vez de "el primer modal visible" — que agarraba el equivocado).
MODALES_HOME = ('modalBonos',)
MODALES_COTIZADOR = ('modalAvisoBonos', 'modalAcomCercano')

AMPAROS_ACCESORIOS = (
    'Pérdida de llaves',
    'Gastos de transporte pérdida total',
    'Gastos de transporte pérdida parcial',
    'Llantas estalladas',
    'Rotura de vidrios',
    'Pequeños accesorios',
)

GENERO_LABEL = {'male': 'Masculino', 'female': 'Femenino'}


class QualitasBot(RegistroErrorMixin):
    """Automatiza una cotización de todo riesgo en el portal de Qualitas
    Colombia. Uso: QualitasBot(cotizacion, headless=True).run()"""

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
                accion='Cree o active la credencial de Qualitas en Credenciales de Aseguradora y reenvíe la solicitud.',
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
        momento de una falla. Nunca vuelca el HTML completo ni valores de
        inputs (evita exponer la contraseña ya tecleada en el DOM)."""
        try:
            debug_dir = os.path.join(settings.MEDIA_ROOT, 'bot_debug')
            os.makedirs(debug_dir, exist_ok=True)
            stamp = timezone.now().strftime('%Y%m%d_%H%M%S')
            base = os.path.join(debug_dir, f'qualitas_{self.cotizacion.pk}_{stamp}')

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

            # Si hay un modal visible bloqueando, se vuelca su estructura
            # (sin valores de inputs) para identificar el botón real de cierre.
            try:
                modal_html = page.locator(
                    '.modal.show:visible, .modal.in:visible, [role="dialog"][aria-modal="true"]:visible'
                ).first.evaluate('el => el.outerHTML.slice(0, 4000)')
                with open(f'{base}_modal.html', 'w', encoding='utf-8') as f:
                    f.write(modal_html)
            except Exception:
                pass

            logger.warning('Diagnóstico del bot guardado en %s.png / %s.txt', base, base)
        except Exception:
            logger.exception('No se pudo capturar el diagnóstico de la página tras la falla')

    def _cerrar_sesion(self, page):
        """Best-effort: cierra la sesión para no acumular sesiones activas
        entre corridas. Nunca lanza excepción.

        IMPORTANTE — bug real detectado revisando capturas de TODAS las
        corridas de hoy: esto nunca logró cerrar sesión ("No se pudo cerrar
        sesión..." salió en cada log). "Cerrar sesión" vive colapsado dentro
        del menú de cuenta (arriba a la derecha), y hay que abrir ese menú
        primero haciendo clic en el ícono de persona
        (<a class="picture-profile">) — el texto "21301 MAESTRA" y el ícono
        de flecha (<img id="fdown">) NO abren nada, solo el ícono de
        persona (confirmado con una prueba aislada de login+logout). Además
        "Cerrar sesión" no es un <button> (buscarlo con role='button' nunca
        podía encontrarlo).
        """
        try:
            try:
                page.locator('a.picture-profile').first.click(timeout=2000)
            except Exception:
                pass
            for patron in ('Cerrar sesión', 'Salir', 'Logout'):
                try:
                    click_by_text(page, patron, timeout=2000)
                    return
                except PlaywrightTimeoutError:
                    continue
            page.locator('[aria-label*="cerrar" i], [aria-label*="salir" i], [aria-label*="logout" i]').first.click(timeout=2000)
        except Exception:
            logger.warning('No se pudo cerrar sesión explícitamente en el portal de Qualitas (best-effort).')

    def run(self):
        self._set_estado('en_proceso', mensaje=None)
        self.cotizacion.ejecutado_en = timezone.now()
        self.cotizacion.save(update_fields=['ejecutado_en'])

        cotizador_page = None
        try:
            with sync_playwright() as playwright, schema_context(self.schema_name):
                browser = playwright.chromium.launch(headless=self.headless)
                page = browser.new_page()
                try:
                    self._paso(PASO_LOGIN)
                    self._login(page)
                    self._paso('Ventanas informativas')
                    self._cerrar_popups(page, MODALES_HOME)

                    self._paso('Apertura del cotizador')
                    with page.expect_popup() as popup_info:
                        click_by_text(page, 'Cotizar')
                    cotizador_page = popup_info.value
                    cotizador_page.wait_for_load_state('domcontentloaded')
                    self._cerrar_popups(cotizador_page, MODALES_COTIZADOR)

                    self._paso('Origen y uso')
                    self._origen_y_uso(cotizador_page)
                    self._paso('Datos del vehículo')
                    self._datos_vehiculo(cotizador_page)
                    self._paso('Datos de cotización')
                    self._datos_cotizacion(cotizador_page)
                    self._paso('Amparos')
                    self._amparos(cotizador_page)
                    self._paso('Importe total')
                    self._guardar_y_capturar_total(cotizador_page)
                    self._paso('Paquetes y formas de pago')
                    self._capturar_resumen(cotizador_page)
                except (BotCancelado, BotTimeout):
                    raise
                except Exception:
                    self._guardar_pantalla(cotizador_page or page)
                    self._capturar_diagnostico(cotizador_page or page)
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
            logger.exception('Error cotizando %s en Qualitas', self.vehiculo.placa)
            self._registrar_error(e)

    # ------------------------------------------------------------------
    # Pasos del flujo
    # ------------------------------------------------------------------

    def _login(self, page):
        """Login con código de intermediario + cuenta + contraseña (no
        email+contraseña como Seguros del Estado).

        Los 3 campos de este formulario no tienen una asociación <label for>
        confiable (get_by_label mezcló valores entre campos en la primera
        corrida real), así que se identifican por posición: los dos primeros
        inputs de texto visibles son código de intermediario y cuenta, y el
        input de contraseña se identifica por su type="password".
        """
        page.goto(self.credencial.portal_url, wait_until='domcontentloaded')
        campos_texto = page.locator(
            'input:not([type="password"]):not([type="hidden"]):not([type="checkbox"]):not([type="radio"])'
        )
        campos_texto.nth(0).wait_for(timeout=15000)

        # fill() asigna el valor de una sola vez sin eventos de tecleo reales;
        # visto en corrida real que esto deja el campo de código con un valor
        # mezclado ("21301-MAESTRA") y el de cuenta vacío — el campo tiene
        # lógica JS (autocompletar/autoformateo) que solo reacciona a tecleo
        # real. Se usa press_sequentially, igual que en el campo de
        # residencia, para evitar la misma clase de falla intermitente.
        campo_codigo = campos_texto.nth(0)
        campo_cuenta = campos_texto.nth(1)
        campo_password = page.locator('input[type="password"]').first

        def escribir_verificado(campo, valor, intentos=3):
            """Teclea y confirma que el valor quedó completo antes de seguir.
            Se vio en corrida real que un solo carácter podía perderse (el
            campo quedó con "2" en vez de "21301"), probablemente por un
            re-render del framework justo al iniciar el tecleo — se reintenta
            limpiando el campo en vez de asumir que un solo intento basta.
            """
            for _ in range(intentos):
                campo.click()
                campo.press('Control+A')
                campo.press('Delete')
                # Reseteo duro adicional: se vio en corrida real que un
                # widget de autocompletar en este campo puede dejar texto
                # residual que Control+A/Delete no siempre limpia del todo
                # entre reintentos, acumulando texto duplicado/mezclado.
                campo.fill('')
                campo.press_sequentially(valor, delay=100)
                page.wait_for_timeout(300)
                if campo.input_value(timeout=2000) == valor:
                    return
            raise RuntimeError(f'No se pudo escribir el valor esperado en el campo de login (quedó: "{campo.input_value()}")')

        escribir_verificado(campo_codigo, self.credencial.codigo_intermediario)
        escribir_verificado(campo_cuenta, self.credencial.cuenta)
        escribir_verificado(campo_password, self.credencial.password)

        click_by_text(page, 'Acceder', role='button')
        wait_visible(page, 'Cotizar')

    def _cerrar_popups(self, page, modal_ids, intentos=1, timeout=8000):
        """Cierra ventanas informativas. Primero intenta por los IDs de
        modal ya vistos en corridas reales (más confiable: esta app puede
        tener varios modales montados a la vez, y "el primer modal visible"
        genérico a veces agarra uno distinto al que realmente bloquea).
        Si no encuentra ninguno de esos IDs, cae al detector genérico.
        Best-effort: si no aparece ninguna ventana, sigue sin fallar.
        """
        if close_known_modals(page, modal_ids, timeout=timeout):
            return
        for _ in range(intentos):
            cerrado = close_icon_popup(page, timeout=timeout)
            if not cerrado:
                break

    def _click_siguiente(self, page, texto_marcador_paso_siguiente, intentos=3):
        """Clic en 'Siguiente' verificando que el wizard realmente avanzó,
        confirmando por un texto propio del CONTENIDO del paso siguiente
        (ej. una etiqueta de campo) — nunca por el nombre del paso en sí
        ("Datos de cotización", etc.), porque ese nombre ya está visible todo
        el tiempo en el menú lateral de pasos, sin importar en cuál paso
        real se esté parado (primera versión de esto tenía ese bug: el clic
        "aprobaba" sin que el wizard avanzara de verdad).

        Visto en corrida real: el clic puede "tomar" sin ningún error de
        Playwright pero el wizard se queda en el mismo paso (validación
        silenciosa, o un backdrop residual interceptando el submit interno
        del formulario) — no basta con asumir que un clic sin excepción
        significa que de verdad avanzó.
        """
        # Importante: el clic se hace UNA sola vez, no dentro del bucle de
        # reintentos. Visto en corrida real (3 veces seguidas) que este
        # paso puede tardar bastante en recalcular antes de habilitar el
        # siguiente paso — reintentar el CLIC mismo (no solo la espera)
        # arriesga disparar cálculos duplicados que nunca terminan de
        # resolver limpio. Se reintenta solo si el clic en sí falla
        # (ej. bloqueado por un backdrop), no si ya se hizo y solo falta
        # esperar más.
        ultimo_error = None
        clic_hecho = False
        for _ in range(intentos):
            remove_stray_backdrops(page)
            try:
                page.locator('#loader').wait_for(timeout=2000, state='hidden')
            except PlaywrightTimeoutError:
                pass
            try:
                click_by_text(page, 'Siguiente', role='button', timeout=45000)
                clic_hecho = True
                break
            except PlaywrightTimeoutError as e:
                ultimo_error = e
        if not clic_hecho:
            raise ultimo_error
        # Una sola espera larga tras el único clic, sin volver a clickear.
        esperar_algun_visible(page, texto_marcador_paso_siguiente, timeout=90000)

    def _origen_y_uso(self, page):
        """Origen y uso: Livianos -> (despliega más opciones) -> Particular.
        Son tarjetas clicables (no un combo), y un modal informativo puede
        seguir interceptando el clic incluso después de _cerrar_popups (su
        aparición no es 100% predecible en el tiempo) — por eso el clic es
        resiliente y reintenta cerrando modales conocidos si lo bloquean."""
        click_resilient(page, 'Livianos', MODALES_COTIZADOR)
        click_resilient(page, 'Particular', MODALES_COTIZADOR)
        self._click_siguiente(page, 'Selecciona o busca los datos del vehículo')

    def _datos_vehiculo(self, page):
        """Búsqueda por placa y captura de los datos que trae el portal.

        El ícono de lupa junto al campo no es un <button> real (un primer
        intento con "el siguiente button en el documento" terminó haciendo
        clic en algo completamente distinto y la búsqueda nunca se disparó,
        dejando Año/Marca/Tipo/Versión vacíos sin que nada fallara). Otros
        campos de búsqueda de este mismo formulario dicen literalmente
        "Enter para buscar", así que se usa ese patrón en vez de adivinar
        un botón.
        """
        campo_placa = page.get_by_label('Búsqueda por placa', exact=False).or_(
            page.get_by_placeholder('Búsqueda por placa', exact=False)
        ).first
        # El tiempo que tarda en volverse visible tras "Origen y uso" varía
        # bastante entre corridas (visto: a veces listo en segundos, a veces
        # sigue oculto pasados 15s) — se le da más margen en vez de asumir
        # que el paso anterior ya dejó todo renderizado.
        campo_placa.wait_for(timeout=30000, state='visible')
        campo_placa.fill(self.placa_portal)
        if self.vehiculo.es_cero_km:
            # Un 0 km no está registrado en Qualitas: buscar por placa responde «Placa o código FASECOLDA no
            # encontrado». La placa de 0 km (`PLACA_CERO_KM`) solo se deja escrita (sin Enter) porque el campo es
            # obligatorio, y el vehículo se busca por su código Fasecolda (el año se completa solo).
            campo_placa.press('Tab')
            self._buscar_por_fasecolda(page)
        else:
            campo_placa.press('Enter')

        # "Fasecolda" ya está en pantalla como etiqueta de campo aunque la
        # búsqueda no haya devuelto nada todavía, así que no sirve como señal
        # de éxito. Se espera a que el combo "Año" deje de estar vacío.
        campo_anio = page.get_by_label('Año', exact=False).first
        for _ in range(20):
            try:
                if campo_anio.input_value(timeout=1000):
                    break
            except Exception:
                pass
            time.sleep(0.5)

        def leer_select(selector):
            """Texto de la opción seleccionada de un <select>. Se leen por su id
            real: la lectura anterior por etiqueta caía en un respaldo que
            raspaba texto cercano y llegó a guardar el aviso "* La búsqueda
            muestra hasta 15 resultados..." como marca y referencia."""
            try:
                return page.locator(selector).evaluate(
                    "e => e.selectedIndex >= 0 ? e.options[e.selectedIndex].text.trim() : ''") or None
            except Exception:
                return None

        def leer_input(selector):
            try:
                return page.locator(selector).input_value(timeout=5000).strip() or None
            except Exception:
                return None

        anio = leer_select('#selectYear')
        marca = leer_select('#selectBrand')
        tipo = leer_select('#selectType')
        version = leer_select('#selectVersion')
        fasecolda = leer_input('#AMIS')
        chasis = leer_input('#serie')

        if anio:
            self._fijar_modelo(anio)
        self.vehiculo.marca = marca or self.vehiculo.marca
        self.vehiculo.clase = tipo or self.vehiculo.clase
        self.vehiculo.referencia = version or self.vehiculo.referencia
        self.vehiculo.codigo_fasecolda = fasecolda or self.vehiculo.codigo_fasecolda
        if chasis:
            self.vehiculo.chasis = chasis
        self._guardar_vehiculo_cambios()

        # Lugar de residencia = zona de circulación registrada en la solicitud.
        municipio = self.vehiculo.zona_circulacion.nombre
        buscar_y_seleccionar_autocompletar(
            page,
            texto_a_escribir=municipio,
            opcion_esperada=municipio,
            campo_label='Lugar de residencia del asegurado',
            preferir_texto=self.vehiculo.zona_circulacion.departamento.nombre,
        )

        self._click_siguiente(page, 'Tipo de vigencia')

    def _buscar_por_fasecolda(self, page):
        """0 km: busca el vehículo por código Fasecolda (campo «Código Fasecolda (Enter para buscar)»)."""
        codigo = (self.vehiculo.codigo_fasecolda or '').strip()
        if not codigo:
            raise BotDatosError(
                'Qualitas busca un 0 km por su código Fasecolda y la solicitud no lo tiene.',
                accion='Registre la solicitud con el código Fasecolda del vehículo y reenvíe a Qualitas.',
            )
        campo = page.locator('#AMIS')
        campo.wait_for(timeout=20000, state='visible')
        campo.fill(codigo)
        campo.press('Enter')

    def _datos_cotizacion(self, page):
        """Captura los datos de vigencia/valor asegurado que trae el portal,
        y llena los campos fijos del asesor + datos del asegurado."""

        def leer(campo):
            try:
                return page.get_by_label(campo, exact=False).first.input_value(timeout=5000)
            except Exception:
                return None

        tipo_vigencia = leer('Tipo de vigencia')
        meses = leer('Meses')
        fecha_inicio = leer('Inicio de vigencia')
        fecha_fin = leer('Fin de vigencia')
        tipo_valor_asegurado = leer('Tipo de valor asegurado')
        valor_asegurado = leer('Valor asegurado')
        moneda = leer('Moneda')

        self.cotizacion.tipo_vigencia = tipo_vigencia
        self.cotizacion.meses_vigencia = int(meses) if meses and meses.isdigit() else None
        self.cotizacion.fecha_vigencia_inicio = self._parsear_fecha(fecha_inicio)
        self.cotizacion.fecha_vigencia_fin = self._parsear_fecha(fecha_fin)
        self.cotizacion.tipo_valor_asegurado = tipo_valor_asegurado
        self.cotizacion.valor_asegurado = parse_money(valor_asegurado)
        self.cotizacion.moneda = moneda
        self.cotizacion.save()

        def llenar_lento(label, valor, timeout=20000, escribir_real=False):
            """Como fill(), pero filtrando a campos YA VISIBLES antes de
            tomar ".first". Se vio en corrida real que get_by_label('Correo
            electrónico') resolvía al campo de un modal COMPLETAMENTE
            distinto y oculto (#modalSendPDFEmail, "enviar PDF por correo",
            premontado en el DOM aunque no se esté usando), en vez del campo
            real y visible del paso "Datos de cotización" — mismo patrón de
            duplicados ocultos premontados ya visto con el marcador de avance
            de paso (ver esperar_algun_visible)."""
            patron = _accent_insensitive_pattern(label)
            campo = page.get_by_label(patron, exact=False).and_(page.locator(':visible')).first
            try:
                campo.wait_for(timeout=timeout, state='visible')
            except PlaywrightTimeoutError:
                # Incluso filtrando por visible, no hay ningún <label for>
                # que asocie correctamente con este campo (mismo problema ya
                # visto en login/residencia: el for= de este portal no
                # siempre apunta al id real de su input hermano). Se ubica
                # por el TEXTO visible del label y se sube al padre directo
                # (marcado consistente en todo el portal:
                # <div class="form-group"><input>...<label>texto</label></div>).
                etiqueta = page.get_by_text(patron).and_(page.locator(':visible')).first
                etiqueta.wait_for(timeout=timeout)
                contenedor = etiqueta.locator('xpath=..')
                campo = contenedor.locator('input:not([type="hidden"])').first
                campo.wait_for(timeout=timeout, state='visible')
            campo.scroll_into_view_if_needed(timeout=timeout)
            if escribir_real:
                # Los campos de fecha (datepicker) no registran bien un
                # fill() directo: visto en corrida real que el calendario
                # queda abierto sin confirmar y el campo sigue marcado como
                # inválido ("Ingrese su fecha de nacimiento"). Se teclea de
                # verdad y se cierra el calendario con Escape.
                campo.click()
                campo.press_sequentially(valor, delay=80)
                page.keyboard.press('Escape')
            else:
                campo.fill(valor, timeout=timeout)

        # Datos fijos de contacto (configurados en la credencial de la aseguradora).
        llenar_lento('Correo electrónico', self.credencial.correo_contacto)
        llenar_lento('Teléfono móvil', self.credencial.telefono_contacto)

        # El <select id="selectTypePerson"> real solo tiene las opciones
        # "Natural" / "Jurídica" (no "Persona Natural"/"Persona Jurídica" —
        # visto en el volcado del HTML real de este campo).
        es_juridica = (self.tomador.document_type.abbreviation or '').upper() == 'NIT'
        select_generic(page, 'Tipo de persona', 'Jurídica' if es_juridica else 'Natural', timeout=15000)

        llenar_lento('Nombre de asegurado', self.tomador.names)

        genero_label = GENERO_LABEL.get(self.tomador.gender)
        if genero_label:
            try:
                select_generic(page, 'Género', genero_label, timeout=5000)
            except Exception:
                pass  # el campo puede no habilitarse en todos los casos (ej. persona jurídica)

        fecha_nacimiento = self.tomador.birthdate.strftime('%d/%m/%Y')
        llenar_lento('Fecha de nacimiento', fecha_nacimiento, escribir_real=True)

        self._click_siguiente(page, 'Asistencia en viaje')

    def _seleccionar_en_fila(self, page, texto_fila, opcion_texto, timeout=10000):
        """Selecciona una opción en el <select> de la tabla "Amparos base"
        (columnas Amparos | Valor asegurado | Deducibles). El <select> no es
        hermano directo de su etiqueta (viven en celdas distintas de la
        misma fila), así que se ubica el ancestro más cercano que contenga
        AMBOS — la fila — y se busca el <select> ahí, no en todo el
        documento (evita agarrar el de una fila vecina)."""
        patron = _accent_insensitive_pattern(texto_fila)
        etiqueta = page.get_by_text(patron, exact=False).and_(page.locator(':visible')).first
        etiqueta.wait_for(timeout=timeout)
        contenedor = etiqueta.locator('xpath=ancestor::*[.//select][1]')
        select_el = contenedor.locator('select').first
        select_el.wait_for(timeout=timeout)
        # Se eligen las opciones REALES del desplegable, sin asumir mayúsculas:
        # select_option(label="PLUS") falló con "did not find some options".
        opciones = [o.strip() for o in select_el.evaluate("e => [...e.options].map(o => o.text)")]
        objetivo = next((o for o in opciones if normalizar_texto(o) == normalizar_texto(opcion_texto)), None) or \
            next((o for o in opciones if normalizar_texto(opcion_texto) in normalizar_texto(o)), None)
        if objetivo is None:
            raise BotPortalError(
                f'Qualitas no ofrece «{opcion_texto.title()}» en «{texto_fila}» para este vehículo '
                f'(opciones disponibles: {", ".join(o for o in opciones if o) or "ninguna"}).',
                accion='Revise en el portal de Qualitas qué asistencia en viaje permite este vehículo; '
                       'si ya no existe «Plus», avise a soporte para ajustar el paquete fijo.',
            )
        select_el.select_option(label=objetivo, timeout=timeout)

    def _amparos(self, page):
        """Asistencia en viaje = Plus, y los amparos accesorios fijos."""
        self._seleccionar_en_fila(page, 'Asistencia en Viaje', 'PLUS')

        for amparo in AMPAROS_ACCESORIOS:
            check_option(page, amparo)

        # Campos que se despliegan al marcar ciertos amparos.
        select_generic(page, 'Días', '15')
        self._deducible_en_tarjeta(page, 'Rotura de vidrios', '5%')

    def _deducible_en_tarjeta(self, page, titulo_tarjeta, opcion_texto, timeout=10000):
        """Elige un valor en el deducible que se despliega dentro de la tarjeta del amparo accesorio
        `titulo_tarjeta`. No se busca «Deducible» en toda la página: hay más de uno (el de «Llantas
        estalladas», el de «Rotura de vidrios» y la columna «Deducibles» de los amparos base)."""
        etiqueta = page.get_by_text(_accent_insensitive_pattern(titulo_tarjeta), exact=False).and_(page.locator(':visible')).first
        etiqueta.wait_for(timeout=timeout)
        tarjeta = etiqueta.locator('xpath=ancestor::*[.//select][1]')
        selects = tarjeta.locator('select')
        selects.first.wait_for(timeout=timeout)
        ofrecidas = []
        for i in range(selects.count()):
            select_el = selects.nth(i)
            opciones = [o.strip() for o in select_el.evaluate("e => [...e.options].map(o => o.text)")]
            ofrecidas.append(opciones)
            elegido = next((o for o in opciones if normalizar_texto(o) == normalizar_texto(opcion_texto)), None)
            if elegido is not None:
                select_el.select_option(label=elegido, timeout=timeout)
                return
        raise BotPortalError(
            f'Qualitas no ofrece el deducible «{opcion_texto}» en «{titulo_tarjeta}» '
            f'(listas de la tarjeta: {" / ".join(", ".join(o for o in lista if o) for lista in ofrecidas) or "ninguna"}).',
            accion='Revise en el portal de Qualitas qué deducibles permite este vehículo para ese amparo; '
                   'si el valor fijo ya no existe, avise a soporte para ajustarlo.',
        )

    def _guardar_y_capturar_total(self, page):
        click_by_text(page, 'Guardar cambios', role='button')
        wait_visible(page, 'Importe total')

        try:
            importe = page.get_by_label('Importe total', exact=False).first.input_value(timeout=5000)
        except PlaywrightTimeoutError:
            importe = page.locator('text=Importe total').locator('xpath=following::*[1]').first.inner_text(timeout=5000)

        self.cotizacion.prima_total = parse_money(importe)
        self.cotizacion.save(update_fields=['prima_total'])

    def _capturar_resumen(self, page):
        """Extras de la pantalla de Amparos, después de guardar: los paquetes que el portal
        sugiere comparar (con su valor anual). AMPLIA ya incluye los amparos accesorios
        elegidos por el bot (es el importe total); PLUS y BASICA son los paquetes estándar.
        Las demás formas de pago (financiada, semestral…) NO se guardan: tras «Guardar
        cambios» el portal solo actualiza la anual y deja las otras con valores anteriores.
        No es obligatorio: si algo cambia en el portal, la cotización igual queda completada
        con el importe total (se registra el motivo en el log)."""
        try:
            cuerpo = page.evaluate('document.body.innerText') or ''
            self._guardar_volcado(page, cuerpo)

            paquetes = []
            for nombre, valor in re.findall(r'([A-ZÁÉÍÓÚÑ]{3,})\s*\$\s*([\d.,]+)\s*\(anual\)', cuerpo):
                if nombre not in {n for n, _ in paquetes}:
                    paquetes.append((nombre, valor))
            if not paquetes:
                return

            from core.policies.models import CotizacionPlan  # import local: evita ciclo al cargar el módulo

            with schema_context(self.schema_name):
                self.cotizacion.planes.all().delete()
                for nombre, valor in paquetes:
                    etiqueta = nombre.title().replace('Basica', 'Básica')
                    CotizacionPlan.objects.create(cotizacion=self.cotizacion, nombre_plan=etiqueta, prima_total=parse_money(valor))
                self.cotizacion.mensaje_bot = ('Amplia incluye los amparos accesorios elegidos (llaves, transportes, llantas, '
                                               'vidrios con deducible 5%, pequeños accesorios); Plus y Básica son los paquetes '
                                               'estándar del portal. Valores anuales.')
                self.cotizacion.moneda = 'Pesos'
                self.cotizacion.save(update_fields=['mensaje_bot', 'moneda'])
        except Exception:
            logger.warning('Qualitas: no se pudieron capturar los paquetes (la cotización sigue válida).', exc_info=True)

    def _guardar_volcado(self, page, cuerpo):
        """Guarda el texto y una captura de la pantalla de resultado, para poder revisar qué se leyó."""
        try:
            debug_dir = os.path.join(settings.MEDIA_ROOT, 'bot_debug')
            os.makedirs(debug_dir, exist_ok=True)
            base = os.path.join(debug_dir, f'qualitas_resumen_{self.cotizacion.pk}')
            with open(f'{base}.txt', 'w', encoding='utf-8') as f:
                f.write(cuerpo)
            page.screenshot(path=f'{base}.png', full_page=True)
        except Exception:
            logger.warning('Qualitas: no se pudo guardar el volcado de la pantalla de resultado.', exc_info=True)

    @staticmethod
    def _parsear_fecha(texto):
        if not texto:
            return None
        for formato in ('%d/%m/%Y', '%Y-%m-%d', '%d-%m-%Y'):
            try:
                return datetime.strptime(texto.strip(), formato).date()
            except (ValueError, AttributeError):
                continue
        return None
