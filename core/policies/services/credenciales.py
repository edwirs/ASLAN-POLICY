"""Qué datos de acceso necesita el bot de cada aseguradora.

Un único modelo (`AseguradoraCredencial`) guarda los datos de todas, pero cada
portal usa solo algunos campos; esta tabla decide cuáles se piden en pantalla
y cuáles son obligatorios para que el bot pueda iniciar sesión.
"""

# Campos que aplican a una aseguradora sin bot propio o aún no mapeada.
CAMPOS_BASE = ('portal_url', 'username', 'password')

CAMPOS_POR_ASEGURADORA = {
    'Seguros del Estado': ('portal_url', 'username', 'password', 'ramo', 'tipo_seguro', 'sucursal'),
    'Qualitas': ('portal_url', 'codigo_intermediario', 'cuenta', 'password', 'correo_contacto', 'telefono_contacto'),
    'HDI': ('portal_url', 'tipo_documento', 'username', 'password', 'clave_agencia'),
    'La Equidad Seguros': ('portal_url', 'username', 'password'),
    'AXA Colpatria': ('portal_url', 'tipo_documento', 'username', 'password'),
    'Seguros Mundial': ('portal_url', 'username', 'password', 'correo_contacto', 'telefono_contacto'),
    'Mapfre': ('portal_url', 'username', 'password'),
}

# Mínimo indispensable para iniciar sesión en el portal.
OBLIGATORIOS_POR_ASEGURADORA = {
    'Seguros del Estado': ('portal_url', 'username', 'password', 'ramo', 'tipo_seguro'),
    # Qualitas y Mundial piden un correo y un celular de contacto: van los de la empresa (no hay valor por defecto).
    'Qualitas': ('portal_url', 'codigo_intermediario', 'cuenta', 'password', 'correo_contacto', 'telefono_contacto'),
    'HDI': ('portal_url', 'username', 'password', 'clave_agencia'),
    'La Equidad Seguros': ('portal_url', 'username', 'password'),
    'AXA Colpatria': ('portal_url', 'username', 'password'),
    'Seguros Mundial': ('portal_url', 'username', 'password', 'correo_contacto', 'telefono_contacto'),
    'Mapfre': ('portal_url', 'username', 'password'),
}
OBLIGATORIOS_BASE = ('portal_url', 'username', 'password')

# Dirección de inicio de sesión de cada portal: es la misma para todos los intermediarios, así que una empresa nueva
# la encuentra ya escrita y solo pone sus datos de acceso.
PORTALES = {
    'Seguros del Estado': 'https://thot-sde-auth.sise3g.com.co/login/agent',
    'Qualitas': 'https://www.qualitascolombia.com.co/home',
    'HDI': 'https://oficinaenlinea.hdiseguros.com.co/',
    'La Equidad Seguros': 'https://polizae.laequidadseguros.coop/#/',
    'AXA Colpatria': 'https://www.axacolpatria.co/es/home',
    'Seguros Mundial': 'https://expedidores.mundialseguros.com.co/#/productos/tipo-producto',
    'Mapfre': 'https://digital.mapfre.com.co/ofiVirtualWeb/vista/publico/loginIntermediariosV2.jsf',
}

# Valores con que arrancan los campos de una credencial nueva (iguales para cualquier intermediario).
INICIALES = {
    'Seguros del Estado': {'ramo': 'Automóviles livianos individual', 'tipo_seguro': 'Particular'},
    'HDI': {'tipo_documento': 'Cédula de ciudadanía'},
    'AXA Colpatria': {'tipo_documento': 'Cédula de ciudadanía'},
}

# Opciones propias de cada empresa en el cotizador de cada portal (se guardan en `AseguradoraCredencial.parametros`).
# Las que tienen `defecto` son decisiones comerciales con un valor de partida (el que usa Gali); las `obligatorio`
# son datos de la empresa sin valor posible por defecto (su oficina, su dirección…).
PARAMETROS_POR_ASEGURADORA = {
    'Mapfre': (
        {'clave': 'oficina', 'etiqueta': 'Oficina en Mapfre', 'obligatorio': True,
         'ayuda': 'Tal como sale en la lista «Oficina» del cotizador de Mapfre (ej. RESTREPO).'},
        {'clave': 'productos', 'etiqueta': 'Productos a cotizar', 'defecto': 'SUPER TREBOL 117, SUPER TREBOL',
         'ayuda': 'Separados por coma, con el nombre de la casilla en «Autos cotización múltiple».'},
        {'clave': 'producto_destacado', 'etiqueta': 'Producto que cuenta en el comparativo', 'defecto': 'Super Trebol 117'},
        {'clave': 'opcion_rce', 'etiqueta': 'Opción de RCE', 'defecto': '(254)',
         'ayuda': 'Código de la lista de RCE del portal: (254) = 4.000 millones.'},
        {'clave': 'deducible_cero_perdida_total', 'etiqueta': 'Deducible en cero por pérdida total', 'defecto': 'SI (S)'},
        {'clave': 'deducible_perdida_parcial', 'etiqueta': 'Deducible por pérdida parcial', 'defecto': '1.200.000'},
        {'clave': 'minutos_sesion', 'etiqueta': 'Minutos que queda abierta la sesión', 'defecto': '10',
         'ayuda': 'Después del captcha y el código, las solicitudes de Mapfre que lleguen en este tiempo se cotizan en la '
                  'misma sesión, sin volver a pedirlos. Al cumplirse se cierra sesión. 0 = cerrar después de cada una.'},
    ),
    'Seguros Mundial': (
        {'clave': 'direccion', 'etiqueta': 'Dirección de contacto (opcional)',
         'ayuda': 'Vacío = la dirección del contacto general para los portales (arriba en Aseguradoras).'},
    ),
    'AXA Colpatria': (
        {'clave': 'perfil', 'etiqueta': 'Perfil con el que se entra', 'defecto': 'Administrador',
         'ayuda': 'El perfil que se elige en AXA después de iniciar sesión.'},
    ),
    'Qualitas': (
        {'clave': 'amparos_accesorios', 'etiqueta': 'Amparos accesorios que se marcan',
         'defecto': ('Pérdida de llaves, Gastos de transporte pérdida total, Gastos de transporte pérdida parcial, '
                     'Llantas estalladas, Rotura de vidrios, Pequeños accesorios'),
         'ayuda': 'Separados por coma, con el nombre que tienen en la pantalla de Amparos.'},
    ),
}


# Dónde se abre el navegador del bot (ver core/tenants/agentes.py). Va primero en las opciones de cada aseguradora con
# bot, salvo Seguros del Estado (se cotiza a mano: su portal rechaza los navegadores automatizados desde cualquier red).
OPCIONES_EJECUCION = (
    ('servidor', 'Servidor de ASLAN'),
    ('automatico', 'Agente de la oficina si está encendido; si no, el servidor'),
    ('agente', 'Solo con el Agente de la oficina'),
)
EJECUCION_POR_DEFECTO = {'Mapfre': 'automatico', 'La Equidad Seguros': 'automatico'}
CON_AGENTE = ('Mapfre', 'La Equidad Seguros', 'Qualitas', 'HDI', 'AXA Colpatria', 'Seguros Mundial')


def _parametro_ejecucion(aseguradora_nombre):
    return {
        'clave': 'ejecutar_en', 'etiqueta': 'Dónde se cotiza', 'opciones': OPCIONES_EJECUCION,
        'defecto': EJECUCION_POR_DEFECTO.get(aseguradora_nombre, 'servidor'),
        'ayuda': ('«Agente de la oficina» = el navegador del PC de la oficina con el Agente ASLAN (Configuraciones › '
                  'Agente de la oficina): sale con la IP de la oficina y muestra ahí las ventanas que piden una persona '
                  '(captcha de Mapfre).'),
    }


def parametros_de(aseguradora_nombre):
    propios = PARAMETROS_POR_ASEGURADORA.get(aseguradora_nombre, ())
    if aseguradora_nombre in CON_AGENTE:
        return (_parametro_ejecucion(aseguradora_nombre),) + tuple(propios)
    return propios


def parametro(credencial, aseguradora_nombre, clave):
    """Valor de una opción del cotizador: el que guardó la empresa o, si no lo cambió, el valor por defecto."""
    guardado = ((credencial.parametros or {}) if credencial else {}).get(clave)
    if guardado not in (None, ''):
        return guardado
    return next((p.get('defecto', '') for p in parametros_de(aseguradora_nombre) if p['clave'] == clave), '')


def lista(valor):
    """«A, B, C» → ['A', 'B', 'C']."""
    return [p.strip() for p in str(valor or '').split(',') if p.strip()]


# Contacto que los bots escriben en los portales: el general de la empresa (ContactoPortales), salvo que la credencial
# de esa aseguradora traiga el suyo. Campo de la credencial -> campo del contacto general.
CAMPOS_CONTACTO = {'correo_contacto': 'correo', 'telefono_contacto': 'celular'}


def contacto_general():
    from core.policies.models import ContactoPortales  # import local: evita ciclo al cargar el módulo
    return ContactoPortales.actual()


def contacto(credencial, aseguradora_nombre, general=None):
    """{'correo', 'celular', 'direccion'} que el bot de esta aseguradora escribe en su portal."""
    general = general or contacto_general()
    return {
        'correo': ((credencial.correo_contacto if credencial else '') or general.correo or '').strip(),
        'celular': ((credencial.telefono_contacto if credencial else '') or general.celular or '').strip(),
        'direccion': (str(parametro(credencial, aseguradora_nombre, 'direccion') or '') or general.direccion or '').strip(),
    }


def campos_de(aseguradora):
    return CAMPOS_POR_ASEGURADORA.get(aseguradora.name, CAMPOS_BASE)


def obligatorios_de(aseguradora):
    return OBLIGATORIOS_POR_ASEGURADORA.get(aseguradora.name, OBLIGATORIOS_BASE)


def credencial_vigente(aseguradora):
    """La credencial que usa el bot: la activa más reciente (igual que los bots)."""
    return aseguradora.credenciales.filter(is_active=True).order_by('-id').first()


def faltantes(aseguradora, credencial=None):
    """Etiquetas de los datos obligatorios que aún no están configurados."""
    credencial = credencial if credencial is not None else credencial_vigente(aseguradora)
    modelo = aseguradora.credenciales.model
    general = contacto_general()
    pendientes = []
    for campo in obligatorios_de(aseguradora):
        if campo in CAMPOS_CONTACTO and getattr(general, CAMPOS_CONTACTO[campo]):
            continue  # lo cubre el contacto general para los portales
        if credencial is None or not getattr(credencial, campo):
            pendientes.append(str(modelo._meta.get_field(campo).verbose_name))
    if aseguradora.name == 'Seguros Mundial' and not contacto(credencial, aseguradora.name, general)['direccion']:
        pendientes.append('Dirección de contacto')
    for p in parametros_de(aseguradora.name):
        if p.get('obligatorio') and not parametro(credencial, aseguradora.name, p['clave']):
            pendientes.append(p['etiqueta'])
    return pendientes
