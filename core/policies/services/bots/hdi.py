"""Bot de cotización para HDI Seguros (Oficina en línea + cotizador de autos).

Flujo (mapeado con una sesión real exploratoria, no a ciegas):
  1. Oficina en línea (oficinaenlinea.hdiseguros.com.co): tipo de documento +
     nº de identificación + contraseña.
  2. Productos > Autos individual > clave de agencia > Consultar. Eso abre el
     cotizador (auto.hdiseguros.com.co) en una ventana nueva.
  3. Cotizador, 4 pasos: validación de datos (identificación + placa) ->
     información del vehículo -> información personal -> cotización.
  4. Se captura el valor de cada paquete (Dinámico/Ligero/Integral/Premium);
     el Premium queda como `prima_total`.

Sesiones: al terminar (bien o mal) SIEMPRE se cierra sesión. Cerrar sesión
desde el cotizador cierra también la oficina en línea.
"""
import logging
import os
import re
import time
import unicodedata
from datetime import timedelta

from django.conf import settings
from django.db import connection
from django.utils import timezone
from django_tenants.utils import schema_context
from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeoutError

# Mismo motivo que en qualitas.py: page.expect_popup() corre un loop de asyncio
# en el hilo y Django bloquearía el ORM sin esta vía oficial.
os.environ.setdefault('DJANGO_ALLOW_ASYNC_UNSAFE', 'true')

from core.policies.services.bots.base import (  # noqa: E402
    PASO_LOGIN,
    PLACA_CERO_KM,
    BotAutenticacionError,
    BotCancelado,
    BotDatosError,
    BotPortalError,
    BotTimeout,
    RegistroErrorMixin,
    _accent_insensitive_pattern,
    dividir_nombre,
    escribir_verificado,
    exigir_clave_al_dia,
    normalizar_texto,
    parse_money,
)

logger = logging.getLogger(__name__)

USO_VEHICULO = 'Particular personas'
TIPO_PLACA_NORMAL = 'Colombiana'
TIPO_PLACA_CERO_KM = 'Tránsito Libre (Vehículo 0 km)'
# Un 0 km no tiene placa: con el tipo «Tránsito Libre» HDI pide un número de tránsito libre y se usa
# siempre la placa de 0 km común a todos los bots (`PLACA_CERO_KM`), no el dato de la solicitud.
MESES = ['Enero', 'Febrero', 'Marzo', 'Abril', 'Mayo', 'Junio', 'Julio', 'Agosto',
         'Septiembre', 'Octubre', 'Noviembre', 'Diciembre']


class HdiBot(RegistroErrorMixin):
    """Cotiza todo riesgo en HDI. Uso: HdiBot(cotizacion, headless=True).run()"""

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

    def _get_credencial(self):
        credencial = self.cotizacion.aseguradora.credenciales.filter(is_active=True).order_by('-id').first()
        if credencial is None:
            raise BotAutenticacionError(
                f'No hay una credencial activa configurada para "{self.cotizacion.aseguradora}".',
                accion='Cree o active la credencial de HDI en Credenciales de Aseguradora y reenvíe la solicitud.',
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
        """Screenshot + textos de botones/enlaces/labels visibles al fallar.
        Nunca vuelca valores de inputs (podrían ser la contraseña)."""
        try:
            debug_dir = os.path.join(settings.MEDIA_ROOT, 'bot_debug')
            os.makedirs(debug_dir, exist_ok=True)
            stamp = timezone.now().strftime('%Y%m%d_%H%M%S')
            base = os.path.join(debug_dir, f'hdi_{self.cotizacion.pk}_{stamp}')
            page.screenshot(path=f'{base}.png', full_page=True)
            textos = page.eval_on_selector_all(
                'button, a, [role="button"], label, h1, h2, h3, h4',
                'els => els.map(e => (e.innerText || "").trim()).filter(Boolean)'
            )
            with open(f'{base}.txt', 'w', encoding='utf-8') as f:
                f.write(f'URL: {page.url}\n\nTextos visibles:\n')
                for texto in textos:
                    f.write(f'- {texto}\n')
            logger.warning('Diagnóstico del bot HDI guardado en %s.png / %s.txt', base, base)
        except Exception:
            logger.exception('No se pudo capturar el diagnóstico de HDI tras la falla')

    def _cerrar_sesion(self, cotizador, home):
        """Cierra sesión SIEMPRE, sin lanzar excepción. Cerrar desde el
        cotizador cierra también la oficina en línea; se intenta además en
        la oficina por si el cotizador nunca llegó a abrirse."""
        for pagina in (cotizador, home):
            if pagina is None:
                continue
            try:
                if pagina.is_closed():
                    continue
                pagina.get_by_text('Cerrar sesión').first.click(timeout=4000)
                pagina.wait_for_timeout(2000)
            except Exception:
                continue
        try:
            home.reload(wait_until='domcontentloaded')
            if home.locator('#password__input').count() == 0:
                logger.warning('HDI: no se pudo confirmar que la sesión quedó cerrada (revisar).')
        except Exception:
            logger.warning('HDI: no se pudo verificar el cierre de sesión (best-effort).')

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
                home = contexto.new_page()
                cotizador = None
                try:
                    self._paso(PASO_LOGIN)
                    self._login(home)
                    self._paso('Menú Productos > Autos individual')
                    cotizador = self._abrir_cotizador(home)
                    self._paso('Validación de datos (identificación y placa)')
                    self._validacion_datos(cotizador)
                    self._paso('Información del vehículo')
                    self._info_vehiculo(cotizador)
                    self._paso('Información personal')
                    self._info_personal(cotizador)
                    self._paso('Cotización (paquetes)')
                    self._capturar_cotizacion(cotizador)
                except (BotCancelado, BotTimeout):
                    raise
                except Exception:
                    self._guardar_pantalla(cotizador or home)
                    self._capturar_diagnostico(cotizador or home)
                    raise
                finally:
                    self._cerrar_sesion(cotizador, home)
                    browser.close()

            self._set_estado('completado', mensaje=None)

        except BotCancelado:
            self._set_estado('cancelado', mensaje='El asesor canceló tras una alerta de confirmación.')
        except BotTimeout:
            self._set_estado('error', mensaje='Se agotó el tiempo esperando la confirmación del asesor.')
        except Exception as e:
            logger.exception('Error cotizando %s en HDI', self.vehiculo.placa)
            self._registrar_error(e)

    # ------------------------------------------------------------------
    # Pasos
    # ------------------------------------------------------------------

    def _login(self, page):
        page.goto(self.credencial.portal_url, wait_until='domcontentloaded')
        combo = page.locator('div[role=button][aria-haspopup=listbox]').first
        combo.wait_for(timeout=20000)
        combo.click()
        tipo = self.credencial.tipo_documento or 'Cédula de ciudadanía'
        page.get_by_role('option', name=_accent_insensitive_pattern(tipo)).first.click()
        escribir_verificado(page, page.locator('#document__number__input'), self.credencial.username)
        escribir_verificado(page, page.locator('#password__input'), self.credencial.password)
        page.get_by_role('button', name=re.compile(r'^Ingresar$', re.I)).first.click()
        try:
            page.get_by_text('Productos', exact=True).first.wait_for(timeout=25000)
        except PlaywrightTimeoutError:
            raise BotAutenticacionError('No se pudo iniciar sesión en HDI: después de ingresar no apareció el menú principal (¿contraseña vencida o cuenta bloqueada?).')

    def _abrir_cotizador(self, home):
        """Productos > Autos individual > clave > Consultar -> ventana nueva."""
        home.get_by_text('Productos', exact=True).first.click()
        item = home.get_by_text('Autos individual', exact=True).first
        item.wait_for(timeout=8000)
        item.click()
        home.get_by_text('Selecciona la clave').first.click()
        clave = (self.credencial.clave_agencia or '').split(' - ')[0].strip()
        opcion = home.get_by_role('option', name=re.compile(re.escape(clave), re.I)) if clave else home.get_by_role('option')
        opcion.first.click()
        with home.expect_popup(timeout=30000) as popup_info:
            home.get_by_role('button', name=re.compile(r'^Consultar$', re.I)).first.click()
        cotizador = popup_info.value
        cotizador.wait_for_load_state('domcontentloaded')
        cotizador.get_by_text('Nueva cotización').first.wait_for(timeout=40000)
        return cotizador

    def _validacion_datos(self, cot):
        """Paso 1: identificación + tipo y número de placa."""
        cot.get_by_text('Nueva cotización').first.click()
        cot.locator('#id').wait_for(timeout=20000)

        abreviatura = (self.tomador.document_type.abbreviation or '').upper()
        if abreviatura != 'CC':
            # HDI abre en "Cédula de Ciudadanía"; para otros tipos se elige por nombre.
            cot.locator('button[name="idType"]').click()
            nombre_tipo = self.tomador.document_type.name
            opcion = cot.locator('ul li').filter(has_text=_accent_insensitive_pattern(nombre_tipo)).first
            try:
                opcion.click(timeout=4000)
            except PlaywrightTimeoutError:
                raise BotDatosError(
                    f'HDI no ofrece el tipo de documento "{nombre_tipo}" en el cotizador.',
                    accion='Cotice este caso directamente en el portal de HDI; el cotizador automático solo maneja los tipos de documento que ese portal ofrece.',
                )

        tipo_placa = TIPO_PLACA_CERO_KM if self.vehiculo.es_cero_km else TIPO_PLACA_NORMAL
        cot.get_by_text('Tipo de placa').first.click()
        cot.get_by_text(tipo_placa, exact=True).first.click()

        escribir_verificado(cot, cot.locator('#id'), self.tomador.dni, delay=60)
        escribir_verificado(cot, cot.locator('#placa'), self.placa_portal, delay=60)

        validar = cot.get_by_role('button', name=re.compile(r'Validar', re.I)).first
        cot.wait_for_timeout(700)
        if not validar.is_enabled():
            if self.vehiculo.es_cero_km:
                raise BotDatosError(
                    f'HDI no aceptó «{PLACA_CERO_KM}» como número de «Tránsito Libre (Vehículo 0 km)».',
                    accion='HDI rechazó el número de tránsito libre que usa el sistema para los 0 km. Confirme con HDI '
                           'cuál debe usarse y avise a soporte para actualizarlo; mientras tanto cotice este vehículo '
                           'directamente en el portal de HDI.',
                )
            raise BotDatosError(
                f'HDI no aceptó la placa «{self.vehiculo.placa}» (tipo «{tipo_placa}»): '
                '"La información ingresada no corresponde al Tipo de placa".',
                accion='Revise que la placa esté bien escrita en la solicitud y reenvíe a HDI.',
            )
        validar.click()
        cot.get_by_role('button', name=re.compile(r'Sí, confirmar', re.I)).first.click(timeout=20000)

        # El modal de éxito tarda varios segundos. Si no es viable, HDI lo dice
        # en otro modal: se devuelve ese texto en vez de un timeout opaco.
        for _ in range(50):
            cuerpo = cot.evaluate('document.body.innerText')
            if 'fueron validados con éxito' in cuerpo:
                break
            cot.wait_for_timeout(1000)
        else:
            raise BotPortalError(
                'HDI no confirmó la validación de datos (identificación y placa). '
                f'La pantalla decía: «{self._resumen_pantalla(cot)}».'
            )
        cot.get_by_role('button', name=re.compile(r'^Continuar$', re.I)).first.click()

    def _info_vehiculo(self, cot):
        """Paso 2: uso, vehículo (lo resuelve HDI por placa o se busca por
        Fasecolda), preguntas adicionales; se captura todo lo del vehículo."""
        cot.get_by_text('Selecciona el uso del vehículo').first.wait_for(timeout=40000)
        cot.get_by_text('Selecciona el uso del vehículo').first.click()
        cot.get_by_text(USO_VEHICULO, exact=True).first.click()
        casilla = cot.locator('input[type=checkbox]').first
        casilla.check(force=True)
        if not casilla.is_checked():
            raise BotPortalError('No se pudo marcar la declaración del intermediario sobre el uso del vehículo.')

        # Vehículos usados: HDI resuelve el vehículo por la placa y llena el
        # buscador solo. Se decide por si el campo trae valor (con unos
        # segundos de margen), NO por su atributo `disabled`, que se aplica
        # un instante después de cargar el valor (visto en la primera corrida).
        buscador = cot.locator('#fname-vehiculo')
        resuelto = False
        for _ in range(10):
            if buscador.input_value():
                resuelto = True
                break
            cot.wait_for_timeout(1000)
        if not resuelto:
            self._buscar_por_fasecolda(cot, buscador)

        # Valor comercial: si HDI lo deja editable (típico en 0 km) y lo tenemos, se escribe.
        valor = cot.locator('input[name="datosVehiculo.vehicleValue"]')
        if valor.is_enabled() and not valor.input_value() and self.vehiculo.valor_comercial:
            escribir_verificado(cot, valor, f'{int(self.vehiculo.valor_comercial)}')

        self._capturar_vehiculo(cot)
        self._preguntas_adicionales(cot)
        cot.get_by_role('button', name=re.compile(r'^Continuar$', re.I)).first.click(timeout=20000)

    def _fasecolda_disponible(self, cot, timeout=360):
        """Código Fasecolda del vehículo. Si todavía no está en la BD, espera a
        que otra aseguradora cotizando el mismo vehículo lo capture (Qualitas
        y Seguros del Estado lo guardan al leer el vehículo por placa); deja de
        esperar cuando ya no quede ninguna en proceso o se agote el tiempo."""
        from core.policies.models import Cotizacion, Vehiculo  # import local: evita ciclo al cargar el módulo

        limite = time.time() + timeout
        while True:
            with schema_context(self.schema_name):
                codigo = (Vehiculo.objects.filter(pk=self.vehiculo.pk)
                          .values_list('codigo_fasecolda', flat=True).first() or '').strip()
                if codigo:
                    return codigo
                siguen = Cotizacion.objects.filter(
                    vehiculo=self.vehiculo,
                    estado_bot__in=('pendiente', 'en_proceso'),
                    created_at__gte=timezone.now() - timedelta(minutes=20),
                ).exclude(pk=self.cotizacion.pk).exists()
            if not siguen or time.time() > limite:
                return ''
            cot.wait_for_timeout(4000)

    def _buscar_por_fasecolda(self, cot, buscador):
        codigo = self._fasecolda_disponible(cot)
        if not codigo:
            raise BotDatosError(
                f'HDI no reconoció el vehículo de placa «{self.vehiculo.placa}» y no hay código Fasecolda para buscarlo '
                '(ninguna otra aseguradora lo capturó a tiempo).',
                accion='Reenvíe a HDI cuando otra aseguradora (Qualitas) haya leído el vehículo, o registre la '
                       'solicitud con el código Fasecolda y reenvíe.',
            )
        # Una etiqueta superpuesta intercepta los clics sobre este campo: se enfoca directo.
        buscador.focus()
        buscador.press_sequentially(codigo, delay=80)
        cot.wait_for_timeout(2500)
        sin_ceros = codigo.lstrip('0')
        resultados = cot.locator('ul li').filter(has_text=re.compile(re.escape(sin_ceros)))
        try:
            resultados.first.click(timeout=10000)
        except PlaywrightTimeoutError:
            raise BotDatosError(
                f'HDI no encontró ningún vehículo con el código Fasecolda «{codigo}».',
                accion='Verifique el código Fasecolda del vehículo en la solicitud y reenvíe a HDI.',
            )
        cot.wait_for_timeout(1500)

    def _leer(self, cot, nombre):
        try:
            return cot.locator(f'input[name="datosVehiculo.{nombre}"]').input_value(timeout=5000).strip() or None
        except Exception:
            return None

    def _capturar_vehiculo(self, cot):
        """Guarda en Vehiculo todo lo que HDI resolvió. En HDI "Versión" es la
        línea (QASHQAI [2]) y "Tipo" la variante (1.6L 2WD MT...), al revés de
        Qualitas: se mapean a clase y referencia para que ambas aseguradoras
        dejen los datos con el mismo significado."""
        marca = self._leer(cot, 'vehicleMarca')
        modelo = self._leer(cot, 'vehicleModel')
        linea = self._leer(cot, 'vehicleVersion')
        variante = self._leer(cot, 'vehicleType')
        fasecolda = self._leer(cot, 'codeFasecolda')
        valor = self._leer(cot, 'vehicleValue')

        with schema_context(self.schema_name):
            if marca:
                self.vehiculo.marca = marca
            if modelo and modelo.isdigit():
                self._fijar_modelo(modelo)
            if linea:
                self.vehiculo.clase = linea
            if variante:
                self.vehiculo.referencia = variante
            if fasecolda:
                self.vehiculo.codigo_fasecolda = fasecolda
            valor_num = parse_money(valor) if valor else None
            if valor_num:
                self.vehiculo.valor_comercial = valor_num
            self._guardar_vehiculo_cambios()
        self._valor_vehiculo = valor_num

    def _preguntas_adicionales(self, cot):
        """Cuatro preguntas Sí/No (¿0 km?, accesorios, dispositivos de
        seguridad, blindaje). Radios en pares [Sí, No] por pregunta. Para un
        0 km solo la primera va en Sí; si no, todo en No."""
        radios = cot.locator('input[type=radio]')
        total = radios.count()
        for pregunta in range(total // 2):
            si, no = radios.nth(pregunta * 2), radios.nth(pregunta * 2 + 1)
            quiere_si = pregunta == 0 and self.vehiculo.es_cero_km
            objetivo = si if quiere_si else no
            if objetivo.is_checked():
                continue
            if objetivo.is_disabled():
                raise BotDatosError(
                    'HDI tiene bloqueada la respuesta de «¿Tu vehículo es 0 km?» en un valor distinto al de la solicitud '
                    f'(en la solicitud es 0 km: {"Sí" if self.vehiculo.es_cero_km else "No"}).',
                    accion='Corrija en la solicitud si el vehículo es 0 km o no, y reenvíe a HDI.',
                )
            objetivo.check(force=True)

    def _info_personal(self, cot):
        """Paso 3: nombre, género, nacimiento y ciudad. Dinámico: solo se
        llena lo que HDI no trae ya cargado/bloqueado."""
        nombre = cot.locator('input[name="primerNombrePersona"]')
        nombre.wait_for(timeout=40000)
        primer_nombre, primer_apellido = dividir_nombre(self.tomador.names)
        apellido = cot.locator('input[name="primerApellidoPersona"]')
        for campo, valor in ((nombre, primer_nombre), (apellido, primer_apellido)):
            if campo.is_enabled() and not campo.input_value():
                escribir_verificado(cot, campo, valor.capitalize(), delay=60)

        # El <label for> del género está roto (no apunta a ningún input), así
        # que se marca el radio directamente.
        radios_genero = cot.locator('input[type=radio]')
        if not any(radios_genero.nth(i).is_checked() for i in range(radios_genero.count())):
            radios_genero.nth(0 if (self.tomador.gender or 'male') == 'male' else 1).check(force=True)

        nac = self.tomador.birthdate
        for nombre_btn, valor in (('Día', str(nac.day)), ('Mes', MESES[nac.month - 1]), ('Año', str(nac.year))):
            boton = cot.get_by_role('button', name=re.compile(rf'^{nombre_btn}')).first
            if boton.is_disabled():
                continue
            boton.click()
            cot.locator('ul li').filter(has_text=re.compile(rf'^{re.escape(valor)}$')).first.click()
            cot.wait_for_timeout(300)

        self._ciudad_movilizacion(cot)
        cot.wait_for_timeout(1500)

        # Etiqueta del descuento que muestra HDI ("0% OFF", "30% OFF"...).
        cuerpo = cot.evaluate('document.body.innerText')
        coincidencia = re.search(r'(\d+(?:[.,]\d+)?)\s*%\s*OFF', cuerpo, re.I)
        if coincidencia:
            with schema_context(self.schema_name):
                self.cotizacion.porcentaje_descuento = coincidencia.group(1).replace(',', '.')
                self.cotizacion.save(update_fields=['porcentaje_descuento'])

        continuar = cot.get_by_role('button', name=re.compile(r'^Continuar$', re.I)).first
        try:
            continuar.click(timeout=20000)
        except PlaywrightTimeoutError:
            raise BotDatosError(
                'HDI dejó deshabilitado «Continuar» en Información personal: falta o es inválido algún dato obligatorio '
                f'(nombre «{primer_nombre} {primer_apellido}», nacimiento {nac:%d/%m/%Y}, ciudad «{self.vehiculo.zona_circulacion}»).',
                accion='Revise el nombre, la fecha de nacimiento y la ciudad en la solicitud y reenvíe a HDI.',
            )

    def _ciudad_movilizacion(self, cot):
        campo = cot.locator('input[name="city"]')
        if not campo.is_enabled() or campo.input_value():
            return
        municipio = self.vehiculo.zona_circulacion
        campo.click()
        campo.press_sequentially(municipio.nombre, delay=90)
        cot.wait_for_timeout(2500)
        depto_n, mun_n = normalizar_texto(municipio.departamento.nombre), normalizar_texto(municipio.nombre)
        sugerencias = cot.locator('button').filter(has_text=_accent_insensitive_pattern(municipio.nombre[:5]))
        textos = [t.strip() for t in sugerencias.all_inner_texts()]
        elegido = None
        for i, texto in enumerate(textos):
            normal = normalizar_texto(texto)
            if mun_n in normal and depto_n in normal:
                elegido = i
                break
        if elegido is None:
            for i, texto in enumerate(textos):
                if mun_n in normalizar_texto(texto):
                    elegido = i
                    break
        if elegido is None:
            raise BotDatosError(
                f'HDI no ofreció la ciudad «{municipio}» en «Ciudad de movilización» (sugerencias: {", ".join(textos) or "ninguna"}).',
                accion='Revise la ciudad de circulación de la solicitud y reenvíe a HDI.',
            )
        sugerencias.nth(elegido).click()

    def _capturar_cotizacion(self, cot):
        """Paso 4: valores de los paquetes. El Premium es la prima_total."""
        # No se espera a ciegas: cada segundo se revisa si ya salieron los paquetes
        # o si HDI mostró un aviso, para explicar el motivo en vez de un timeout opaco.
        for _ in range(90):
            if cot.get_by_text('PREMIUM', exact=True).count():
                break
            alerta = cot.evaluate(
                """() => { const m = [...document.querySelectorAll('.modal.show,[role=dialog]')]
                    .find(e => e.getBoundingClientRect().width > 0 && (e.innerText || '').trim());
                    return m ? m.innerText : null; }""")
            if alerta:
                raise BotPortalError(f'HDI mostró un aviso en lugar de los paquetes: «{" ".join(alerta.split())[:300]}».')
            cot.wait_for_timeout(1000)
        else:
            raise BotPortalError(
                'HDI no mostró los paquetes cotizados después de 90 segundos. '
                f'La pantalla decía: «{self._resumen_pantalla(cot)}».'
            )
        cot.wait_for_timeout(1500)
        cuerpo = cot.evaluate('document.body.innerText')
        paquetes = re.findall(r'^\s*([A-ZÁÉÍÓÚÑ][A-ZÁÉÍÓÚÑ ]{2,})\s*\n\s*\$\s*([\d\'.,]+)\s*\n\s*Financiaci', cuerpo, re.M)
        if not paquetes:
            raise BotPortalError(f'No se pudieron leer los paquetes cotizados de HDI. La pantalla decía: «{self._resumen_pantalla(cot)}».')

        from core.policies.models import CotizacionPlan  # import local: evita ciclo al cargar el módulo

        numero = re.search(r'Cotización\s*\n\s*(\d{6,})', cuerpo)
        premium = None
        with schema_context(self.schema_name):
            self.cotizacion.planes.all().delete()
            for nombre, valor in paquetes:
                prima = parse_money(valor)
                CotizacionPlan.objects.create(cotizacion=self.cotizacion, nombre_plan=nombre.strip().title(), prima_total=prima)
                if nombre.strip().upper() == 'PREMIUM':
                    premium = prima
            if premium is None:
                raise BotPortalError('HDI cotizó, pero ninguno de los paquetes es «Premium», así que no hay prima Premium que guardar.')
            self.cotizacion.prima_total = premium
            if getattr(self, '_valor_vehiculo', None):
                self.cotizacion.valor_asegurado = self._valor_vehiculo
            self.cotizacion.moneda = 'Pesos'
            self.cotizacion.mensaje_bot = f'Cotización HDI Nº {numero.group(1)}' if numero else None
            self.cotizacion.save()

    @staticmethod
    def _resumen_pantalla(cot):
        try:
            return re.sub(r'\s+', ' ', cot.evaluate('document.body.innerText'))[-400:]
        except Exception:
            return '(no disponible)'
