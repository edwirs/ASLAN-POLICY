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

# Estado del vehículo para el seguimiento. Cualquiera distinto de «activo» bloquea el botón de cotizar hasta que alguien
# lo actualice desde la solicitud (ver services/polizas.py).
ESTADO_VEHICULO = (
    ('activo', 'Activo'),
    ('vendido', 'Vendido'),
    ('siniestrado', 'Siniestrado (pérdida total)'),
    ('hurtado', 'Hurtado'),
    ('chatarrizado', 'Chatarrizado'),
    ('no_renovo', 'No renovó / se fue con otro'),
)

# Qué cambió en un vehículo (historial / trazabilidad).
TIPO_EVENTO_VEHICULO = (
    ('estado', 'Cambio de estado'),
    ('propietario', 'Cambio de propietario'),
    ('ciudad', 'Cambio de ciudad de circulación'),
    ('decision', 'Decisión del cliente'),
    ('correo', 'Cotización enviada por correo'),
    ('valor', 'Valor manual de aseguradora'),
)

# Columna «ESTADO» del Excel: OK = la póliza ya se generó (tiene fecha de pago).
ESTADO_POLIZA = (
    ('generada', 'Generada'),
    ('cancelada', 'Cancelada'),
)

# Columna «ESTADO GALI» del Excel: si la aseguradora ya dio fecha de pago de la comisión.
ESTADO_COMISION = (
    ('cartera', 'Pendiente (en cartera)'),
    ('ok', 'Confirmada (OK, con fecha de pago)'),
)

# Por qué el cliente NO compró después de cotizar (cierra el caso sin bloquear la placa: puede volver a cotizar).
MOTIVO_NO_COMPRO = (
    ('precio', 'Le pareció costoso'),
    ('otra_aseguradora', 'Renovó con su aseguradora actual'),
    ('otro_intermediario', 'Compró con otro intermediario'),
    ('no_responde', 'No volvió a responder'),
    ('no_necesita', 'Ya no lo necesita'),
    ('otro', 'Otro motivo'),
)

ORIGEN_POLIZA = (
    ('sistema', 'Registrada en el sistema'),
    ('importada', 'Importada del histórico'),
)

# Plantillas de correo: a qué tipo de seguro aplica cada una (por ahora solo autos).
TIPO_SEGURO_PLANTILLA = (
    ('autos', 'Autos'),
)

# Cifrado de la conexión con el servidor de correo (SMTP).
SEGURIDAD_SMTP = (
    ('tls', 'STARTTLS (puerto 587, el más común)'),
    ('ssl', 'SSL (puerto 465)'),
    ('ninguna', 'Sin cifrado (no recomendado)'),
)

ESTADO_CORREO = (
    ('enviado', 'Enviado'),
    ('error', 'No se pudo enviar'),
)
