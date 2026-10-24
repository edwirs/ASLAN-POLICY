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
    'Seguros del Estado': ('portal_url', 'username', 'password'),
    'Qualitas': ('portal_url', 'codigo_intermediario', 'cuenta', 'password'),
    'HDI': ('portal_url', 'username', 'password', 'clave_agencia'),
    'La Equidad Seguros': ('portal_url', 'username', 'password'),
    'AXA Colpatria': ('portal_url', 'username', 'password'),
    'Seguros Mundial': ('portal_url', 'username', 'password'),
    'Mapfre': ('portal_url', 'username', 'password'),
}
OBLIGATORIOS_BASE = ('portal_url', 'username', 'password')


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
    return pendientes
