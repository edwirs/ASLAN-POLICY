from datetime import date
from zoneinfo import ZoneInfo

from django.db import models
from django.forms import model_to_dict
from django.utils import timezone

from core.policies.choices import ERROR_BOT_TIPO
from core.policies.choices import ESTADO_BOT
from core.policies.choices import ESTADO_COMISION
from core.policies.choices import ESTADO_CORREO
from core.policies.choices import ESTADO_COTIZACION
from core.policies.choices import ESTADO_POLIZA
from core.policies.choices import MOTIVO_NO_COMPRO
from core.policies.choices import ESTADO_VEHICULO
from core.policies.choices import MEDIO_PAGO
from core.policies.choices import ORIGEN_POLIZA
from core.policies.choices import SEGURIDAD_SMTP
from core.policies.choices import SERVICIO_VEHICULO
from core.policies.choices import TIPO_ASESOR
from core.policies.choices import TIPO_CUENTA
from core.policies.choices import TIPO_EVENTO_VEHICULO
from core.policies.choices import TIPO_SEGURO_PLANTILLA
from core.policies.fields import EncryptedCharField
from core.pos.models import Client
from core.pos.models import DocumentType
from core.pos.models import Municipio
from core.security.registry import perms_for
from core.user.models import User


class Aseguradora(models.Model):
    name = models.CharField(max_length=150, unique=True, verbose_name='Nombre')
    nit = models.CharField(max_length=20, null=True, blank=True, verbose_name='NIT')
    logo = models.ImageField(upload_to='aseguradoras/%Y/%m/%d', null=True, blank=True, verbose_name='Logo')
    phone = models.CharField(max_length=20, null=True, blank=True, verbose_name='Teléfono')
    email = models.CharField(max_length=100, null=True, blank=True, verbose_name='Email')
    is_active = models.BooleanField(default=True, verbose_name='Estado')

    def __str__(self):
        return self.name

    def toJSON(self):
        item = model_to_dict(self)
        item['logo'] = self.logo.url if self.logo else None
        return item

    class Meta:
        verbose_name = 'Aseguradora'
        verbose_name_plural = 'Aseguradoras'
        ordering = ['name']
        default_permissions = ()
        permissions = (
            ('view_aseguradora', 'Ver Aseguradora'),
            ('add_aseguradora', 'Agregar Aseguradora'),
            ('change_aseguradora', 'Editar Aseguradora'),
            ('delete_aseguradora', 'Eliminar Aseguradora'),
        )


class AseguradoraCredencial(models.Model):
    """Credenciales de acceso al portal web de una aseguradora, usadas por el
    bot de cotización. La contraseña se guarda cifrada (ver core.policies.fields),
    nunca en texto plano, y nunca se expone vía toJSON()."""
    aseguradora = models.ForeignKey(Aseguradora, on_delete=models.CASCADE, related_name='credenciales', verbose_name='Aseguradora')
    portal_url = models.URLField(max_length=300, verbose_name='URL del portal')
    # Algunas aseguradoras usan usuario/email + contraseña (Seguros del Estado);
    # otras usan código de intermediario + cuenta + contraseña (Qualitas). Se
    # dejan ambos pares de campos opcionales para no forzar un único esquema.
    username = models.CharField(max_length=150, null=True, blank=True, verbose_name='Usuario / Email / Nº de identificación')
    # HDI inicia sesión con tipo de documento + número de identificación (en
    # `username`) y luego exige elegir una "clave" de agencia en un combo.
    tipo_documento = models.CharField(max_length=60, null=True, blank=True, verbose_name='Tipo de documento (login)')
    clave_agencia = models.CharField(max_length=150, null=True, blank=True, verbose_name='Clave / agencia (cotizador)')
    codigo_intermediario = models.CharField(max_length=50, null=True, blank=True, verbose_name='Código intermediario')
    cuenta = models.CharField(max_length=100, null=True, blank=True, verbose_name='Cuenta')
    password = EncryptedCharField(max_length=500, verbose_name='Contraseña')

    ramo = models.CharField(max_length=150, null=True, blank=True, verbose_name='Ramo (cotizador)')
    tipo_seguro = models.CharField(max_length=100, null=True, blank=True, verbose_name='Tipo de seguro (cotizador)')
    sucursal = models.CharField(max_length=150, null=True, blank=True, verbose_name='Sucursal (cotizador)')
    correo_contacto = models.CharField(max_length=100, null=True, blank=True, verbose_name='Correo de contacto (cotizador)')
    telefono_contacto = models.CharField(max_length=20, null=True, blank=True, verbose_name='Teléfono de contacto (cotizador)')
    # Opciones propias de la empresa en el cotizador de este portal (oficina, productos, RCE…): ver
    # services/credenciales.PARAMETROS_POR_ASEGURADORA, que dice cuáles tiene cada aseguradora y su valor por defecto.
    parametros = models.JSONField(default=dict, blank=True, verbose_name='Opciones del cotizador')

    # La aseguradora exigió cambiar la contraseña en su portal. Mientras esté marcada, los bots no intentan entrar
    # (cada intento fallido acerca la cuenta al bloqueo); se limpia sola al guardar una contraseña nueva.
    requiere_cambio_clave = models.BooleanField(default=False, verbose_name='Requiere cambio de contraseña')
    cambio_clave_detectado_en = models.DateTimeField(null=True, blank=True, verbose_name='Cambio de contraseña detectado el')

    is_active = models.BooleanField(default=True, verbose_name='Estado')
    created_at = models.DateTimeField(auto_now_add=True, verbose_name='Fecha de registro')

    def __str__(self):
        identificador = self.username or self.cuenta or self.codigo_intermediario or ''
        return f'{self.aseguradora} - {identificador}'

    def toJSON(self):
        item = model_to_dict(self, exclude=['aseguradora', 'password', 'created_at', 'cambio_clave_detectado_en'])
        item['aseguradora'] = self.aseguradora.toJSON()
        item['created_at'] = self.created_at.strftime('%Y-%m-%d %H:%M')
        return item

    class Meta:
        verbose_name = 'Credencial de Aseguradora'
        verbose_name_plural = 'Credenciales de Aseguradoras'
        ordering = ['-id']
        default_permissions = ()
        permissions = (
            ('view_aseguradoracredencial', 'Ver Credencial de Aseguradora'),
            ('add_aseguradoracredencial', 'Agregar Credencial de Aseguradora'),
            ('change_aseguradoracredencial', 'Editar Credencial de Aseguradora'),
            ('delete_aseguradoracredencial', 'Eliminar Credencial de Aseguradora'),
        )


class CoberturaAseguradora(models.Model):
    """Ficha comparativa de coberturas y asistencias de una aseguradora (cuadro «COMPARATIVO»).

    Todas las aseguradoras tienen los mismos campos, apliquen o no (se escribe «No Ampara»). Una
    aseguradora puede tener varios productos (AXA: Plus y VIP; Seguros del Estado: Integral y Elite): cada
    uno es una ficha. Es información de referencia para reportes y comparaciones; no la usan los bots.
    Los textos son libres porque cada aseguradora expresa los valores a su manera (SMMLV, SMDLV, $, días…)."""
    aseguradora = models.ForeignKey(Aseguradora, on_delete=models.CASCADE, related_name='fichas', verbose_name='Aseguradora')
    producto = models.CharField(max_length=80, default='General', verbose_name='Producto / plan',
                                help_text='Ej: Plus, VIP, Integral, Elite. Use «General» si la aseguradora tiene uno solo.')

    # Responsabilidad civil extracontractual
    rc_limite_millones = models.PositiveIntegerField(null=True, blank=True, verbose_name='RC extracontractual: límite máximo (millones de pesos)')
    rc_deducible = models.CharField(max_length=300, blank=True, verbose_name='RC extracontractual: deducible')

    # Coberturas del vehículo
    perdida_total_cubrimiento = models.CharField(max_length=300, blank=True, verbose_name='Pérdida total por daños o hurto (cubrimiento)')
    perdida_parcial_deducible = models.CharField(max_length=300, blank=True, verbose_name='Pérdida parcial por daños y/o hurto (deducible)')
    eventos_naturaleza = models.CharField(max_length=300, blank=True, verbose_name='Eventos de la naturaleza')
    amparo_patrimonial = models.CharField(max_length=300, blank=True, verbose_name='Amparo patrimonial')

    # Asistencias
    grua = models.CharField(max_length=300, blank=True, verbose_name='Grúa varada y accidente')
    carro_taller = models.CharField(max_length=300, blank=True, verbose_name='Carro taller (desvare por llanta, batería, gasolina o cerrajería)')
    asistencia_juridica = models.CharField(max_length=300, blank=True, verbose_name='Asistencia jurídica en proceso penal y civil')
    gastos_transporte_perdida_total = models.CharField(max_length=300, blank=True, verbose_name='Gastos de transporte en pérdida total')
    gastos_transporte_perdida_parcial = models.CharField(max_length=300, blank=True, verbose_name='Gastos de transporte en pérdida parcial')
    vehiculo_reemplazo_perdida_total = models.CharField(max_length=300, blank=True, verbose_name='Vehículo de reemplazo en pérdida total')
    vehiculo_reemplazo_perdida_parcial = models.CharField(max_length=300, blank=True, verbose_name='Vehículo de reemplazo en pérdida parcial')
    conductor_elegido = models.CharField(max_length=300, blank=True, verbose_name='Conductor elegido')
    revision_antes_viaje = models.CharField(max_length=300, blank=True, verbose_name='Revisión antes de viaje')
    asistencia_hogar = models.CharField(max_length=300, blank=True, verbose_name='Asistencia hogar')

    # Amparos adicionales
    ruptura_vidrios = models.CharField(max_length=300, blank=True, verbose_name='Ruptura de vidrios')
    accidentes_personales = models.CharField(max_length=300, blank=True, verbose_name='Accidentes personales')
    llantas_estalladas = models.CharField(max_length=300, blank=True, verbose_name='Llantas estalladas')
    perdida_llaves = models.CharField(max_length=300, blank=True, verbose_name='Pérdida de llaves')
    pequenos_accesorios = models.CharField(max_length=300, blank=True, verbose_name='Pequeños accesorios')
    farolas_stop_espejos = models.CharField(max_length=300, blank=True, verbose_name='Farolas, stop, vidrios y espejos retrovisores (exclusiva por daños)')
    amortiguadores_parachoques = models.CharField(max_length=300, blank=True, verbose_name='Amortiguadores y parachoques')

    observaciones = models.TextField(blank=True, verbose_name='Observaciones')
    created_at = models.DateTimeField(auto_now_add=True, verbose_name='Fecha de registro')
    updated_at = models.DateTimeField(auto_now=True, verbose_name='Última actualización')

    def __str__(self):
        return f'{self.aseguradora} - {self.producto}'

    class Meta:
        verbose_name = 'Ficha de coberturas'
        verbose_name_plural = 'Fichas de coberturas'
        ordering = ['aseguradora__name', 'id']
        unique_together = (('aseguradora', 'producto'),)
        default_permissions = ()


class TipoPoliza(models.Model):
    code = models.SlugField(max_length=30, unique=True, verbose_name='Código')
    name = models.CharField(max_length=100, unique=True, verbose_name='Nombre')
    description = models.CharField(max_length=500, null=True, blank=True, verbose_name='Descripción')
    is_active = models.BooleanField(default=True, verbose_name='Estado')

    def __str__(self):
        return self.name

    def toJSON(self):
        return model_to_dict(self)

    class Meta:
        verbose_name = 'Tipo de póliza'
        verbose_name_plural = 'Tipos de póliza'
        ordering = ['name']
        default_permissions = ()
        permissions = (
            ('view_tipopoliza', 'Ver Tipo de póliza'),
            ('add_tipopoliza', 'Agregar Tipo de póliza'),
            ('change_tipopoliza', 'Editar Tipo de póliza'),
            ('delete_tipopoliza', 'Eliminar Tipo de póliza'),
        )


class Vehiculo(models.Model):
    tomador = models.ForeignKey(Client, on_delete=models.PROTECT, related_name='vehiculos', verbose_name='Tomador')
    placa = models.CharField(max_length=10, unique=True, verbose_name='Placa')
    referencia = models.CharField(max_length=150, null=True, blank=True, verbose_name='Referencia (línea y versión)')
    modelo = models.PositiveIntegerField(null=True, blank=True, verbose_name='Modelo (año)')
    modelo_fuente = models.CharField(max_length=60, null=True, blank=True, verbose_name='Aseguradora que fijó el modelo')
    zona_circulacion = models.ForeignKey(Municipio, on_delete=models.PROTECT, verbose_name='Zona de circulación')

    es_cero_km = models.BooleanField(default=False, verbose_name='¿Es 0 kilómetros?')
    clase = models.CharField(max_length=100, null=True, blank=True, verbose_name='Clase')
    marca = models.CharField(max_length=100, null=True, blank=True, verbose_name='Marca')
    servicio = models.CharField(max_length=20, choices=SERVICIO_VEHICULO, null=True, blank=True, verbose_name='Servicio')
    codigo_fasecolda = models.CharField(max_length=20, null=True, blank=True, verbose_name='Código Fasecolda')
    valor_comercial = models.DecimalField(max_digits=14, decimal_places=2, null=True, blank=True, verbose_name='Valor comercial')
    chasis = models.CharField(max_length=50, null=True, blank=True, verbose_name='Chasis')
    tipo_vehiculo = models.CharField(max_length=60, null=True, blank=True, verbose_name='Tipo de vehículo (automóvil, camioneta…)')
    color = models.CharField(max_length=60, null=True, blank=True, verbose_name='Color')
    motor = models.CharField(max_length=60, null=True, blank=True, verbose_name='Motor')
    serie = models.CharField(max_length=60, null=True, blank=True, verbose_name='Serie')
    combustible = models.CharField(max_length=40, null=True, blank=True, verbose_name='Tipo de combustible')
    valor_accesorios = models.DecimalField(max_digits=12, decimal_places=2, default=0.00, verbose_name='Valor accesorios')

    # SOAT del vehículo: lo escribe el asesor al abrir el comparativo y sale en el PDF y en el correo (valor y días
    # que le quedan de vigencia, contados desde el día en que se mira).
    soat_valor = models.DecimalField(max_digits=14, decimal_places=0, null=True, blank=True, verbose_name='Valor del SOAT')
    soat_vencimiento = models.DateField(null=True, blank=True, verbose_name='Vencimiento del SOAT')

    # Seguimiento: vendido, siniestrado… Distinto de «activo» = no se puede cotizar hasta que alguien lo actualice.
    estado = models.CharField(max_length=15, choices=ESTADO_VEHICULO, default='activo', verbose_name='Estado del vehículo')
    estado_fecha = models.DateField(null=True, blank=True, verbose_name='Fecha del estado')
    estado_nota = models.CharField(max_length=300, blank=True, default='', verbose_name='Nota del estado')

    # «No compró»: cierra la última cotización sin póliza. Solo cuenta si es posterior a la última cotización.
    no_compro_fecha = models.DateField(null=True, blank=True, verbose_name='No compró (fecha)')
    no_compro_motivo = models.CharField(max_length=20, choices=MOTIVO_NO_COMPRO, blank=True, default='', verbose_name='Motivo por el que no compró')
    no_compro_nota = models.CharField(max_length=300, blank=True, default='', verbose_name='Nota de por qué no compró')

    is_active = models.BooleanField(default=True, verbose_name='Estado')
    created_at = models.DateTimeField(auto_now_add=True, verbose_name='Fecha de registro')

    def __str__(self):
        return f'{self.placa} - {self.tomador.get_full_name()}'

    @property
    def bloqueado_para_cotizar(self):
        return self.estado != 'activo'

    def estado_json(self):
        return {
            'id': self.estado,
            'name': self.get_estado_display(),
            'fecha': self.estado_fecha.strftime('%Y-%m-%d') if self.estado_fecha else None,
            'nota': self.estado_nota,
            'bloqueado': self.bloqueado_para_cotizar,
        }

    def toJSON(self):
        item = model_to_dict(self, exclude=['tomador', 'zona_circulacion', 'created_at', 'estado', 'estado_fecha', 'estado_nota', 'no_compro_fecha',
                                            'soat_valor', 'soat_vencimiento'])
        item['soat_valor'] = int(self.soat_valor) if self.soat_valor is not None else None
        item['soat_vencimiento'] = self.soat_vencimiento.strftime('%Y-%m-%d') if self.soat_vencimiento else None
        item['tomador'] = self.tomador.toJSON()
        item['estado'] = self.estado_json()
        item['zona_circulacion'] = str(self.zona_circulacion)
        item['servicio'] = {'id': self.servicio, 'name': self.get_servicio_display()} if self.servicio else None
        item['valor_accesorios'] = float(self.valor_accesorios)
        item['valor_comercial'] = float(self.valor_comercial) if self.valor_comercial is not None else None
        item['created_at'] = self.created_at.strftime('%Y-%m-%d %H:%M')
        item['tiene_cotizacion'] = self.cotizaciones.exists()
        return item

    class Meta:
        verbose_name = 'Vehículo'
        verbose_name_plural = 'Vehículos'
        ordering = ['-id']
        default_permissions = ()
        permissions = (
            ('view_vehiculo', 'Ver Vehículo'),
            ('add_vehiculo', 'Agregar Vehículo'),
            ('change_vehiculo', 'Editar Vehículo'),
            ('delete_vehiculo', 'Eliminar Vehículo'),
            ('view_vehiculo_registrado', 'Ver vehículos registrados'),
            ('view_comparativo', 'Ver el comparativo de aseguradoras de un vehículo'),
            ('add_valor_externo', 'Registrar valores de aseguradoras sin bot'),
            ('use_asistente', 'Usar el asistente Aslani'),
            ('change_vehiculo_estado', 'Cambiar el estado de un vehículo (vendido, siniestrado…)'),
        )


def _ruta_cotizacion_manual(instancia, nombre):
    """Nombre aleatorio: la cotización lleva datos personales y no debe poder adivinarse su dirección."""
    import uuid
    return f'cotizaciones_manuales/{timezone.now():%Y/%m}/{uuid.uuid4().hex}.pdf'


def _ruta_pdf_portal(instancia, nombre):
    """PDF que descarga el bot del portal: nombre aleatorio, igual que las cotizaciones manuales."""
    import uuid
    return f'cotizaciones_portal/{timezone.now():%Y/%m}/{uuid.uuid4().hex}.pdf'


class ValorExterno(models.Model):
    """Valor final que nos entrega un tercero para una aseguradora SIN bot (Bolívar, Allianz, Sura…):
    se le pide al externo que cotice el vehículo y solo informa el valor. Se guarda cada registro (historial);
    en el comparativo cuenta el más reciente de cada aseguradora."""
    vehiculo = models.ForeignKey(Vehiculo, on_delete=models.CASCADE, related_name='valores_externos', verbose_name='Vehículo')
    aseguradora = models.ForeignKey(Aseguradora, on_delete=models.PROTECT, related_name='valores_externos', verbose_name='Aseguradora')
    valor = models.DecimalField(max_digits=14, decimal_places=0, verbose_name='Valor final')
    # Segundo valor del portal al cotizar a mano (Seguros del Estado: Elite = `valor`, Integral = `valor_2`). El
    # comparativo usa siempre `valor`.
    valor_2 = models.DecimalField(max_digits=14, decimal_places=0, null=True, blank=True, verbose_name='Segundo valor')
    # PDF de la cotización de la aseguradora: se adjunta al correo si este valor queda entre los dos más baratos.
    documento = models.FileField(upload_to=_ruta_cotizacion_manual, null=True, blank=True, verbose_name='PDF de la cotización')
    asesor = models.ForeignKey(User, on_delete=models.PROTECT, verbose_name='Registrado por')
    created_at = models.DateTimeField(auto_now_add=True, verbose_name='Fecha de registro')

    def __str__(self):
        return f'{self.vehiculo.placa} - {self.aseguradora}: ${self.valor}'

    class Meta:
        verbose_name = 'Valor de aseguradora sin bot'
        verbose_name_plural = 'Valores de aseguradoras sin bot'
        ordering = ['-id']
        default_permissions = ()


class Cotizacion(models.Model):
    vehiculo = models.ForeignKey(Vehiculo, on_delete=models.PROTECT, related_name='cotizaciones', verbose_name='Vehículo')
    tomador = models.ForeignKey(
        Client, on_delete=models.PROTECT, related_name='cotizaciones', verbose_name='Tomador',
        help_text='Dueño del vehículo al momento de esta cotización. No cambia si el vehículo cambia de '
                   'propietario después, para no alterar el historial.'
    )
    asesor = models.ForeignKey(User, on_delete=models.PROTECT, verbose_name='Asesor')
    aseguradora = models.ForeignKey(Aseguradora, on_delete=models.PROTECT, related_name='cotizaciones', verbose_name='Aseguradora')
    aseguradora_actual = models.ForeignKey(Aseguradora, on_delete=models.PROTECT, null=True, blank=True, related_name='+', verbose_name='Aseguradora actual')
    tipo_poliza = models.ForeignKey(TipoPoliza, on_delete=models.PROTECT, verbose_name='Tipo de póliza')
    # Ciudad de circulación con la que se pidió ESTA cotización: el vehículo puede cambiar de ciudad al año siguiente.
    zona_circulacion = models.ForeignKey(Municipio, on_delete=models.PROTECT, null=True, blank=True, related_name='+',
                                         verbose_name='Zona de circulación al cotizar')

    fecha_vigencia_inicio = models.DateField(null=True, blank=True, verbose_name='Fecha inicio de vigencia')
    fecha_vigencia_fin = models.DateField(null=True, blank=True, verbose_name='Fecha fin de vigencia')
    cotizacion_vigente_hasta = models.DateField(null=True, blank=True, verbose_name='La cotización de la aseguradora vale hasta')
    fecha_renovacion = models.DateField(null=True, blank=True, verbose_name='Fecha de renovación')
    tipo_vigencia = models.CharField(max_length=100, null=True, blank=True, verbose_name='Tipo de vigencia')
    meses_vigencia = models.PositiveIntegerField(null=True, blank=True, verbose_name='Meses de vigencia')

    tipo_valor_asegurado = models.CharField(max_length=100, null=True, blank=True, verbose_name='Tipo de valor asegurado')
    moneda = models.CharField(max_length=20, null=True, blank=True, verbose_name='Moneda')

    valor_asegurado = models.DecimalField(max_digits=12, decimal_places=2, default=0.00, verbose_name='Valor asegurado')
    total_valor_asegurado = models.DecimalField(max_digits=12, decimal_places=2, default=0.00, verbose_name='Total valor asegurado')
    valor_soat = models.DecimalField(max_digits=12, decimal_places=2, default=0.00, verbose_name='Valor SOAT')
    prima_total = models.DecimalField(max_digits=12, decimal_places=2, default=0.00, verbose_name='Prima total')
    valor_sin_iva = models.DecimalField(max_digits=12, decimal_places=2, default=0.00, verbose_name='Valor sin IVA')
    valor_comision = models.DecimalField(max_digits=12, decimal_places=2, default=0.00, verbose_name='Valor comisión')

    descuentos = models.DecimalField(max_digits=12, decimal_places=2, default=0.00, verbose_name='Descuentos')
    porcentaje_descuento = models.DecimalField(max_digits=5, decimal_places=2, null=True, blank=True, verbose_name='% de descuento que ofrece la aseguradora')
    fecha_descuento = models.DateField(null=True, blank=True, verbose_name='Fecha de descuento')

    medio_pago = models.CharField(max_length=20, choices=MEDIO_PAGO, default=MEDIO_PAGO[0][0], verbose_name='Medio de pago')
    fecha_pago = models.DateField(null=True, blank=True, verbose_name='Fecha de pago')
    extension_telefonica = models.CharField(max_length=20, null=True, blank=True, verbose_name='Extensión telefónica')

    estado = models.CharField(max_length=20, choices=ESTADO_COTIZACION, default=ESTADO_COTIZACION[0][0], verbose_name='Estado')
    estado_gestion = models.CharField(max_length=100, null=True, blank=True, verbose_name='Estado de gestión (GAU)')

    valor_pago_aseguradora = models.DecimalField(max_digits=12, decimal_places=2, default=0.00, verbose_name='Valor pago a aseguradora')
    fecha_pago_cartera = models.DateField(null=True, blank=True, verbose_name='Fecha de pago cartera')

    estado_bot = models.CharField(max_length=25, choices=ESTADO_BOT, default=ESTADO_BOT[0][0], verbose_name='Estado del bot')
    mensaje_bot = models.TextField(null=True, blank=True, verbose_name='Mensaje del bot')
    error_tipo = models.CharField(max_length=20, choices=ERROR_BOT_TIPO, null=True, blank=True, verbose_name='Tipo de error')
    paso_bot = models.CharField(max_length=120, null=True, blank=True, verbose_name='Paso del bot (en curso o donde falló)')
    accion_sugerida = models.TextField(null=True, blank=True, verbose_name='Qué debe hacer el asesor')
    detalle_tecnico = models.TextField(null=True, blank=True, verbose_name='Detalle técnico del error')
    # PDF de la cotización que el bot descarga del portal. Se adjunta al correo si queda entre las 2 más baratas; si no,
    # se borra a los 10 días (ver services/pdf_cotizaciones.py). Los que se enviaron al cliente se conservan.
    pdf = models.FileField(upload_to=_ruta_pdf_portal, null=True, blank=True, verbose_name='PDF de la cotización (portal)')
    pdf_descargado_en = models.DateTimeField(null=True, blank=True, verbose_name='PDF descargado el')
    pdf_enviado_en = models.DateTimeField(null=True, blank=True, verbose_name='PDF enviado al cliente el')
    documento_verificado = models.BooleanField(default=False, verbose_name='Documento verificado en aseguradora')
    fecha_nacimiento_coincide = models.BooleanField(null=True, blank=True, verbose_name='Fecha de nacimiento coincide')
    confirmacion_bot = models.BooleanField(
        null=True, blank=True,
        verbose_name='Confirmación del asesor',
        help_text='Se usa cuando el bot queda en pausa esperando una decisión (ej. fecha de nacimiento no coincide): '
                   'null = sin responder, True = continuar, False = cancelar.'
    )
    # Pasos que solo una persona puede hacer (ej. el código de 6 dígitos que Mapfre envía al celular del intermediario):
    # el bot pide ayuda con `verificacion_bot` ('captcha' o 'codigo') y espera la respuesta del asesor.
    verificacion_bot = models.CharField(max_length=10, null=True, blank=True, verbose_name='Qué necesita el bot del asesor')
    codigo_verificacion = models.CharField(max_length=10, null=True, blank=True, verbose_name='Código de verificación (temporal)')
    ejecutado_en = models.DateTimeField(null=True, blank=True, verbose_name='Fecha de ejecución del bot')

    created_at = models.DateTimeField(auto_now_add=True, verbose_name='Fecha de creación')

    def __str__(self):
        return f'{self.vehiculo.placa} - {self.aseguradora} ({self.get_estado_display()})'

    def dias_vigencia(self):
        if not self.fecha_vigencia_fin:
            return None
        return (self.fecha_vigencia_fin - date.today()).days

    def esta_vencido(self):
        dias = self.dias_vigencia()
        return dias is not None and dias < 0

    def toJSON(self):
        item = model_to_dict(self, exclude=['vehiculo', 'tomador', 'asesor', 'aseguradora', 'aseguradora_actual', 'tipo_poliza', 'created_at', 'zona_circulacion'])
        item['zona_circulacion'] = str(self.zona_circulacion) if self.zona_circulacion else None
        item['vehiculo'] = self.vehiculo.toJSON()
        # El tomador que se muestra es el de ESTA cotización, no necesariamente
        # el dueño actual del vehículo (puede haber cambiado desde entonces).
        item['vehiculo']['tomador'] = self.tomador.toJSON()
        item['asesor'] = self.asesor.toJSON()
        item['aseguradora'] = self.aseguradora.toJSON()
        item['aseguradora_actual'] = self.aseguradora_actual.toJSON() if self.aseguradora_actual else None
        item['tipo_poliza'] = self.tipo_poliza.toJSON()
        item['fecha_vigencia_inicio'] = self.fecha_vigencia_inicio.strftime('%Y-%m-%d') if self.fecha_vigencia_inicio else None
        item['fecha_vigencia_fin'] = self.fecha_vigencia_fin.strftime('%Y-%m-%d') if self.fecha_vigencia_fin else None
        item['cotizacion_vigente_hasta'] = self.cotizacion_vigente_hasta.strftime('%Y-%m-%d') if self.cotizacion_vigente_hasta else None
        item['fecha_renovacion'] = self.fecha_renovacion.strftime('%Y-%m-%d') if self.fecha_renovacion else None
        item['fecha_descuento'] = self.fecha_descuento.strftime('%Y-%m-%d') if self.fecha_descuento else None
        item['fecha_pago'] = self.fecha_pago.strftime('%Y-%m-%d') if self.fecha_pago else None
        item['fecha_pago_cartera'] = self.fecha_pago_cartera.strftime('%Y-%m-%d') if self.fecha_pago_cartera else None
        item['valor_asegurado'] = float(self.valor_asegurado)
        item['total_valor_asegurado'] = float(self.total_valor_asegurado)
        item['valor_soat'] = float(self.valor_soat)
        item['prima_total'] = float(self.prima_total)
        item['valor_sin_iva'] = float(self.valor_sin_iva)
        item['valor_comision'] = float(self.valor_comision)
        item['descuentos'] = float(self.descuentos)
        item['porcentaje_descuento'] = float(self.porcentaje_descuento) if self.porcentaje_descuento is not None else None
        item['valor_pago_aseguradora'] = float(self.valor_pago_aseguradora)
        item['medio_pago'] = {'id': self.medio_pago, 'name': self.get_medio_pago_display()}
        item['estado'] = {'id': self.estado, 'name': self.get_estado_display()}
        item['estado_bot'] = {'id': self.estado_bot, 'name': self.get_estado_bot_display()}
        item['ejecutado_en'] = self.ejecutado_en.strftime('%Y-%m-%d %H:%M') if self.ejecutado_en else None
        item['dias_vigencia'] = self.dias_vigencia()
        item['esta_vencido'] = self.esta_vencido()
        item['planes'] = [plan.toJSON() for plan in self.planes.all()]
        return item

    class Meta:
        verbose_name = 'Cotización'
        verbose_name_plural = 'Cotizaciones'
        ordering = ['-id']
        default_permissions = ()
        permissions = (
            ('view_cotizacion', 'Ver Cotización'),
            ('add_cotizacion', 'Agregar Cotización'),
            ('change_cotizacion', 'Editar Cotización'),
            ('delete_cotizacion', 'Eliminar Cotización'),
        )


class CotizacionPlan(models.Model):
    cotizacion = models.ForeignKey(Cotizacion, on_delete=models.CASCADE, related_name='planes', verbose_name='Cotización')
    nombre_plan = models.CharField(max_length=100, verbose_name='Plan')
    prima_total = models.DecimalField(max_digits=12, decimal_places=2, default=0.00, verbose_name='Prima total')

    def __str__(self):
        return f'{self.nombre_plan} - ${self.prima_total}'

    def toJSON(self):
        item = model_to_dict(self, exclude=['cotizacion'])
        item['prima_total'] = float(self.prima_total)
        return item

    class Meta:
        verbose_name = 'Plan cotizado'
        verbose_name_plural = 'Planes cotizados'
        ordering = ['id']
        default_permissions = ()
        permissions = (
            ('view_cotizacionplan', 'Ver Plan cotizado'),
            ('add_cotizacionplan', 'Agregar Plan cotizado'),
            ('change_cotizacionplan', 'Editar Plan cotizado'),
            ('delete_cotizacionplan', 'Eliminar Plan cotizado'),
        )


class Asesor(models.Model):
    """Persona que cotiza con la plataforma y recibe una comisión: un asesor de la casa (interno) o uno aliado
    que trabaja por su cuenta o con su propia empresa (externo)."""
    tipo = models.CharField(max_length=10, choices=TIPO_ASESOR, default='interno', verbose_name='Tipo de asesor')
    nombres = models.CharField(max_length=150, verbose_name='Nombres y apellidos')
    tipo_documento = models.ForeignKey(DocumentType, on_delete=models.PROTECT, verbose_name='Tipo de documento')
    documento = models.CharField(max_length=20, unique=True, verbose_name='Número de documento')
    correo = models.EmailField(max_length=100, unique=True, verbose_name='Correo')
    telefono = models.CharField(max_length=20, verbose_name='Teléfono / WhatsApp')
    ciudad = models.ForeignKey(Municipio, on_delete=models.PROTECT, null=True, blank=True, verbose_name='Ciudad')

    # Solo asesores externos con empresa propia.
    empresa = models.CharField(max_length=150, null=True, blank=True, verbose_name='Empresa')
    nit_empresa = models.CharField(max_length=20, null=True, blank=True, verbose_name='NIT de la empresa')

    porcentaje_comision = models.DecimalField(max_digits=5, decimal_places=2, default=0, verbose_name='Comisión (%)')
    fecha_vinculacion = models.DateField(default=date.today, verbose_name='Fecha de vinculación')

    # Para pagar la comisión.
    banco = models.CharField(max_length=80, null=True, blank=True, verbose_name='Banco')
    tipo_cuenta = models.CharField(max_length=10, choices=TIPO_CUENTA, null=True, blank=True, verbose_name='Tipo de cuenta')
    numero_cuenta = models.CharField(max_length=30, null=True, blank=True, verbose_name='Número de cuenta')

    # Si el asesor entra al sistema, aquí se enlaza su usuario: sus cotizaciones quedan a su nombre.
    usuario = models.OneToOneField(User, on_delete=models.SET_NULL, null=True, blank=True, related_name='asesor',
                                   verbose_name='Usuario del sistema')
    observaciones = models.TextField(null=True, blank=True, verbose_name='Observaciones')
    is_active = models.BooleanField(default=True, verbose_name='Estado')
    created_at = models.DateTimeField(auto_now_add=True, verbose_name='Fecha de registro')

    def __str__(self):
        return f'{self.nombres} ({self.get_tipo_display()})'

    def toJSON(self):
        return {
            'id': self.id,
            'tipo': self.tipo,
            'tipo_display': self.get_tipo_display(),
            'nombres': self.nombres,
            'documento': f'{self.tipo_documento.abbreviation} {self.documento}',
            'correo': self.correo,
            'telefono': self.telefono,
            'ciudad': str(self.ciudad) if self.ciudad else None,
            'empresa': self.empresa,
            'porcentaje_comision': float(self.porcentaje_comision),
            'usuario': self.usuario.username if self.usuario else None,
            'is_active': self.is_active,
        }

    class Meta:
        verbose_name = 'Asesor'
        verbose_name_plural = 'Asesores'
        ordering = ['nombres']
        default_permissions = ()
        permissions = perms_for('policies.Asesor')


class AsistenteConversacion(models.Model):
    """Una conversación del usuario con Aslani (el historial del chat). Solo la ve su dueño."""
    usuario = models.ForeignKey(User, on_delete=models.CASCADE, related_name='conversaciones_asistente', verbose_name='Usuario')
    titulo = models.CharField(max_length=80, default='Nuevo chat', verbose_name='Título')
    created_at = models.DateTimeField(auto_now_add=True, verbose_name='Creada')
    updated_at = models.DateTimeField(auto_now=True, verbose_name='Última actividad')

    def __str__(self):
        return f'{self.titulo} ({self.usuario})'

    class Meta:
        verbose_name = 'Conversación con Aslani'
        verbose_name_plural = 'Conversaciones con Aslani'
        ordering = ['-updated_at']
        default_permissions = ()


class AsistenteMensaje(models.Model):
    """Mensaje de una conversación. Solo se guardan los textos del usuario y de Aslani (no el resultado bruto de las consultas)."""
    conversacion = models.ForeignKey(AsistenteConversacion, on_delete=models.CASCADE, related_name='mensajes', verbose_name='Conversación')
    rol = models.CharField(max_length=10, choices=(('user', 'Usuario'), ('assistant', 'Aslani')), verbose_name='Quién')
    contenido = models.TextField(verbose_name='Texto')
    consultas = models.JSONField(default=list, blank=True, verbose_name='Consultas que usó Aslani')
    created_at = models.DateTimeField(auto_now_add=True, verbose_name='Fecha')

    class Meta:
        verbose_name = 'Mensaje de Aslani'
        verbose_name_plural = 'Mensajes de Aslani'
        ordering = ['id']
        default_permissions = ()


class AsistenteUso(models.Model):
    """Preguntas que un usuario le hizo a Aslani en un día (hora de Colombia): sostiene el límite diario y el indicador
    «te quedan N». Vive en la base de datos (no en memoria) para que sea exacto con varios procesos y no se pierda al reiniciar."""
    usuario = models.ForeignKey(User, on_delete=models.CASCADE, related_name='uso_asistente', verbose_name='Usuario')
    fecha = models.DateField(verbose_name='Día')
    preguntas = models.PositiveIntegerField(default=0, verbose_name='Preguntas del día')

    class Meta:
        verbose_name = 'Uso diario de Aslani'
        verbose_name_plural = 'Uso diario de Aslani'
        unique_together = ('usuario', 'fecha')
        default_permissions = ()


class AsistenteConsumo(models.Model):
    """Lo que costó UNA pregunta a Aslani con IA (suma de todas las llamadas que hizo): tokens reales y su costo en dólares."""
    usuario = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, related_name='+', verbose_name='Usuario')
    created_at = models.DateTimeField(auto_now_add=True, verbose_name='Fecha')
    modelo = models.CharField(max_length=60, verbose_name='Modelo')
    tokens_entrada = models.PositiveIntegerField(default=0, verbose_name='Tokens de entrada')
    tokens_salida = models.PositiveIntegerField(default=0, verbose_name='Tokens de salida')
    tokens_cache_lectura = models.PositiveIntegerField(default=0, verbose_name='Tokens leídos de caché')
    tokens_cache_escritura = models.PositiveIntegerField(default=0, verbose_name='Tokens escritos en caché')
    llamadas = models.PositiveSmallIntegerField(default=1, verbose_name='Llamadas al modelo')
    costo_usd = models.DecimalField(max_digits=10, decimal_places=6, default=0, verbose_name='Costo (USD)')

    class Meta:
        verbose_name = 'Consumo de Aslani'
        verbose_name_plural = 'Consumo de Aslani'
        ordering = ['-created_at']
        default_permissions = ()


class HistorialVehiculo(models.Model):
    """Trazabilidad de un vehículo: cada cambio de estado, de propietario o de ciudad de circulación (quién, cuándo, de qué a qué)."""
    vehiculo = models.ForeignKey(Vehiculo, on_delete=models.CASCADE, related_name='historial', verbose_name='Vehículo')
    tipo = models.CharField(max_length=12, choices=TIPO_EVENTO_VEHICULO, verbose_name='Qué cambió')
    anterior = models.CharField(max_length=200, blank=True, default='', verbose_name='Antes')
    nuevo = models.CharField(max_length=200, blank=True, default='', verbose_name='Después')
    nota = models.CharField(max_length=300, blank=True, default='', verbose_name='Nota')
    usuario = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, related_name='+', verbose_name='Usuario')
    created_at = models.DateTimeField(auto_now_add=True, verbose_name='Fecha')

    def toJSON(self):
        return {
            'tipo': self.tipo,
            'tipo_display': self.get_tipo_display(),
            'anterior': self.anterior,
            'nuevo': self.nuevo,
            'nota': self.nota,
            'usuario': self.usuario.username if self.usuario else None,
            'fecha': timezone.localtime(self.created_at, ZoneInfo('America/Bogota')).strftime('%Y-%m-%d %H:%M'),  # hora de Colombia
        }

    class Meta:
        verbose_name = 'Historial del vehículo'
        verbose_name_plural = 'Historial de vehículos'
        ordering = ['-created_at', '-id']
        default_permissions = ()


class Poliza(models.Model):
    """La póliza que el cliente ELIGIÓ y se generó (una fila del Excel de seguimiento). Viene de una cotización del sistema o
    del histórico importado. Guarda el propietario, la ciudad y el asesor de ESE año: no cambian si el vehículo cambia después."""
    vehiculo = models.ForeignKey(Vehiculo, on_delete=models.PROTECT, related_name='polizas', verbose_name='Vehículo')
    tomador = models.ForeignKey(Client, on_delete=models.PROTECT, related_name='polizas', verbose_name='Tomador')
    asesor = models.ForeignKey(Asesor, on_delete=models.PROTECT, related_name='polizas', verbose_name='Asesor')
    aseguradora = models.ForeignKey(Aseguradora, on_delete=models.PROTECT, related_name='polizas', verbose_name='Aseguradora')
    tipo_poliza = models.ForeignKey(TipoPoliza, on_delete=models.PROTECT, verbose_name='Tipo de póliza')
    cotizacion = models.ForeignKey(Cotizacion, on_delete=models.SET_NULL, null=True, blank=True, related_name='polizas',
                                   verbose_name='Cotización de origen')
    plan = models.CharField(max_length=80, blank=True, default='', verbose_name='Plan (extensión)')
    numero_poliza = models.CharField(max_length=50, blank=True, default='', verbose_name='Número de póliza')
    zona_circulacion = models.ForeignKey(Municipio, on_delete=models.PROTECT, related_name='+', verbose_name='Ciudad de circulación')

    fecha_renovacion = models.DateField(verbose_name='Fecha de renovación (vencimiento)')
    prima_total = models.DecimalField(max_digits=14, decimal_places=2, default=0, verbose_name='Prima total')
    valor_sin_iva = models.DecimalField(max_digits=14, decimal_places=2, default=0, verbose_name='Valor sin IVA')
    valor_comision = models.DecimalField(max_digits=14, decimal_places=2, default=0, verbose_name='Valor de comisión')
    descuentos = models.DecimalField(max_digits=14, decimal_places=2, default=0, verbose_name='Descuentos')
    fecha_descuento = models.DateField(null=True, blank=True, verbose_name='Fecha de descuento')

    # La aseguradora financia; 1 = paga la totalidad, más de 1 = cuotas mensuales que empiezan en `fecha_pago`.
    numero_cuotas = models.PositiveSmallIntegerField(default=1, verbose_name='Número de cuotas')
    fecha_pago = models.DateField(verbose_name='Fecha de pago (máxima / primera cuota)')
    estado = models.CharField(max_length=10, choices=ESTADO_POLIZA, default='generada', verbose_name='Estado')

    fecha_pago_aseguradora = models.DateField(null=True, blank=True, verbose_name='Pago de aseguradora')
    estado_comision = models.CharField(max_length=10, choices=ESTADO_COMISION, default='cartera', verbose_name='Estado de la comisión')
    fecha_pago_cartera = models.DateField(null=True, blank=True, verbose_name='Fecha de pago de la comisión (cartera)')

    observaciones = models.TextField(blank=True, default='', verbose_name='Observaciones')
    origen = models.CharField(max_length=10, choices=ORIGEN_POLIZA, default='sistema', verbose_name='Origen')
    datos_importados = models.JSONField(null=True, blank=True, verbose_name='Fila original del Excel')
    creado_por = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, related_name='+', verbose_name='Registrada por')
    created_at = models.DateTimeField(auto_now_add=True, verbose_name='Fecha de registro')
    updated_at = models.DateTimeField(auto_now=True, verbose_name='Última actualización')

    def __str__(self):
        return f'{self.vehiculo.placa} · {self.aseguradora} · vence {self.fecha_renovacion:%d/%m/%Y}'

    @property
    def forma_pago(self):
        return 'Totalidad' if self.numero_cuotas <= 1 else f'{self.numero_cuotas} cuotas'

    @property
    def porcentaje_comision(self):
        return round(float(self.valor_comision) * 100 / float(self.valor_sin_iva), 2) if self.valor_sin_iva else None

    def dias_para_vencer(self):
        return (self.fecha_renovacion - date.today()).days

    def toJSON(self):
        f = lambda d: d.strftime('%Y-%m-%d') if d else None
        tomador = self.tomador
        return {
            'id': self.id,
            'vehiculo_id': self.vehiculo_id,
            'placa': self.vehiculo.placa,
            'tomador': tomador.names,
            'documento': f'{tomador.document_type.abbreviation if tomador.document_type else ""} {tomador.dni}'.strip(),
            'celular': tomador.mobile,
            'asesor': self.asesor.nombres,
            'aseguradora': self.aseguradora.name,
            'tipo_poliza': self.tipo_poliza.name,
            'plan': self.plan,
            'numero_poliza': self.numero_poliza,
            'ciudad': str(self.zona_circulacion),
            'fecha_renovacion': f(self.fecha_renovacion),
            'dias_para_vencer': self.dias_para_vencer(),
            'prima_total': float(self.prima_total),
            'valor_sin_iva': float(self.valor_sin_iva),
            'valor_comision': float(self.valor_comision),
            'porcentaje_comision': self.porcentaje_comision,
            'descuentos': float(self.descuentos),
            'numero_cuotas': self.numero_cuotas,
            'forma_pago': self.forma_pago,
            'fecha_pago': f(self.fecha_pago),
            'estado': {'id': self.estado, 'name': self.get_estado_display()},
            'fecha_pago_aseguradora': f(self.fecha_pago_aseguradora),
            'estado_comision': {'id': self.estado_comision, 'name': self.get_estado_comision_display()},
            'fecha_pago_cartera': f(self.fecha_pago_cartera),
            'origen': self.origen,
        }

    class Meta:
        verbose_name = 'Póliza'
        verbose_name_plural = 'Pólizas'
        ordering = ['-fecha_renovacion', '-id']
        default_permissions = ()
        permissions = perms_for('policies.Poliza')


class CuotaPoliza(models.Model):
    """Una cuota mensual de una póliza financiada por la aseguradora. Solo es para hacer seguimiento y recordar al cliente:
    el dinero va directo a la aseguradora. El valor es aproximado (prima / número de cuotas); se puede ajustar."""
    poliza = models.ForeignKey(Poliza, on_delete=models.CASCADE, related_name='cuotas', verbose_name='Póliza')
    numero = models.PositiveSmallIntegerField(verbose_name='Cuota')
    fecha = models.DateField(verbose_name='Fecha de pago')
    valor = models.DecimalField(max_digits=14, decimal_places=2, default=0, verbose_name='Valor aproximado')
    pagada = models.BooleanField(default=False, verbose_name='Pagada')
    fecha_pagada = models.DateField(null=True, blank=True, verbose_name='Marcada como pagada el')

    def toJSON(self):
        return {
            'id': self.id,
            'numero': self.numero,
            'fecha': self.fecha.strftime('%Y-%m-%d'),
            'valor': float(self.valor),
            'pagada': self.pagada,
            'fecha_pagada': self.fecha_pagada.strftime('%Y-%m-%d') if self.fecha_pagada else None,
        }

    class Meta:
        verbose_name = 'Cuota de póliza'
        verbose_name_plural = 'Cuotas de pólizas'
        ordering = ['poliza', 'numero']
        unique_together = ('poliza', 'numero')
        default_permissions = ()


class CuentaCorreo(models.Model):
    """Cuenta de correo desde la que salen las cotizaciones (servidor SMTP). La contraseña se guarda cifrada y nunca
    se expone en toJSON(). En Google Workspace es una «contraseña de aplicación» de la cuenta."""
    nombre = models.CharField(max_length=100, verbose_name='Nombre de la cuenta')
    correo = models.EmailField(max_length=150, verbose_name='Correo que envía')
    nombre_remitente = models.CharField(max_length=150, blank=True, default='', verbose_name='Nombre que ve el cliente')
    servidor = models.CharField(max_length=150, default='smtp.gmail.com', verbose_name='Servidor SMTP')
    puerto = models.PositiveIntegerField(default=587, verbose_name='Puerto')
    seguridad = models.CharField(max_length=10, choices=SEGURIDAD_SMTP, default='tls', verbose_name='Seguridad')
    usuario = models.CharField(max_length=150, blank=True, default='', verbose_name='Usuario (si es distinto del correo)')
    clave = EncryptedCharField(max_length=500, blank=True, default='', verbose_name='Contraseña de aplicación')
    probada_en = models.DateTimeField(null=True, blank=True, verbose_name='Última prueba de conexión')
    prueba_ok = models.BooleanField(null=True, blank=True, verbose_name='La última prueba funcionó')
    prueba_mensaje = models.CharField(max_length=300, blank=True, default='', verbose_name='Resultado de la última prueba')
    is_active = models.BooleanField(default=True, verbose_name='Activa')
    created_at = models.DateTimeField(auto_now_add=True, verbose_name='Fecha de registro')

    def __str__(self):
        return f'{self.nombre} <{self.correo}>'

    @property
    def remitente(self):
        return f'{self.nombre_remitente} <{self.correo}>' if self.nombre_remitente else self.correo

    def toJSON(self):
        item = model_to_dict(self, exclude=['clave', 'probada_en', 'created_at'])
        item['tiene_clave'] = bool(self.clave)
        item['seguridad_display'] = self.get_seguridad_display()
        item['probada_en'] = timezone.localtime(self.probada_en, ZoneInfo('America/Bogota')).strftime('%Y-%m-%d %H:%M') if self.probada_en else None
        return item

    class Meta:
        verbose_name = 'Cuenta de correo'
        verbose_name_plural = 'Cuentas de correo'
        ordering = ['nombre']
        default_permissions = ()
        permissions = perms_for('policies.CuentaCorreo')


class PlantillaCorreo(models.Model):
    """Plantilla del correo con el que se envía la cotización al cliente. El asunto, los destinatarios y el cuerpo
    llevan variables ({cliente}, {placa}…) y bloques ({datos_vehiculo}, {comparativo}, {promocion}, {firma}) que se
    llenan al armar el correo (ver core.policies.services.correo)."""
    nombre = models.CharField(max_length=100, verbose_name='Nombre de la plantilla')
    tipo_seguro = models.CharField(max_length=20, choices=TIPO_SEGURO_PLANTILLA, default='autos', verbose_name='Tipo de seguro')
    cuenta = models.ForeignKey(CuentaCorreo, on_delete=models.PROTECT, null=True, blank=True, related_name='plantillas',
                               verbose_name='Cuenta desde la que sale el correo')
    para = models.CharField(max_length=300, default='{correo_cliente}', verbose_name='Para')
    cc = models.CharField(max_length=500, blank=True, default='', verbose_name='Con copia (CC)')
    asunto = models.CharField(max_length=300, verbose_name='Asunto')
    cuerpo = models.TextField(verbose_name='Cuerpo del correo')
    promocion_activa = models.BooleanField(default=True, verbose_name='Incluir la promoción en el correo')
    promocion_texto = models.CharField(max_length=300, blank=True, default='', verbose_name='Texto de la promoción')
    promocion_imagen = models.ImageField(upload_to='plantillas/promociones/%Y/%m', null=True, blank=True, verbose_name='Imagen de la promoción')
    promocion_aseguradora = models.ForeignKey(Aseguradora, on_delete=models.SET_NULL, null=True, blank=True, related_name='+',
                                              verbose_name='Mostrar la promoción solo si esta aseguradora está en el comparativo')
    vigencia_cotizacion_dias = models.PositiveSmallIntegerField(default=15, verbose_name='Días de vigencia de las cotizaciones')
    adjuntar_pdf = models.BooleanField(default=True, verbose_name='Adjuntar el PDF del comparativo')
    predeterminada = models.BooleanField(default=False, verbose_name='Predeterminada para su tipo de seguro')
    is_active = models.BooleanField(default=True, verbose_name='Activa')
    actualizada_por = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, related_name='+', verbose_name='Actualizada por')
    created_at = models.DateTimeField(auto_now_add=True, verbose_name='Fecha de registro')
    updated_at = models.DateTimeField(auto_now=True, verbose_name='Última actualización')

    def __str__(self):
        return self.nombre

    def toJSON(self):
        return {
            'id': self.id,
            'nombre': self.nombre,
            'tipo_seguro': self.get_tipo_seguro_display(),
            'cuenta': str(self.cuenta) if self.cuenta else None,
            'asunto': self.asunto,
            'predeterminada': self.predeterminada,
            'is_active': self.is_active,
            'actualizada_por': (self.actualizada_por.names or self.actualizada_por.username) if self.actualizada_por else None,
            'updated_at': timezone.localtime(self.updated_at, ZoneInfo('America/Bogota')).strftime('%Y-%m-%d %H:%M'),
        }

    class Meta:
        verbose_name = 'Plantilla de correo'
        verbose_name_plural = 'Plantillas de correo'
        ordering = ['tipo_seguro', '-predeterminada', 'nombre']
        default_permissions = ()
        permissions = perms_for('policies.PlantillaCorreo')


class FirmaCorreo(models.Model):
    """Firma (imagen) que cada usuario pone al final de los correos que envía."""
    usuario = models.OneToOneField(User, on_delete=models.CASCADE, related_name='firma_correo', verbose_name='Usuario')
    imagen = models.ImageField(upload_to='firmas/%Y/%m', verbose_name='Imagen de la firma')
    updated_at = models.DateTimeField(auto_now=True, verbose_name='Última actualización')

    def __str__(self):
        return f'Firma de {self.usuario}'

    class Meta:
        verbose_name = 'Firma de correo'
        verbose_name_plural = 'Firmas de correo'
        default_permissions = ()
        permissions = perms_for('policies.FirmaCorreo')


class CorreoEnviado(models.Model):
    """Registro de cada correo de cotización que se intentó enviar (enviado o con error)."""
    vehiculo = models.ForeignKey(Vehiculo, on_delete=models.CASCADE, related_name='correos', verbose_name='Vehículo')
    plantilla = models.ForeignKey(PlantillaCorreo, on_delete=models.SET_NULL, null=True, blank=True, related_name='+', verbose_name='Plantilla')
    remitente = models.CharField(max_length=200, verbose_name='De')
    para = models.CharField(max_length=500, verbose_name='Para')
    cc = models.CharField(max_length=500, blank=True, default='', verbose_name='CC')
    asunto = models.CharField(max_length=300, verbose_name='Asunto')
    adjunto = models.CharField(max_length=150, blank=True, default='', verbose_name='Adjunto')
    estado = models.CharField(max_length=10, choices=ESTADO_CORREO, default='enviado', verbose_name='Estado')
    error = models.TextField(blank=True, default='', verbose_name='Error')
    enviado_por = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, related_name='+', verbose_name='Enviado por')
    created_at = models.DateTimeField(auto_now_add=True, verbose_name='Fecha')

    class Meta:
        verbose_name = 'Correo enviado'
        verbose_name_plural = 'Correos enviados'
        ordering = ['-created_at', '-id']
        default_permissions = ()
        permissions = perms_for('policies.CorreoEnviado')
