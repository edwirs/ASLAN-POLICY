from django.db import models
from django.forms import model_to_dict
from django.utils import timezone

from core.pos.models import Client, Product, Municipio

DEATH_PLACE_CHOICES = (
    ('home', 'Casa'),
    ('hospital', 'Hospital'),
    ('external', 'Exterior'),
)

DISPOSITION_TYPE_CHOICES = (
    ('inhumation', 'Inhumación'),
    ('cremation', 'Cremación'),
)


class ServiceType(models.Model):
    AGREEMENT = 'agreement'
    PARTICULAR = 'particular'
    EXEQUIAL_PLAN = 'exequial_plan'

    code = models.SlugField(max_length=30, unique=True, verbose_name='Código')
    name = models.CharField(max_length=100, unique=True, verbose_name='Nombre')
    description = models.CharField(max_length=500, null=True, blank=True, verbose_name='Descripción')
    is_active = models.BooleanField(default=True, verbose_name='Estado')

    def __str__(self):
        return self.name

    def toJSON(self):
        return model_to_dict(self)

    class Meta:
        verbose_name = 'Tipo de servicio'
        verbose_name_plural = 'Tipos de servicio'


class ClientServiceRate(models.Model):
    client = models.ForeignKey(Client, on_delete=models.PROTECT, related_name='funeral_service_rates', verbose_name='Cliente / Entidad')
    service_type = models.ForeignKey(ServiceType, on_delete=models.PROTECT, verbose_name='Tipo de servicio')
    product = models.ForeignKey(Product, on_delete=models.PROTECT, verbose_name='Servicio')
    price = models.DecimalField(max_digits=9, decimal_places=2, default=0.00, verbose_name='Valor pactado')
    is_active = models.BooleanField(default=True, verbose_name='Estado')

    def __str__(self):
        return f'{self.client} - {self.product} (${self.price})'

    def toJSON(self):
        item = model_to_dict(self, exclude=['client', 'service_type', 'product'])
        item['client'] = self.client.toJSON()
        item['service_type'] = self.service_type.toJSON()
        item['product'] = self.product.toJSON()
        item['price'] = float(self.price)
        return item

    class Meta:
        verbose_name = 'Tarifa de servicio por cliente'
        verbose_name_plural = 'Tarifas de servicio por cliente'
        unique_together = ('client', 'product')


class FuneralClientProfile(models.Model):
    client = models.OneToOneField(Client, on_delete=models.CASCADE, related_name='funeral_profile', verbose_name='Cliente / Entidad')
    service_type = models.ForeignKey(ServiceType, on_delete=models.PROTECT, verbose_name='Tipo de servicio')

    def __str__(self):
        return f'{self.client} ({self.service_type})'

    def toJSON(self):
        item = model_to_dict(self, exclude=['client', 'service_type'])
        item['client'] = self.client.toJSON()
        item['service_type'] = self.service_type.toJSON()
        return item

    class Meta:
        verbose_name = 'Clasificación de cliente'
        verbose_name_plural = 'Clasificación de clientes'


class ServiceReception(models.Model):
    service_type = models.ForeignKey(ServiceType, on_delete=models.PROTECT, verbose_name='Tipo de servicio')
    client = models.ForeignKey(Client, on_delete=models.PROTECT, related_name='service_receptions', verbose_name='Cliente / Entidad')

    # Contactos (aplican principalmente a convenios)
    contact_1_name = models.CharField(max_length=150, null=True, blank=True, verbose_name='Nombre contacto 1')
    contact_1_phone = models.CharField(max_length=20, null=True, blank=True, verbose_name='Teléfono contacto 1')
    contact_2_name = models.CharField(max_length=150, null=True, blank=True, verbose_name='Nombre contacto 2')
    contact_2_phone = models.CharField(max_length=20, null=True, blank=True, verbose_name='Teléfono contacto 2')
    authorized_by = models.CharField(max_length=150, null=True, blank=True, verbose_name='Persona que autoriza el servicio')

    # Datos del fallecido
    deceased_name = models.CharField(max_length=150, verbose_name='Nombre del fallecido')
    deceased_document = models.CharField(max_length=20, null=True, blank=True, verbose_name='Identificación del fallecido')
    death_certificate_number = models.CharField(max_length=50, null=True, blank=True, verbose_name='Certificado de defunción')
    death_city = models.ForeignKey(Municipio, on_delete=models.PROTECT, null=True, blank=True, related_name='+', verbose_name='Ciudad de fallecimiento')
    death_place = models.CharField(max_length=20, choices=DEATH_PLACE_CHOICES, null=True, blank=True, verbose_name='Lugar de fallecimiento')
    final_destination_city = models.ForeignKey(Municipio, on_delete=models.PROTECT, null=True, blank=True, related_name='+', verbose_name='Ciudad de destino final')
    disposition_type = models.CharField(max_length=20, choices=DISPOSITION_TYPE_CHOICES, null=True, blank=True, verbose_name='Inhumación / Cremación')

    created_at = models.DateTimeField(default=timezone.now, verbose_name='Fecha de recepción')

    def __str__(self):
        return f'{self.deceased_name} - {self.client}'

    def toJSON(self):
        item = model_to_dict(self, exclude=['client', 'service_type', 'death_city', 'final_destination_city'])
        item['client'] = self.client.toJSON()
        item['service_type'] = self.service_type.toJSON()
        item['death_city'] = str(self.death_city) if self.death_city else None
        item['final_destination_city'] = str(self.final_destination_city) if self.final_destination_city else None
        item['death_place'] = self.get_death_place_display() if self.death_place else None
        item['disposition_type'] = self.get_disposition_type_display() if self.disposition_type else None
        item['created_at'] = self.created_at.strftime('%Y-%m-%d %H:%M')
        item['details'] = [d.toJSON() for d in self.details.all()]
        return item

    class Meta:
        verbose_name = 'Recepción de servicio'
        verbose_name_plural = 'Recepciones de servicio'
        ordering = ['-id']


class ServiceReceptionDetail(models.Model):
    reception = models.ForeignKey(ServiceReception, on_delete=models.CASCADE, related_name='details', verbose_name='Recepción')
    product = models.ForeignKey(Product, on_delete=models.PROTECT, verbose_name='Servicio')
    price = models.DecimalField(max_digits=9, decimal_places=2, default=0.00, verbose_name='Valor')
    authorization_number = models.CharField(max_length=50, null=True, blank=True, verbose_name='Número de autorización')

    def __str__(self):
        return f'{self.product} (${self.price})'

    def toJSON(self):
        item = model_to_dict(self, exclude=['reception', 'product'])
        item['product'] = self.product.toJSON()
        item['price'] = float(self.price)
        return item

    class Meta:
        verbose_name = 'Detalle de recepción'
        verbose_name_plural = 'Detalles de recepción'
