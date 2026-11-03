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
    ),
    'Seguros Mundial': (
        {'clave': 'direccion', 'etiqueta': 'Dirección de contacto', 'obligatorio': True,
         'ayuda': 'Va con el correo y el celular de contacto en los datos del propietario (ej. la dirección de la oficina).'},
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


def parametros_de(aseguradora_nombre):
    return PARAMETROS_POR_ASEGURADORA.get(aseguradora_nombre, ())


def parametro(credencial, aseguradora_nombre, clave):
    """Valor de una opción del cotizador: el que guardó la empresa o, si no lo cambió, el valor por defecto."""
    guardado = ((credencial.parametros or {}) if credencial else {}).get(clave)
    if guardado not in (None, ''):
        return guardado
    return next((p.get('defecto', '') for p in parametros_de(aseguradora_nombre) if p['clave'] == clave), '')


def lista(valor):
    """«A, B, C» → ['A', 'B', 'C']."""
    return [p.strip() for p in str(valor or '').split(',') if p.strip()]


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
    pendientes = []
    for campo in obligatorios_de(aseguradora):
        if credencial is None or not getattr(credencial, campo):
            pendientes.append(str(modelo._meta.get_field(campo).verbose_name))
    for p in parametros_de(aseguradora.name):
        if p.get('obligatorio') and not parametro(credencial, aseguradora.name, p['clave']):
            pendientes.append(p['etiqueta'])
    return pendientes
