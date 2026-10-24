import logging
import re
import time
from decimal import Decimal, InvalidOperation

from django.utils import timezone
from django_tenants.utils import schema_context
from playwright.sync_api import TimeoutError as PlaywrightTimeoutError

logger = logging.getLogger(__name__)

_ACCENT_GROUPS = ('aáàäâ', 'eéèëê', 'iíìïî', 'oóòöô', 'uúùüû', 'nñ')
# Mapea CADA variante (con o sin tilde) a la clase completa del grupo, para
# que dé igual si el texto de origen ya trae tilde o no.
_ACCENT_MAP = {variante: f'[{grupo}]' for grupo in _ACCENT_GROUPS for variante in grupo}


def _accent_insensitive_pattern(text):
    """Construye un patrón regex que ignora tildes además de mayúsculas.

    El portal es inconsistente con las tildes (ej. 'AUTOMOVILES' sin tilde,
    'Ubicación' con tilde), así que buscar el texto tal cual como lo tenemos
    guardado en nuestra base de datos falla con demasiada frecuencia.
    """
    partes = []
    for ch in text:
        lower = ch.lower()
        if lower in _ACCENT_MAP:
            partes.append(_ACCENT_MAP[lower])
        else:
            partes.append(re.escape(ch))
    return re.compile(''.join(partes), re.IGNORECASE)


class BotCancelado(Exception):
    """El asesor eligió cancelar en un punto de confirmación del bot."""
    pass


class BotTimeout(Exception):
    """El bot esperó una confirmación del asesor y nadie respondió a tiempo."""
    pass


def normalizar_texto(texto):
    """Minúsculas y sin tildes, para comparar nombres/opciones entre sistemas."""
    import unicodedata
    sin_tildes = unicodedata.normalize('NFD', texto or '')
    return ''.join(c for c in sin_tildes if unicodedata.category(c) != 'Mn').lower().strip()


PASO_LOGIN = 'Inicio de sesión'


def dividir_nombre(nombre_completo):
    """(primer nombre, primer apellido) a partir de un nombre completo.

    Los portales solo piden esos dos datos. Con 2 palabras: nombre + apellido. Con 4 o
    más (2 nombres + 2 apellidos) el primer apellido es la 3ª palabra. Con 3
    es ambiguo (1 nombre + 2 apellidos, o 2 nombres + 1 apellido); para
    cotizar no es crítico y se asume 1 nombre + 2 apellidos."""
    partes = (nombre_completo or '').split()
    if not partes:
        return '', ''
    if len(partes) == 1:
        return partes[0], partes[0]
    if len(partes) == 2:
        return partes[0], partes[1]
    if len(partes) == 3:
        return partes[0], partes[1]
    return partes[0], partes[2]


class BotError(Exception):
    """Falla ya entendida por el bot: lleva el mensaje para el asesor y qué
    debe hacer. Las subclases fijan el tipo (ver Cotizacion.error_tipo)."""
    tipo = 'inesperado'

    def __init__(self, mensaje, accion=None):
        super().__init__(mensaje)
        self.mensaje = mensaje
        self.accion = accion


class BotAutenticacionError(BotError):
    """No se pudo iniciar sesión (credenciales, cuenta bloqueada, sin credencial configurada)."""
    tipo = 'autenticacion'


class BotDatosError(BotError):
    """Un dato de la solicitud fue rechazado por el portal o falta para poder cotizar."""
    tipo = 'datos'


class BotPortalError(BotError):
    """El portal rechazó, bloqueó o no mostró lo esperado (ej. vehículo no asegurable)."""
    tipo = 'portal'


class BotNoCotizableError(BotError):
    """La aseguradora no cotiza este caso por una regla suya (ej. el vehículo ya está
    asegurado con ella, modelo no admitido). No es una falla: reenviar no cambia el resultado."""
    tipo = 'no_cotizable'


class BotSaturadoError(BotError):
    """El portal avisa que tiene demasiadas consultas («intenta más tarde»). No es un dato ni una regla de la
    aseguradora: es transitorio, se muestra como alerta naranja y se puede reenviar más tarde."""
    tipo = 'saturado'


class BotClaveVencidaError(BotError):
    """El portal pide cambiar la contraseña (vencida o de cambio obligatorio). El bot no puede seguir: hay que
    cambiarla a mano en el portal y actualizarla en el sistema. Reintentar antes solo arriesga bloquear la cuenta."""
    tipo = 'clave_vencida'


ACCION_POR_TIPO = {
    'autenticacion': 'Verifique el usuario y la contraseña de {aseguradora} en las credenciales y que la cuenta no esté '
                     'bloqueada; luego reenvíe la solicitud a {aseguradora}.',
    'timeout': 'Reenvíe la solicitud a {aseguradora}. Si vuelve a fallar en el mismo paso, cotice a mano en su portal '
               'y avise a soporte.',
    'datos': 'Corrija el dato indicado en la solicitud y reenvíe a {aseguradora}.',
    'portal': 'Revise el caso directamente en el portal de {aseguradora}. Si ahí tampoco permite cotizar este '
              'vehículo o persona, esta aseguradora no cotizará.',
    'interrumpida': 'Reenvíe la solicitud a {aseguradora}.',
    'no_cotizable': '{aseguradora} no cotiza este caso: no hace falta reenviar. Cotice con otra aseguradora o gestione '
                    'el caso directamente con {aseguradora}.',
    'saturado': '{aseguradora} tiene demasiadas consultas en este momento. Espere unos minutos y use «Reenviar a '
                '{aseguradora}»; no hace falta corregir ningún dato.',
    'clave_vencida': 'Entre al portal de {aseguradora}, cambie la contraseña y actualícela en Aseguradoras › Editar '
                     '(campo Contraseña). Cuando la guarde podrá reenviar la solicitud.',
    'inesperado': 'Reenvíe la solicitud a {aseguradora}. Si se repite, avise a soporte: el detalle técnico quedó guardado.',
}

# Pistas por (aseguradora, paso) para timeouts cuyo motivo ya se conoce de pruebas reales.
PISTAS_PASO = {
    ('Qualitas', 'Datos del vehículo'): 'Qualitas no deja avanzar si ya tiene una cotización pendiente para esta '
                                         'placa o si no reconoce el vehículo.',
    ('HDI', 'Cotización (paquetes)'): 'HDI no mostró los paquetes a tiempo: el vehículo puede no ser asegurable '
                                       'o el portal estar lento.',
}


def _limpiar_alerta(texto):
    """Quita el 'Aviso' inicial y el botón final (Salir/Aceptar...) del texto de un modal."""
    texto = re.sub(r'\s+', ' ', texto or '').strip()
    texto = re.sub(r'^(Aviso|Alerta|Atención|Error)\s+', '', texto, flags=re.I)
    texto = re.sub(r'\s+(Salir|Aceptar|Cerrar|Entendido|Ok)$', '', texto, flags=re.I)
    return texto.strip()


# Fragmentos (sin tildes ni mayúsculas) de avisos de portal que significan «este vehículo ya está asegurado».
AVISOS_NO_COTIZABLE = ('ya contar con este vehiculo asegurado', 'poliza vigente')


# Frases (sin tildes ni mayúsculas) con que los portales avisan que la contraseña venció o debe cambiarse. No se
# conocen los textos exactos de cada aseguradora, así que son amplias en la forma pero siempre hablan de la
# contraseña/clave: un simple enlace «¿olvidó su contraseña?» del login no coincide con ninguna.
_CLAVE = r'(?:contrasena|clave|password)'
PATRONES_CLAVE_VENCIDA = tuple(re.compile(p) for p in (
    # «Su contraseña ha expirado», «clave vencida»…  (no «sesión expirada»: eso es otra cosa)
    rf'\b{_CLAVE}\b[^.]{{0,25}}\b(?:ha\s+|esta\s+|se\s+)?(?:expirad|vencid|caducad|expiro|vencio|caduco)',
    # «Se venció su contraseña», «expiró la clave»
    rf'\b(?:expirad\w+|vencid\w+|caducad\w+|expiro|vencio|caduco)\s+(?:su\s+|tu\s+|la\s+)?{_CLAVE}\b',
    # «Debe cambiar su contraseña», «es necesario actualizar la clave»
    rf'\b(?:debe|debes|tiene que|tienes que|necesita|necesitas|requiere|es necesario|es obligatorio)\b[^.]{{0,30}}'
    rf'\b(?:cambiar|actualizar|renovar|restablecer|modificar|establecer)\b[^.]{{0,25}}\b{_CLAVE}\b',
    rf'\b(?:cambio|actualizacion|renovacion|restablecimiento)\s+(?:obligatori\w+|forzos\w+)\s+de\s+(?:la\s+|su\s+|tu\s+)?{_CLAVE}\b',
    rf'\b(?:cambio|actualizacion|renovacion)\s+de\s+{_CLAVE}\s+(?:obligatori\w+|requerid\w+|pendiente)',
    rf'\b{_CLAVE}\s+(?:temporal|provisional|por defecto|inicial)\b[^.]{{0,40}}\b(?:cambi|actualiz)',
    rf'\bformulario de cambio de {_CLAVE}\b',
))


def pide_cambio_de_clave(*textos):
    """Si alguno de los textos (excepción, aviso o pantalla del portal) dice que hay que cambiar la contraseña,
    devuelve el fragmento donde lo dice (para mostrárselo al asesor); si no, None."""
    for texto in textos:
        if not texto:
            continue
        original = re.sub(r'\s+', ' ', str(texto)).strip()
        normal = normalizar_texto(original)  # misma longitud: quitar tildes no cambia las posiciones
        for patron in PATRONES_CLAVE_VENCIDA:
            m = patron.search(normal)
            if m:
                return original[max(0, m.start() - 40):m.end() + 60].strip()
    return None


def exigir_clave_al_dia(credencial, aseguradora):
    """Para el constructor de cada bot: si ya se detectó que el portal pide cambiar la contraseña, no se intenta
    entrar (evita bloquear la cuenta) hasta que la contraseña se actualice en el sistema."""
    if credencial is not None and credencial.requiere_cambio_clave:
        raise BotClaveVencidaError(
            f'{aseguradora} pidió cambiar la contraseña y todavía no se ha actualizado en el sistema. '
            'No se intentó entrar al portal para no arriesgar el bloqueo de la cuenta.')


def marcar_clave_vencida(aseguradora):
    """Deja marcada la credencial activa de la aseguradora: los bots dejan de intentar hasta que se actualice."""
    credencial = aseguradora.credenciales.filter(is_active=True).order_by('-id').first()
    if credencial is not None and not credencial.requiere_cambio_clave:
        credencial.requiere_cambio_clave = True
        credencial.cambio_clave_detectado_en = timezone.now()
        credencial.save(update_fields=['requiere_cambio_clave', 'cambio_clave_detectado_en'])


def clasificar_error(exc, aseguradora, paso, alerta=None, pantalla=None):
    """Convierte una excepción del bot en lo que necesita el asesor:
    {tipo, mensaje, accion, detalle}. `alerta` es el texto del aviso (modal)
    que el portal tenía abierto al fallar, si lo hubo; `pantalla` es lo que
    mostraba, para el detalle técnico."""
    paso_txt = paso or 'inicio'
    detalle = f'{type(exc).__name__}: {exc}'[:3500]
    if pantalla:
        detalle += f'\n\nPantalla del portal al fallar:\n{pantalla[-600:]}'

    fragmento = None if isinstance(exc, BotClaveVencidaError) else pide_cambio_de_clave(exc, alerta, pantalla)
    if fragmento:
        # El portal pide cambiar la contraseña (suele verse como un timeout o «no se pudo iniciar sesión»).
        tipo = 'clave_vencida'
        mensaje = (f'{aseguradora} parece estar pidiendo cambiar la contraseña, por eso no se pudo continuar. '
                   f'El portal dice: «…{fragmento}…».')
        accion = None
    elif isinstance(exc, BotError):
        tipo, mensaje, accion = exc.tipo, exc.mensaje, exc.accion
    elif isinstance(exc, PlaywrightTimeoutError):
        if paso == PASO_LOGIN:
            tipo = 'autenticacion'
            mensaje = f'No se pudo iniciar sesión en {aseguradora}: el portal no mostró la pantalla principal tras ingresar.'
            accion = None
        elif alerta and any(f in normalizar_texto(alerta) for f in AVISOS_NO_COTIZABLE):
            # El portal dice que el vehículo ya está asegurado: no es una falla, esa aseguradora no cotiza el caso.
            tipo = 'no_cotizable'
            mensaje = f'{aseguradora} no cotiza este vehículo: «{_limpiar_alerta(alerta).rstrip(".")}».'
            accion = None
        elif alerta:
            tipo = 'portal'
            mensaje = f'{aseguradora} mostró un aviso en el paso «{paso_txt}»: «{_limpiar_alerta(alerta).rstrip(".")}».'
            accion = None
        else:
            tipo = 'timeout'
            mensaje = f'{aseguradora} no respondió a tiempo en el paso «{paso_txt}».'
            pista = PISTAS_PASO.get((aseguradora, paso))
            if pista:
                mensaje += f' {pista}'
            accion = None
    else:
        tipo = 'inesperado'
        mensaje = f'Falla interna del bot en el paso «{paso_txt}»: {str(exc).strip()[:300]}'
        accion = None

    if not accion:
        accion = ACCION_POR_TIPO[tipo].format(aseguradora=aseguradora)
    return {'tipo': tipo, 'mensaje': mensaje, 'accion': accion, 'detalle': detalle}


def registrar_error(cotizacion, exc, paso, schema_name, alerta=None, pantalla=None):
    """Guarda en la cotización el error ya clasificado (estado 'error')."""
    info = clasificar_error(exc, str(cotizacion.aseguradora), paso, alerta=alerta, pantalla=pantalla)
    with schema_context(schema_name):
        if info['tipo'] == 'clave_vencida':
            marcar_clave_vencida(cotizacion.aseguradora)
        cotizacion.estado_bot = 'error'
        cotizacion.error_tipo = info['tipo']
        cotizacion.paso_bot = paso
        cotizacion.mensaje_bot = info['mensaje']
        cotizacion.accion_sugerida = info['accion']
        cotizacion.detalle_tecnico = info['detalle']
        cotizacion.save(update_fields=['estado_bot', 'error_tipo', 'paso_bot', 'mensaje_bot', 'accion_sugerida', 'detalle_tecnico'])
    return info


# Un 0 km no tiene placa: en TODOS los portales se escribe siempre esta (no la de la solicitud).
PLACA_CERO_KM = 'TL123A'


class RegistroErrorMixin:
    """Para los bots: guarda el paso en curso (visible en vivo en la pantalla de
    proceso) y registra los errores clasificados. Requiere self.cotizacion y
    self.schema_name."""
    paso_actual = None
    ultima_alerta = None
    ultima_pantalla = None

    # Quién manda sobre el MODELO del vehículo (año). Los portales no coinciden entre sí (cada uno lo deduce a su
    # manera: línea de Fasecolda, base propia…) y el modelo cambia el valor asegurado y la prima. Mundial lo valida
    # contra el RUNT con la placa (si está mal, rechaza); La Equidad lo lee por placa. Los demás solo lo completan si
    # el vehículo aún no tiene modelo y nunca pisan el de una fuente de mayor prioridad.
    PRIORIDAD_MODELO = {'Seguros Mundial': 3, 'La Equidad Seguros': 2}

    def _prioridad_modelo(self, fuente):
        return self.PRIORIDAD_MODELO.get(fuente, 1) if fuente else 0

    def _fijar_modelo(self, modelo):
        """Registra el modelo que leyó este bot SOLO si le corresponde: decide con lo que hay en la BD en este
        instante (otro bot pudo fijarlo mientras este corría con una copia vieja del vehículo) y deja el modelo
        vigente en `self.vehiculo` para el resto del proceso."""
        from core.policies.models import Vehiculo  # import local: evita ciclo al cargar el módulo
        try:
            modelo = int(re.sub(r'\D', '', str(modelo or ''))[:4])
        except ValueError:
            return
        if not modelo:
            return
        fuente = self.cotizacion.aseguradora.name
        with schema_context(self.schema_name):
            actual = Vehiculo.objects.filter(pk=self.vehiculo.pk).values('modelo', 'modelo_fuente').first() or {}
            mia, previa = self._prioridad_modelo(fuente), self._prioridad_modelo(actual.get('modelo_fuente'))
            # Puede fijarlo si no hay modelo, si su fuente pesa más, o si es una fuente prioritaria que se actualiza.
            if not actual.get('modelo') or mia > previa or (mia == previa and mia >= 2):
                Vehiculo.objects.filter(pk=self.vehiculo.pk).update(modelo=modelo, modelo_fuente=fuente)
                vigente, vigente_fuente = modelo, fuente
            else:
                vigente, vigente_fuente = actual['modelo'], actual.get('modelo_fuente')
        self.vehiculo.modelo = vigente
        self.vehiculo.modelo_fuente = vigente_fuente
        if hasattr(self, '_vehiculo_inicial'):
            self._vehiculo_inicial['modelo'] = vigente  # ya quedó guardado: no se vuelve a escribir con la copia vieja

    def _modelo_vigente(self):
        """Modelo del vehículo según la BD ahora mismo (puede haberlo fijado otro bot después de arrancar este)."""
        from core.policies.models import Vehiculo  # import local: evita ciclo al cargar el módulo
        with schema_context(self.schema_name):
            modelo = Vehiculo.objects.filter(pk=self.vehiculo.pk).values_list('modelo', flat=True).first()
        if modelo:
            self.vehiculo.modelo = modelo
        return modelo

    @property
    def placa_portal(self):
        """Placa que se escribe en el portal de la aseguradora: la real, o `PLACA_CERO_KM` si es 0 km."""
        return PLACA_CERO_KM if self.vehiculo.es_cero_km else self.vehiculo.placa

    def _paso(self, nombre):
        self.paso_actual = nombre
        try:
            with schema_context(self.schema_name):
                self.cotizacion.paso_bot = nombre
                self.cotizacion.save(update_fields=['paso_bot'])
        except Exception:
            logger.warning('No se pudo guardar el paso en curso del bot.', exc_info=True)

    def _guardar_pantalla(self, page):
        """Antes de cerrar el navegador: guarda el aviso (modal) visible y un
        extracto de lo que mostraba el portal, para explicar la falla."""
        try:
            self.ultima_alerta = page.evaluate(
                """() => { const m = [...document.querySelectorAll('.modal.show,[role=dialog]')]
                    .find(e => e.getBoundingClientRect().width > 0 && (e.innerText || '').trim());
                    return m ? m.innerText : null; }"""
            )
            cuerpo = page.evaluate('document.body.innerText') or ''
            self.ultima_pantalla = re.sub(r'\s+', ' ', cuerpo)[-4000:]
            # Una pantalla con «nueva contraseña» + «confirmar» y dos campos de clave es el cambio obligatorio.
            campos_clave = page.evaluate(
                """() => [...document.querySelectorAll('input[type=password]')]
                    .filter(e => e.getBoundingClientRect().width > 0).length""")
            normal = normalizar_texto(cuerpo)
            if campos_clave >= 2 and re.search(r'nueva\s+(contrasena|clave)', normal) and re.search(r'confirm|repit', normal):
                self.ultima_pantalla = 'Formulario de cambio de contraseña visible. ' + self.ultima_pantalla
        except Exception:
            pass

    def _esperar_al_asesor(self, tipo, mensaje, timeout=300, listo=None, intervalo=1.0):
        """Pausa el bot (sin cerrar el navegador) hasta que una persona haga lo que el bot no puede: ver
        `Cotizacion.verificacion_bot`.

        - tipo 'codigo': devuelve el código que el asesor escribió en la modal de la plataforma.
        - tipo 'captcha': el asesor lo resuelve en la ventana del portal; `listo()` dice cuándo ya está hecho.
        Si el asesor cancela lanza BotCancelado; si pasa `timeout` segundos, BotTimeout. El código no queda guardado.
        """
        from core.policies.models import Cotizacion  # import local: evita ciclo al cargar el módulo

        with schema_context(self.schema_name):
            Cotizacion.objects.filter(pk=self.cotizacion.pk).update(
                estado_bot='esperando_confirmacion', mensaje_bot=mensaje, verificacion_bot=tipo,
                confirmacion_bot=None, codigo_verificacion=None)
        try:
            limite = time.time() + timeout
            while time.time() < limite:
                with schema_context(self.schema_name):
                    fila = Cotizacion.objects.filter(pk=self.cotizacion.pk).values('confirmacion_bot', 'codigo_verificacion').first() or {}
                if fila.get('confirmacion_bot') is False:
                    raise BotCancelado()
                if tipo == 'codigo' and fila.get('codigo_verificacion'):
                    return fila['codigo_verificacion']
                if listo is not None and listo():
                    return True
                time.sleep(intervalo)
            raise BotTimeout()
        finally:
            with schema_context(self.schema_name):
                Cotizacion.objects.filter(pk=self.cotizacion.pk, estado_bot='esperando_confirmacion').update(
                    estado_bot='en_proceso', verificacion_bot=None, codigo_verificacion=None)

    def _registrar_error(self, exc):
        return registrar_error(self.cotizacion, exc, self.paso_actual, self.schema_name,
                               alerta=self.ultima_alerta, pantalla=self.ultima_pantalla)

    # Campos del vehículo que los bots capturan de los portales. Varios bots corren a la vez
    # sobre el mismo vehículo: guardar el objeto completo con la copia en memoria (cargada al
    # arrancar) borraría lo que otra aseguradora capturó mientras tanto. Por eso cada bot
    # guarda SOLO los campos que él mismo cambió.
    CAMPOS_VEHICULO_CAPTURADOS = ('marca', 'modelo', 'referencia', 'clase', 'servicio', 'codigo_fasecolda',
                                  'valor_comercial', 'chasis', 'valor_accesorios', 'tipo_vehiculo', 'color', 'motor',
                                  'serie', 'combustible')

    def _foto_vehiculo(self):
        """Recuerda cómo estaba el vehículo al arrancar el bot (llamar en __init__)."""
        self._vehiculo_inicial = {c: getattr(self.vehiculo, c) for c in self.CAMPOS_VEHICULO_CAPTURADOS}

    def _guardar_vehiculo_cambios(self):
        """Guarda en la BD solo los campos del vehículo que este bot cambió."""
        cambiados = [c for c in self.CAMPOS_VEHICULO_CAPTURADOS
                     if getattr(self.vehiculo, c) != self._vehiculo_inicial[c]]
        if not cambiados:
            return
        with schema_context(self.schema_name):
            self.vehiculo.save(update_fields=cambiados)
        self._vehiculo_inicial.update({c: getattr(self.vehiculo, c) for c in cambiados})


def parse_money(texto):
    """Convierte un valor monetario mostrado en el portal (ej. '$ 45.000.000,00')
    a Decimal. Devuelve Decimal('0') si no logra interpretarlo."""
    if texto is None:
        return Decimal('0')
    limpio = re.sub(r'[^\d,.-]', '', str(texto)).strip()
    if not limpio:
        return Decimal('0')
    # Formato colombiano: '.' separador de miles, ',' decimales.
    if ',' in limpio and '.' in limpio:
        limpio = limpio.replace('.', '').replace(',', '.')
    elif ',' in limpio:
        limpio = limpio.replace(',', '.')
    else:
        # Solo puntos: si el último grupo tiene 3 dígitos asumimos que son
        # separadores de miles (ej. '45.000.000'), no decimales.
        partes = limpio.split('.')
        if len(partes) > 1 and len(partes[-1]) == 3:
            limpio = limpio.replace('.', '')
    try:
        return Decimal(limpio)
    except InvalidOperation:
        return Decimal('0')


def click_by_text(page, text, role=None, timeout=10000, exact=False):
    """Intenta hacer clic en un elemento identificado por su texto visible.

    El portal no nos dio selectores CSS/IDs reales (no se inspeccionó su HTML
    por política de manejo de credenciales), así que se prioriza texto visible
    sobre selectores frágiles. Si esto falla en la primera corrida real, es la
    primera línea a revisar.
    """
    if role:
        name = text if exact else _accent_insensitive_pattern(text)
        locator = page.get_by_role(role, name=name, exact=exact)
    elif exact:
        locator = page.get_by_text(text, exact=True)
    else:
        locator = page.get_by_text(_accent_insensitive_pattern(text))
    locator.first.wait_for(timeout=timeout)
    # click() por defecto usa el timeout global de Playwright (30s) si no se
    # le pasa uno explícito — visto en corrida real que un modal "cargando"
    # legítimo (no un popup informativo a cerrar) puede tardar más de 30s en
    # desaparecer y bloquear el clic todo ese tiempo sin que el `timeout` de
    # esta función tuviera ningún efecto sobre esa espera.
    locator.first.click(timeout=timeout)


def click_select(page, label_text, option_text, timeout=10000):
    """Abre y elige una opción en un combo tipo Material-UI Select.

    En estos combos el texto de la etiqueta (ej. "Ramo") es solo un <label>
    flotante decorativo; el elemento clickeable real es un
    div[role="button"][aria-haspopup="listbox"] que queda superpuesto encima,
    por lo que hacer clic directo en el label falla ("intercepts pointer
    events"). Se toma el primer botón de ese tipo que aparece DESPUÉS del
    label en el documento (no "en cualquier ancestro común", que puede
    terminar agarrando el combo de un campo vecino cuando varios comparten
    un contenedor, ej. una fila con Ramo/Tipo de Seguro/Sucursal).
    """
    label = page.get_by_text(_accent_insensitive_pattern(label_text)).and_(page.locator(':visible')).first
    label.wait_for(timeout=timeout)
    trigger = label.locator(
        'xpath=following::*[@role="button" and @aria-haspopup="listbox"][1]'
    ).first
    trigger.click(timeout=timeout)
    click_by_text(page, option_text, role='option', timeout=timeout)


def esperar_algun_visible(page, text, timeout=20000):
    """Como wait_visible, pero a prueba de copias ocultas del mismo texto
    montadas en otra parte del documento (esta app suele premontar pasos del
    wizard todavía no visitados, ocultos) — filtra primero a elementos que
    YA están visibles antes de tomar ".first", en vez de arriesgarse a que
    ".first" caiga en una copia oculta que nunca se muestre mientras la
    visible real queda más adelante en el documento."""
    marcador = page.get_by_text(_accent_insensitive_pattern(text)).and_(page.locator(':visible'))
    marcador.first.wait_for(timeout=timeout, state='visible')


def wait_visible(page, text, timeout=20000):
    """Espera a que aparezca un texto en pantalla. Se usa en vez de
    `wait_for_load_state('networkidle')` porque esta app tiene actividad de
    red de fondo constante (gráficas, notificaciones) que nunca la deja
    "quieta" — esperar la red nunca terminaría."""
    page.get_by_text(_accent_insensitive_pattern(text)).first.wait_for(timeout=timeout)


def close_icon_popup(page, timeout=4000):
    """Cierra una ventana/modal informativa que no tiene texto identificable,
    solo un ícono de "X". Best-effort: si no aparece ninguna, no falla.

    La búsqueda del botón se acota al modal VISIBLE (algunas apps mantienen
    varios modales en el DOM a la vez, ocultos, y buscar ".close" sin acotar
    puede encontrar el de uno que ni siquiera está en pantalla). Si no se
    identifica un botón con clase/atributo reconocible, como último recurso
    hace clic en la esquina superior derecha del modal, donde casi siempre
    está la "X" aunque no tenga marcado semántico.

    Devuelve True si cerró algo, False si no encontró ningún modal visible.
    """
    try:
        modal = page.locator(
            '.modal.show:visible, .modal.in:visible, [role="dialog"][aria-modal="true"]:visible'
        ).first
        modal.wait_for(timeout=timeout, state='visible')
    except PlaywrightTimeoutError:
        return False

    try:
        import os
        from django.conf import settings
        debug_dir = os.path.join(settings.MEDIA_ROOT, 'bot_debug')
        os.makedirs(debug_dir, exist_ok=True)
        html = modal.evaluate('el => el.outerHTML.slice(0, 4000)')
        with open(os.path.join(debug_dir, 'modal_detectado.html'), 'w', encoding='utf-8') as f:
            f.write(html)
    except Exception:
        pass

    candidatos = (
        'button.close',
        '.close',
        '[data-dismiss="modal"]',
        '[data-bs-dismiss="modal"]',
        'button[aria-label="Close" i]',
        'button[aria-label*="cerrar" i]',
    )
    for selector in candidatos:
        try:
            boton = modal.locator(selector).first
            boton.wait_for(timeout=1500, state='visible')
            boton.click(timeout=1500)
            remove_stray_backdrops(page)
            return True
        except PlaywrightTimeoutError:
            continue

    try:
        import os
        from django.conf import settings
        debug_dir = os.path.join(settings.MEDIA_ROOT, 'bot_debug')
        os.makedirs(debug_dir, exist_ok=True)
        html = modal.evaluate('el => el.outerHTML.slice(0, 3000)')
        with open(os.path.join(debug_dir, 'modal_sin_cerrar.html'), 'w', encoding='utf-8') as f:
            f.write(html)
    except Exception:
        pass

    try:
        box = modal.bounding_box()
        if box:
            page.mouse.click(box['x'] + box['width'] - 20, box['y'] + 20)
            remove_stray_backdrops(page)
            return True
    except Exception:
        pass
    return False


def remove_stray_backdrops(page):
    """Elimina cualquier backdrop de modal que quede bloqueando clics en toda
    la página ("intercepts pointer events"). Visto en corrida real: el
    fallback de cierre por clic en la esquina (ver close_known_modals) no
    siempre dispara la limpieza que Bootstrap hace al cerrar un modal
    "oficialmente", dejando el backdrop atrás — incluso cuando ya no hay
    ningún modal realmente visible bloqueando. Se quita sin condición (en
    los puntos donde se llama, ya se cerraron los modales que nos importan)
    en vez de intentar adivinar si "cuenta" como huérfano. Best-effort:
    nunca lanza excepción."""
    try:
        page.evaluate("document.querySelectorAll('.modal-backdrop').forEach(el => el.remove())")
        page.evaluate("document.body.classList.remove('modal-open')")
    except Exception:
        pass


def close_known_modals(page, modal_ids, timeout=2000):
    """Cierra, uno por uno, cualquier modal de esta lista de IDs conocidos
    que esté visible. A diferencia de close_icon_popup (que busca "el primer
    modal visible" con un selector genérico), esto evita agarrar por error
    un modal distinto al que realmente está bloqueando — en apps que
    mantienen varios modales montados a la vez, ".first" no es confiable.
    Devuelve True si cerró al menos uno."""
    cerrado_alguno = False
    for modal_id in modal_ids:
        modal = page.locator(f'#{modal_id}')
        try:
            modal.wait_for(timeout=timeout, state='visible')
        except PlaywrightTimeoutError:
            continue

        cerrado = False
        for selector in ('button.close', '[data-dismiss="modal"]', '[data-bs-dismiss="modal"]'):
            try:
                boton = modal.locator(selector).first
                boton.wait_for(timeout=1000, state='visible')
                boton.click(timeout=1000)
                cerrado = True
                break
            except PlaywrightTimeoutError:
                continue
        if not cerrado:
            try:
                box = modal.bounding_box()
                if box:
                    page.mouse.click(box['x'] + box['width'] - 20, box['y'] + 20)
                    cerrado = True
            except Exception:
                pass
        cerrado_alguno = cerrado_alguno or cerrado
    if cerrado_alguno:
        remove_stray_backdrops(page)
    return cerrado_alguno


def click_resilient(page, text, modal_ids, role=None, timeout=8000, intentos=4):
    """Como click_by_text, pero si el clic falla porque un modal lo
    intercepta, intenta cerrar los modales conocidos y reintenta.

    Se usa en vez de "cerrar todo antes y ya" porque estos modales a veces
    aparecen con un JS diferido cuyo momento exacto no es predecible — un
    solo intento de cierre con tiempo fijo antes del clic puede correr
    demasiado pronto (el modal aún no existe) o demasiado tarde.
    """
    ultimo_error = None
    for _ in range(intentos):
        try:
            click_by_text(page, text, role=role, timeout=timeout)
            return
        except PlaywrightTimeoutError as e:
            ultimo_error = e
            close_known_modals(page, modal_ids, timeout=2000)
    raise ultimo_error


def check_option(page, label_text, timeout=8000):
    """Marca un checkbox identificado por su texto visible (ej. "Pérdida de
    llaves"). Intenta por accesibilidad (get_by_label) y, si no hay una
    asociación real <label for>, hace clic sobre el propio texto (patrón
    común: el checkbox y su texto comparten el mismo contenedor clickeable).
    """
    try:
        checkbox = page.get_by_label(_accent_insensitive_pattern(label_text)).and_(page.locator(':visible')).first
        checkbox.wait_for(timeout=timeout)
        if not checkbox.is_checked():
            checkbox.check(timeout=timeout)
        return
    except PlaywrightTimeoutError:
        pass
    click_by_text(page, label_text, timeout=timeout)


def select_generic(page, label_text, option_text, timeout=8000):
    """Selecciona una opción probando varios patrones de UI, porque no se
    conoce de antemano qué framework usa cada portal (Material-UI, <select>
    nativo, tarjetas clicables). Prueba en orden: combo MUI (click_select),
    <select> nativo, y por último clic directo sobre el texto de la opción.
    """
    try:
        click_select(page, label_text, option_text, timeout=timeout)
        return
    except PlaywrightTimeoutError:
        pass
    try:
        select_el = page.get_by_label(_accent_insensitive_pattern(label_text)).and_(page.locator(':visible')).first
        select_el.wait_for(timeout=timeout)
        select_el.select_option(label=option_text, timeout=timeout)
        return
    except Exception:
        pass
    try:
        # Fallback adicional: el <label> de este portal a veces no asocia
        # por for= con su control real (mismo problema visto en
        # login/residencia/correo). Se ubica por el TEXTO visible del label
        # y se sube al padre directo para encontrar el <select> real.
        patron = _accent_insensitive_pattern(label_text)
        etiqueta = page.get_by_text(patron).and_(page.locator(':visible')).first
        etiqueta.wait_for(timeout=timeout)
        contenedor = etiqueta.locator('xpath=..')
        select_el = contenedor.locator('select').first
        select_el.wait_for(timeout=timeout)
        select_el.select_option(label=option_text, timeout=timeout)
        return
    except Exception:
        pass
    click_by_text(page, option_text, timeout=timeout)


def buscar_y_seleccionar_autocompletar(page, texto_a_escribir, opcion_esperada, campo_label=None, timeout=10000, preferir_texto=None):
    """Escribe en un campo de autocompletar (ej. ciudad de residencia) y elige
    la sugerencia que aparece. Si se da `campo_label`, ubica el campo por su
    etiqueta; si no, usa el campo enfocado/visible más probable por
    placeholder genérico."""
    campo = None
    if campo_label:
        patron = _accent_insensitive_pattern(campo_label)
        candidato = page.get_by_label(patron).or_(page.get_by_placeholder(patron)).first
        try:
            candidato.wait_for(timeout=timeout)
            campo = candidato
        except PlaywrightTimeoutError:
            # El texto de la etiqueta existe en pantalla pero get_by_label no
            # lo resuelve: en este portal el <label for="..."> a veces apunta
            # a un id que no corresponde a ningún input real (visto en
            # corrida real, ej. for="input" sin ese id en el documento). El
            # marcado real de estos campos es siempre
            # <div class="form-group..."><input>...<label>texto</label></div>
            # — input y label son HERMANOS bajo el mismo padre directo — así
            # que se sube solo un nivel (el padre inmediato del label) y se
            # busca el input ahí, en vez de un ancestro más amplio que puede
            # terminar abarcando varios campos hermanos a la vez (visto en
            # corrida real: agarró "Código postal" en vez del campo correcto).
            etiqueta = page.get_by_text(patron).first
            etiqueta.wait_for(timeout=timeout)
            contenedor = etiqueta.locator('xpath=..')
            campo = contenedor.locator('input:not([type="hidden"])').first
    else:
        campo = page.get_by_role('textbox').first
    campo.wait_for(timeout=timeout)
    # Defensivo: un backdrop de modal huérfano (ver remove_stray_backdrops)
    # puede seguir bloqueando el clic aunque los modales conocidos ya se
    # hayan cerrado antes de llegar a este paso.
    remove_stray_backdrops(page)
    campo.click()
    # No se usa fill(): asigna el valor de una sola vez y varios buscadores
    # de este portal solo disparan su búsqueda con eventos de tecleo reales
    # por carácter (visto en corrida real: fill() dejó el campo con el texto
    # pero ninguna sugerencia apareció). press_sequentially simula tecleo real.
    campo.press_sequentially(texto_a_escribir, delay=120)
    patron_opcion = _accent_insensitive_pattern(opcion_esperada)

    def opciones_visibles():
        opciones = page.locator('ul.ui-autocomplete li, [role="option"]').filter(has_text=patron_opcion).and_(page.locator(':visible'))
        if opciones.count() == 0:
            # Algunas listas no usan esas clases; se reintenta con texto visible genérico.
            opciones = page.get_by_text(patron_opcion).and_(page.locator(':visible'))
        if preferir_texto:
            preferidas = opciones.filter(has_text=_accent_insensitive_pattern(preferir_texto))
            if preferidas.count():
                opciones = preferidas
        return opciones

    def ya_elegida():
        """La opción quedó elegida si el campo ya no tiene solo lo tecleado (el portal lo completa, ej. con el depto)."""
        try:
            return campo.input_value(timeout=2000).strip().lower() != texto_a_escribir.strip().lower()
        except Exception:
            return False

    # La lista de sugerencias se elige entre las opciones VISIBLES: el mismo texto (ej. "Cali") puede existir además
    # en elementos ocultos del DOM, y tomar el primero a ciegas hizo fallar a Qualitas con una lista correcta a la
    # vista ("CALI, VALLE DEL CAUCA").
    try:
        opciones_visibles().first.wait_for(timeout=timeout)
    except PlaywrightTimeoutError:
        # A veces el portal llena la lista pero la deja oculta (visto en Qualitas al cotizar un 0 km: el menú tenía
        # «ZIPAQUIRA, CUNDINAMARCA…» con display:none). Se elige con el teclado: flecha abajo hasta la opción + Enter.
        if _elegir_con_teclado(page, campo, patron_opcion, preferir_texto) and ya_elegida():
            return
        opciones_visibles().first.wait_for(timeout=timeout)
    # El menú se redibuja con cada respuesta del portal: un clic dado apenas aparece la lista puede perderse
    # (visto en Qualitas: el campo seguía con lo tecleado y «Siguiente» deshabilitado). Se espera a que se asiente
    # y se verifica que el clic realmente eligió la opción; si no, se reintenta.
    for intento in range(4):
        page.wait_for_timeout(1500 if intento == 0 else 1000)
        try:
            opciones_visibles().first.click(timeout=timeout)
        except PlaywrightTimeoutError:
            continue
        page.wait_for_timeout(800)
        if ya_elegida():
            return
    if _elegir_con_teclado(page, campo, patron_opcion, preferir_texto) and ya_elegida():
        return
    raise PlaywrightTimeoutError(
        f'No se pudo elegir la opción «{opcion_esperada}» de la lista de sugerencias (el campo quedó con lo tecleado).')


def _elegir_con_teclado(page, campo, patron_opcion, preferir_texto=None):
    """Elige con el teclado una sugerencia de jQuery UI que está en el DOM pero oculta. True si el campo quedó con la
    opción esperada; False si no había ninguna sugerencia que coincida (no deja el campo modificado)."""
    try:
        # Solo la lista de ESTE campo (la página puede tener otras listas de autocompletado con elementos).
        textos = campo.evaluate(
            """e => { const $ = window.jQuery; if (!$ || !$(e).autocomplete) return [];
                      const w = $(e).autocomplete('widget')[0];
                      return w ? [...w.children].map(l => (l.textContent || '').trim()) : []; }""")
    except Exception:
        return False
    coincidencias = [i for i, t in enumerate(textos) if t and patron_opcion.search(t)]
    if not coincidencias:
        return False
    if preferir_texto:
        patron_pref = _accent_insensitive_pattern(preferir_texto)
        preferidas = [i for i in coincidencias if patron_pref.search(textos[i])]
        coincidencias = preferidas or coincidencias
    posicion = coincidencias[0] + 1  # ArrowDown la primera vez resalta la opción 1
    for _ in range(posicion):
        campo.press('ArrowDown')
        page.wait_for_timeout(150)
    campo.press('Enter')
    page.wait_for_timeout(800)
    try:
        return bool(patron_opcion.search(campo.input_value(timeout=2000)))
    except Exception:
        return False


def escribir_verificado(page, campo, valor, intentos=3, delay=70):
    """Teclea `valor` de verdad (press_sequentially, no fill) y confirma que el
    campo quedó EXACTAMENTE con ese valor antes de seguir. Se vio en corridas
    reales (Qualitas) que un solo carácter podía perderse o duplicarse por un
    re-render del framework al iniciar el tecleo, y que el portal luego enviaba
    datos incompletos. Se limpia el campo entre intentos. Lanza RuntimeError
    (sin incluir el valor, por si es una contraseña) si no se logra."""
    for _ in range(intentos):
        campo.click()
        campo.press('Control+A')
        campo.press('Delete')
        campo.press_sequentially(valor, delay=delay)
        page.wait_for_timeout(250)
        if campo.input_value(timeout=2000) == valor:
            return
    raise RuntimeError('No se pudo escribir el valor esperado en un campo del portal tras varios intentos.')
