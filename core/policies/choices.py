MEDIO_PAGO = (
    ('cash', 'Efectivo'),
    ('creditCard', 'Tarjeta Crédito'),
    ('debitCard', 'Tarjeta Débito'),
    ('transfer', 'Transferencia'),
    ('mixto', 'Mixto'),
)

ESTADO_COTIZACION = (
    ('cotizado', 'Cotizado'),
    ('aprobado', 'Aprobado'),
    ('emitido', 'Emitido'),
    ('vencido', 'Vencido'),
    ('cancelado', 'Cancelado'),
)

SERVICIO_VEHICULO = (
    ('particular', 'Particular'),
    ('publico', 'Público'),
)

ESTADO_BOT = (
    ('pendiente', 'Pendiente'),
    ('en_proceso', 'En proceso'),
    ('esperando_confirmacion', 'Esperando confirmación'),
    ('completado', 'Completado'),
    ('error', 'Error'),
    ('cancelado', 'Cancelado'),
)

# Por qué falló un bot, en lenguaje del asesor (ver services/bots/base.py:clasificar_error).
ERROR_BOT_TIPO = (
    ('autenticacion', 'No se pudo iniciar sesión'),
    ('timeout', 'El portal no respondió a tiempo'),
    ('datos', 'Dato rechazado o faltante'),
    ('portal', 'Aviso o rechazo del portal'),
    ('interrumpida', 'Proceso interrumpido'),
    ('no_cotizable', 'La aseguradora no cotiza este caso'),
    ('saturado', 'El portal está saturado'),
    ('clave_vencida', 'La aseguradora pide cambiar la contraseña'),
    ('inesperado', 'Falla inesperada del bot'),
)

TIPO_ASESOR = (
    ('interno', 'Interno'),
    ('externo', 'Externo'),
)

TIPO_CUENTA = (
    ('ahorros', 'Ahorros'),
    ('corriente', 'Corriente'),
)
