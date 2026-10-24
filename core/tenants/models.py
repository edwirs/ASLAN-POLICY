import environ
from django.db import models
from django_tenants.models import TenantMixin, DomainMixin
from django.db.models.signals import post_save
from django.dispatch import receiver

env = environ.Env()


class Client(TenantMixin):
    name = models.CharField(max_length=150, verbose_name='Razón social')
    nit = models.CharField(max_length=20,unique=True,verbose_name='NIT')
    email = models.EmailField(blank=True,null=True)
    phone = models.CharField(max_length=20,blank=True,null=True)
    created_on = models.DateTimeField(auto_now_add=True)
    paid_until = models.DateField(null=True,blank=True)
    on_trial = models.BooleanField(default=True)
    # Aslani (asistente con IA): el plan de cada empresa. La bolsa se renueva cada mes y no se acumula.
    aslani_ia_activa = models.BooleanField(default=True, verbose_name='Aslani con IA activa')
    aslani_preguntas_mes = models.PositiveIntegerField(default=900, verbose_name='Preguntas de Aslani por mes')
    aslani_hasta = models.DateField(null=True, blank=True, verbose_name='Aslani IA pagada hasta',
                                    help_text='Vacío = sin vencimiento. Pasada esta fecha la IA se apaga (queda el modo básico).')
    aslani_precio_cop = models.PositiveIntegerField(default=0, verbose_name='Lo que paga por Aslani al mes (COP, con IVA)')
    # Módulos contratados: lo que no está activo desaparece del menú y sus pantallas se bloquean.
    modulo_cotizador = models.BooleanField(default=True, verbose_name='Módulo Cotizador')
    modulo_asesores = models.BooleanField(default=True, verbose_name='Módulo Asesores')
    modulo_cartera = models.BooleanField(default=False, verbose_name='Módulo Cartera')
    # Suspensión manual del acceso (además de la automática por vencimiento de «paid_until»).
    PLANES = (('mensual', 'Mensual'), ('trimestral', 'Trimestral'), ('semestral', 'Semestral'), ('anual', 'Anual'))
    MESES_PLAN = {'mensual': 1, 'trimestral': 3, 'semestral': 6, 'anual': 12}
    plan = models.CharField(max_length=12, choices=PLANES, blank=True, default='', verbose_name='Plan de suscripción')
    suspendida = models.BooleanField(default=False, verbose_name='Acceso suspendido')
    nota = models.TextField(blank=True, default='', verbose_name='Notas internas')
    auto_create_schema = True

    def __str__(self):
        return self.name


class Domain(DomainMixin):
    pass


class Pago(models.Model):
    """Un pago que una empresa le hizo a ASLAN. Al registrarlo desde el panel se extiende la fecha que corresponde."""
    TIPOS = (('suscripcion', 'Suscripción'), ('aslani', 'Aslani IA'), ('otro', 'Otro'))
    empresa = models.ForeignKey(Client, on_delete=models.CASCADE, related_name='pagos', verbose_name='Empresa')
    fecha = models.DateField(verbose_name='Fecha del pago')
    tipo = models.CharField(max_length=12, choices=TIPOS, verbose_name='Concepto')
    monto_cop = models.PositiveIntegerField(verbose_name='Monto (COP, con IVA)')
    meses = models.PositiveSmallIntegerField(default=1, verbose_name='Meses que cubre')
    nota = models.CharField(max_length=200, blank=True, default='', verbose_name='Nota')
    creado = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-fecha', '-id']


class Auditoria(models.Model):
    """Quién hizo qué en el panel de la plataforma (solo se agrega, nunca se edita)."""
    fecha = models.DateTimeField(auto_now_add=True)
    accion = models.CharField(max_length=60)
    schema = models.CharField(max_length=63, blank=True, default='')
    detalle = models.CharField(max_length=300, blank=True, default='')
    ip = models.CharField(max_length=45, blank=True, default='')

    class Meta:
        ordering = ['-fecha', '-id']


class Anuncio(models.Model):
    """Aviso que ven los usuarios de las empresas (todas o una) mientras está vigente."""
    NIVELES = (('info', 'Informativo'), ('aviso', 'Aviso'), ('urgente', 'Urgente'))
    titulo = models.CharField(max_length=80)
    mensaje = models.CharField(max_length=400)
    nivel = models.CharField(max_length=8, choices=NIVELES, default='info')
    schema = models.CharField(max_length=63, blank=True, default='', help_text='Vacío = todas las empresas.')
    desde = models.DateField()
    hasta = models.DateField()
    activo = models.BooleanField(default=True)

    class Meta:
        ordering = ['-desde', '-id']


class AccesoPlataforma(models.Model):
    """Acceso del dueño al panel cuando ya se cambió desde el panel (si no existe, rige lo de .env.secrets).
    Guarda la clave cifrada, el secreto de la verificación en dos pasos y las direcciones IP permitidas."""
    usuario = models.CharField(max_length=60)
    clave_hash = models.CharField(max_length=200)
    totp_secreto = models.CharField(max_length=64, blank=True, default='')
    totp_activo = models.BooleanField(default=False)
    ips_permitidas = models.CharField(max_length=300, blank=True, default='', help_text='Separadas por coma. Vacío = cualquiera.')
    actualizado = models.DateTimeField(auto_now=True)

# Este signal se dispara justo después de que se crea una nueva empresa (Client)
@receiver(post_save, sender=Client)
def create_default_domain(sender, instance, created, **kwargs):
    if created:
        # Asume que el dominio será 'schema_name.critera.online'
        # Puedes cambiar 'critera.online' por tu dominio principal
        BASE_DOMAIN = env("BASE_DOMAIN", default="aslantecnologia.online")
        # Un nombre de host no admite «_» (Django lo rechaza y la empresa no abriría): el guion bajo del esquema pasa a guion.
        domain_name = f"{instance.schema_name.replace('_', '-')}.{BASE_DOMAIN}"
        
        # Crea el objeto Domain asociado al tenant recién creado
        Domain.objects.create(
            domain=domain_name, 
            tenant=instance, 
            is_primary=True
        )