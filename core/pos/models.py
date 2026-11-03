import os
from datetime import datetime

from django.db import models
from django.db.models import Sum, FloatField
from django.db.models.functions import Coalesce
from django.forms import model_to_dict
from decimal import Decimal, ROUND_HALF_UP
from zoneinfo import ZoneInfo
from django.utils import timezone

from config import settings
from core.pos.choices import GENDER
from core.pos.choices import PAYMENTMETHODS
from core.pos.choices import TRANSFERMETHODS
from core.pos.choices import EXPENSES
from core.pos.choices import SERVICE_TYPE
from core.pos.choices import TYPETMETHODS
from core.pos.choices import TIPO_CONTRATO
from core.pos.choices import PERIODO_NOMINA
from core.pos.choices import STATUS_CHOICES
from core.pos.choices import EMPLOYEE_TRANSACTION_CHOICES
from core.pos.choices import AUTORIZATION_DISCOUNT
from core.pos.choices import PERSON_TYPE
from core.pos.choices import TAX_RESPONSIBILITY
from core.pos.choices import CREDIT_NOTE_OPERATION_TYPE
from core.pos.choices import CREDIT_NOTE_CORRECTION_CONCEPT
from core.pos.choices import FACTUS_ENVIRONMENT
from core.user.models import User

class Departamento(models.Model):
    nombre = models.CharField(max_length=100)
    codigo = models.CharField(max_length=10, unique=True)

    def __str__(self):
        return self.nombre


class Municipio(models.Model):
    departamento = models.ForeignKey(Departamento, on_delete=models.CASCADE, related_name='municipios')
    nombre = models.CharField(max_length=100)
    codigo = models.CharField(max_length=10, unique=True)

    def __str__(self):
        # AQUÍ LOGRAS EL FORMATO QUE NECESITAS AUTOMÁTICAMENTE
        return f"{self.departamento.nombre} - {self.nombre}"

class Category(models.Model):
    name = models.CharField(max_length=50, unique=True, verbose_name='Nombre')
    description = models.CharField(max_length=500, null=True, blank=True, verbose_name='Descripción')
    is_active = models.BooleanField(default=True, verbose_name='Estado')

    def __str__(self):
        return self.name

    def toJSON(self):
        item = model_to_dict(self)
        return item

    class Meta:
        verbose_name = 'Categoría'
        verbose_name_plural = 'Categorías'


class Product(models.Model):
    name = models.CharField(max_length=100, verbose_name='Nombre')
    code = models.CharField(max_length=20, unique=True, verbose_name='Código')
    barcode = models.CharField(max_length=50, null=True, blank=True, verbose_name='Código de Barras')
    description = models.CharField(max_length=500, null=True, blank=True, db_index=True, verbose_name='Descripción')
    category = models.ForeignKey(Category, on_delete=models.PROTECT, verbose_name='Categoría')
    price = models.DecimalField(max_digits=9, decimal_places=2, default=0.00, verbose_name='Precio de Compra')
    pvp = models.DecimalField(max_digits=9, decimal_places=2, default=0.00, verbose_name='Precio de Venta')
    image = models.ImageField(upload_to='product/%Y/%m/%d', null=True, blank=True, verbose_name='Imagen')
    is_service = models.BooleanField(default=False, verbose_name='¿Sin Inventario?')
    with_tax = models.BooleanField(default=True, verbose_name='¿Se cobra impuesto?')
    stock = models.DecimalField(max_digits=9, decimal_places=2, default=0.00, verbose_name='Stock')
    is_active = models.BooleanField(default=True, verbose_name='Estado')

    def __str__(self):
        return self.get_full_name()

    def get_full_name(self):
        return f'{self.code} - {self.name} ({self.category.name})'

    def get_short_name(self):
        return f'{self.name} ({self.category.name})'

    def get_image(self):
        if self.image:
            return f'{settings.MEDIA_URL}{self.image}'
        return f'{settings.STATIC_URL}img/default/empty.png'

    def toJSON(self):
        item = model_to_dict(self)
        item['full_name'] = self.get_full_name()
        item['short_name'] = self.get_short_name()
        item['category'] = self.category.toJSON()
        item['price'] = float(self.price)
        item['pvp'] = float(self.pvp)
        item['stock'] = float(self.stock) 
        item['image'] = self.get_image()
        return item

    class Meta:
        verbose_name = 'Producto'
        verbose_name_plural = 'Productos'


class Company(models.Model):
    name = models.CharField(max_length=50, verbose_name='Razón social')
    ruc = models.CharField(max_length=13, verbose_name='Número de RUC')
    address = models.CharField(max_length=200, verbose_name='Dirección')
    mobile = models.CharField(max_length=10, verbose_name='Teléfono celular')
    phone = models.CharField(max_length=10, verbose_name='Teléfono convencional')
    email = models.CharField(max_length=50, verbose_name='Email')
    website = models.CharField(max_length=250, verbose_name='Dirección de página web')
    description = models.CharField(max_length=500, null=True, blank=True, verbose_name='Descripción')
    iva = models.DecimalField(default=0.00, decimal_places=2, max_digits=9, verbose_name='IVA')
    image = models.ImageField(null=True, blank=True, upload_to='company/%Y/%m/%d', verbose_name='Logotipo de la empresa')
    is_active = models.BooleanField(default=True, verbose_name='Estado')
    enable_barcode_reader = models.BooleanField(
        default=False,
        verbose_name='Activar lector de código de barras'
    )

    def __str__(self):
        return self.name

    def get_iva(self):
        return float(self.iva)

    def get_image(self):
        if self.image:
            # Ruta absoluta en el disco para que xhtml2pdf la lea sin problemas
            return os.path.join(settings.MEDIA_ROOT, self.image.name)
        return os.path.join(settings.STATIC_URL, 'img/default/empty.png')

    def toJSON(self):
        item = model_to_dict(self)
        item['image'] = self.get_image()
        item['iva'] = float(self.iva)
        return item

    class Meta:
        verbose_name = 'Compañia'
        verbose_name_plural = 'Compañias'
        default_permissions = ()
        permissions = (
            ('view_company', 'Can view Empresa'),
        )

class DocumentType(models.Model):
    name = models.CharField(max_length=100, verbose_name='Nombre')
    abbreviation = models.CharField(max_length=10, unique=True, verbose_name='Acrónimo')
    code = models.CharField(max_length=10, unique=True, verbose_name='Código DIAN')
    is_active = models.BooleanField(default=True, verbose_name='Estado')

    def toJSON(self):
        item = {
            'id': self.id,
            'name': self.name,
            'abbreviation': self.abbreviation,
            'code': self.code,
            'is_active': self.is_active
        }
        return item

    def __str__(self):
        return f"{self.name} ({self.abbreviation})"

    class Meta:
        verbose_name = 'Tipo de Documento'
        verbose_name_plural = 'Tipos de Documentos'
        ordering = ['id']

class Client(models.Model):
    document_type = models.ForeignKey(DocumentType, on_delete=models.PROTECT, verbose_name='Tipo de documento')
    dni = models.CharField(max_length=20, unique=True, verbose_name='Número de documento')
    dv = models.CharField(max_length=1, null=True, blank=True, verbose_name='Dígito de verificación')
    
    person_type = models.CharField(max_length=20, choices=PERSON_TYPE, default=PERSON_TYPE[0][0], verbose_name='Tipo de persona')
    tax_responsibility = models.CharField(max_length=30, choices=TAX_RESPONSIBILITY, default=TAX_RESPONSIBILITY[0][0], verbose_name='Responsabilidad tributaria')
    
    names = models.CharField(max_length=150, verbose_name='Nombre o Razón social')
    commercial_name = models.CharField(max_length=150, null=True, blank=True, verbose_name='Nombre comercial')
    
    gender = models.CharField(max_length=50, choices=GENDER, default=GENDER[0][0], verbose_name='Género')
    birthdate = models.DateField(default=datetime.now, verbose_name='Fecha de nacimiento')
    
    country = models.CharField(max_length=100, default='Colombia', verbose_name='País')
    municipality = models.ForeignKey(Municipio, on_delete=models.PROTECT, null=True, blank=True, verbose_name='Municipio / Ciudad')
    address = models.CharField(max_length=500, null=True, blank=True, verbose_name='Dirección')
    
    mobile = models.CharField(max_length=10, null=True, blank=True, verbose_name='Teléfono')
    phone = models.CharField(max_length=20, null=True, blank=True, verbose_name='Otro celular')
    email = models.CharField(max_length=50, null=True, blank=True, verbose_name='Email')
    email_secundario = models.CharField(max_length=100, null=True, blank=True, verbose_name='Otro correo')
    # Solo para empresas (NIT): la persona dueña de la empresa. Opcionales.
    propietario_documento = models.CharField(max_length=20, null=True, blank=True, verbose_name='Cédula del propietario')
    propietario_nombre = models.CharField(max_length=150, null=True, blank=True, verbose_name='Nombre del propietario de la empresa')
    is_active = models.BooleanField(default=True, verbose_name='Estado')

    def __str__(self):
        return self.get_full_name()

    @property
    def es_empresa(self):
        return bool(self.document_type and self.document_type.abbreviation == 'NIT')

    def get_full_name(self):
        doc_abbr = self.document_type.abbreviation if self.document_type else ''
        if self.dv:
            return f'{self.names} - {doc_abbr}: {self.dni}-{self.dv}'
        return f'{self.names} - {doc_abbr}: {self.dni}'

    def birthdate_format(self):
        return self.birthdate.strftime('%Y-%m-%d')

    def toJSON(self):
        item = model_to_dict(self)
        item['text'] = self.get_full_name()
        item['document_type'] = self.document_type.toJSON() if self.document_type else None
        item['person_type'] = {'id': self.person_type, 'name': self.get_person_type_display()}
        item['tax_responsibility'] = {'id': self.tax_responsibility, 'name': self.get_tax_responsibility_display()}
        item['gender'] = {'id': self.gender, 'name': self.get_gender_display()}
        item['birthdate'] = self.birthdate.strftime('%Y-%m-%d')
        if self.municipality:
            item['municipality'] = {
                'id': self.municipality.id,
                'name': str(self.municipality), # Esto usará el __str__ de Municipio (DEPTO - Mun)
                'code': self.municipality.codigo # El código necesario para Factus
            }
        else:
            item['municipality'] = None
        return item

    class Meta:
        verbose_name = 'Cliente'
        verbose_name_plural = 'Clientes'
        ordering = ['id']
        default_permissions = ()
        permissions = (
            ('view_client', 'Ver Cliente'),
            ('add_client', 'Agregar Cliente'),
            ('change_client', 'Editar Cliente'),
            ('delete_client', 'Eliminar Cliente'),
        )

class ClientContact(models.Model):
    client = models.ForeignKey(Client, on_delete=models.CASCADE, related_name='contacts', verbose_name="Cliente")
    names = models.CharField(max_length=150, verbose_name="Nombres y Apellidos")
    email = models.EmailField(verbose_name="Correo electrónico")
    position = models.CharField(max_length=100, blank=True, null=True, verbose_name="Cargo")
    phone = models.CharField(max_length=20, blank=True, null=True, verbose_name="Teléfono")

    def __str__(self):
        return f"{self.names} ({self.client.names})"

    class Meta:
        verbose_name = "Contacto de Cliente"
        verbose_name_plural = "Contactos de Clientes"

class Provider(models.Model):
    names = models.CharField(max_length=150, verbose_name='Nombre')
    dni = models.CharField(max_length=13, unique=True, verbose_name='Número de identificacion')
    gender = models.CharField(max_length=50, choices=GENDER, default=GENDER[0][0], verbose_name='Genero')
    mobile = models.CharField(max_length=10, null=True, blank=True, verbose_name='Teléfono')
    email = models.CharField(max_length=50, null=True, blank=True, verbose_name='Email')
    address = models.CharField(max_length=500, null=True, blank=True, verbose_name='Dirección')
    is_active = models.BooleanField(default=True, verbose_name='Estado')

    def __str__(self):
        return self.get_full_name()

    def get_full_name(self):
        return f'{self.names} ({self.dni})'

    def toJSON(self):
        item = model_to_dict(self)
        item['text'] = self.get_full_name()
        item['gender'] = {'id': self.gender, 'name': self.get_gender_display()}
        return item

    class Meta:
        verbose_name = 'Proveedor'
        verbose_name_plural = 'Proveedores'

class Sale(models.Model):
    company = models.ForeignKey(Company, on_delete=models.PROTECT, verbose_name='Compañia')
    client = models.ForeignKey(Client, on_delete=models.PROTECT, verbose_name='Cliente')
    employee = models.ForeignKey(User, on_delete=models.PROTECT, verbose_name='Empleado')
    creation_date = models.DateTimeField(auto_now_add=True, verbose_name='Fecha y hora de registro')
    date_joined = models.DateField(default=datetime.now, verbose_name='Fecha de registro')
    subtotal_12 = models.DecimalField(max_digits=9, decimal_places=2, default=0.00, verbose_name='Subtotal 12%')
    subtotal_12_sin_iva = models.DecimalField(max_digits=9, decimal_places=2, default=0.00, verbose_name='Valor Bruto')
    subtotal_0 = models.DecimalField(max_digits=9, decimal_places=2, default=0.00, verbose_name='Subtotal 0%')
    dscto = models.DecimalField(max_digits=9, decimal_places=2, default=0.00, verbose_name='Descuento')
    total_dscto = models.DecimalField(max_digits=9, decimal_places=2, default=0.00, verbose_name='Valor del descuento')
    iva = models.DecimalField(max_digits=9, decimal_places=2, default=0.00, verbose_name='Iva')
    total_iva = models.DecimalField(max_digits=9, decimal_places=2, default=0.00, verbose_name='Valor de iva')
    total = models.DecimalField(max_digits=9, decimal_places=2, default=0.00, verbose_name='Total a pagar')
    cash = models.DecimalField(max_digits=9, decimal_places=2, null=True, default=0.00, verbose_name='Efectivo recibido')
    change = models.DecimalField(max_digits=9, decimal_places=2, null=True, default=0.00, verbose_name='Cambio')
    paymentmethod = models.CharField(max_length=50, choices=PAYMENTMETHODS, default=PAYMENTMETHODS[0][0], verbose_name='Método de pago')
    transfermethods = models.CharField(max_length=50, choices=TRANSFERMETHODS, default=TRANSFERMETHODS[0][0], verbose_name='Tipo transferencia', null=True)
    typemethods = models.CharField(max_length=50, choices=TYPETMETHODS, default=TYPETMETHODS[0][0], verbose_name='Tipo pago', null=True)
    autorization_discount = models.CharField(max_length=50, choices=AUTORIZATION_DISCOUNT, default=AUTORIZATION_DISCOUNT[0][0], verbose_name='Autorización Descuento', null=True)
    discount_value = models.DecimalField(max_digits=9, decimal_places=2, default=0.00, verbose_name='Valor Descuento', null = True)
    expiration_date = models.DateField(null = True, blank=True , verbose_name='Fecha de vencimiento')
    service_type = models.CharField(max_length=50, choices=SERVICE_TYPE, default=SERVICE_TYPE[0][0], verbose_name='Tipo Servicio', null=True)
    delivered = models.BooleanField(default=False, verbose_name='Entregado')
    propina = models.DecimalField(max_digits=9, decimal_places=2, default=0.00, verbose_name='Propina')
    nequi_value = models.DecimalField(max_digits=9, decimal_places=2, default=0.00, verbose_name='Valor Nequi')
    daviplata_value = models.DecimalField(max_digits=9, decimal_places=2, default=0.00, verbose_name='Valor Daviplata')
    description = models.CharField(max_length=500, null=True, blank=True, verbose_name='Descripción')
    is_active = models.BooleanField(default=True, verbose_name='Estado')
    # campos para integrar con Factus
    factus_invoice_id = models.CharField(max_length=50, null=True, blank=True)
    factus_status = models.CharField(max_length=20, null=True, blank=True)
    factus_pdf_url = models.URLField(max_length=500, null=True, blank=True)
    factus_xml_url = models.URLField(max_length=500, null=True, blank=True)
    factus_cufe = models.TextField(null=True, blank=True)
    factus_resolution = models.TextField(null=True, blank=True)
    factus_prefix = models.TextField(null=True, blank=True)
    factus_range_from = models.TextField(null=True, blank=True)
    factus_range_to = models.TextField(null=True, blank=True)
    factus_date_from = models.TextField(null=True, blank=True)
    factus_date_to = models.TextField(null=True, blank=True)
    factus_qr_url = models.URLField(null=True, blank=True) 
    is_electronicinvoice = models.BooleanField(default=False, verbose_name='Electronica')
    email_sent_count = models.PositiveIntegerField(default=0, verbose_name="Correos enviados")
    attachment = models.FileField(upload_to='sales/attachments/', null=True, blank=True, verbose_name="Archivo adjunto")

    def __str__(self):
        return self.client.get_full_name()

    def get_subtotal_without_taxes(self):
        return float(self.saledetail_set.filter().aggregate(result=Coalesce(Sum('subtotal'), 0.00, output_field=FloatField())).get('result'))

    def get_full_subtotal(self):
        return float(self.subtotal_0) + float(self.subtotal_12)

    def calculate_invoice(self):
        self.subtotal_0 = float(self.saledetail_set.filter(product__with_tax=False).aggregate(result=Coalesce(Sum('total'), 0.00, output_field=FloatField())).get('result'))
        self.subtotal_12 = float(self.saledetail_set.filter(product__with_tax=True).aggregate(result=Coalesce(Sum('total'), 0.00, output_field=FloatField())).get('result'))
        subtotal = float(self.get_full_subtotal())
        discount_rate = float(self.dscto or 0)
        self.total_dscto = subtotal * discount_rate

        # El IVA se calcula sobre la base ya descontada. El total de una venta
        # siempre debe incluirlo; de lo contrario difiere del total validado por DIAN/Factus.
        iva_before_global_discount = float(self.saledetail_set.filter(product__with_tax=True).aggregate(result=Coalesce(Sum('total_iva'), 0.00, output_field=FloatField())).get('result'))
        self.total_iva = iva_before_global_discount * (1 - discount_rate)
        self.subtotal_12_sin_iva = self.subtotal_12 * (1 - discount_rate)
        self.total = (subtotal - float(self.total_dscto)) + float(self.total_iva)
        self.save()

    def calculate_detail(self):
        for detail in self.saledetail_set.filter():
            detail.price = float(detail.price)
            detail.iva = float(self.iva)
            detail.price_with_vat = detail.price + (detail.price * detail.iva)
            detail.subtotal = detail.price * detail.cant
            detail.total_dscto = detail.subtotal * float(detail.dscto)
            detail.total_iva = (detail.subtotal - detail.total_dscto) * detail.iva
            detail.total = detail.subtotal - detail.total_dscto
            detail.save()

    def total_paid(self):
        result = self.salecreditpayment_set.aggregate(s=Sum('total'))['s']
        return result if result else 0

    def pending(self):
        return self.total - self.total_paid()

    def toJSON(self):
        item = model_to_dict(self, exclude=['company', 'creation_date'])
        item['client'] = self.client.toJSON()
        item['employee'] = self.employee.toJSON()
        item['date_joined'] = self.date_joined.strftime('%Y-%m-%d')
        item['date_joined'] = self.date_joined.strftime('%Y-%m-%d')
        local_date = self.creation_date.astimezone(ZoneInfo("America/Bogota"))
        item['creation_time'] = local_date.strftime('%I:%M:%S %p')
        item['datetime_full'] = local_date.strftime('%Y-%m-%d %I:%M %p')
        item['subtotal_12'] = float(self.subtotal_12)
        item['subtotal_12_sin_iva'] = float(self.subtotal_12_sin_iva)
        item['subtotal_0'] = float(self.subtotal_0)
        item['subtotal'] = float(self.get_subtotal_without_taxes())
        item['dscto'] = float(self.dscto)
        item['total_dscto'] = float(self.total_dscto)
        item['iva'] = float(self.iva)
        item['total_iva'] = float(self.total_iva)
        item['total'] = float(self.total)
        item['cash'] = float(self.cash)
        item['change'] = float(self.change)
        item['paymentmethod'] = {'id': self.paymentmethod, 'name': self.get_paymentmethod_display()}
        item['transfermethods'] = {'id': self.transfermethods, 'name': self.get_transfermethods_display()}
        item['autorization_discount'] = {'id': self.autorization_discount, 'name': self.get_autorization_discount_display()}
        item['discount_value'] = float(self.discount_value or 0)
        item['typemethods'] = {'id': self.typemethods, 'name': self.get_typemethods_display()}
        item['expiration_date'] = (self.expiration_date.strftime('%Y-%m-%d') if self.expiration_date else None)
        item['service_type'] = {'id': self.service_type, 'name': self.get_service_type_display()}
        item['delivered'] = self.delivered
        item['total_paid'] = float(self.total_paid())
        item['pending'] = float(self.pending())
        item['propina'] = float(self.propina)
        item['nequi_value'] = float(self.nequi_value)
        item['daviplata_value'] = float(self.daviplata_value)
        item['factus_invoice_id'] = self.factus_invoice_id
        item['factus_status'] = self.factus_status
        item['factus_pdf_url'] = self.factus_pdf_url
        item['factus_xml_url'] = self.factus_xml_url
        item['factus_cufe'] = self.factus_cufe
        item['factus_resolution'] = self.factus_resolution
        item['factus_qr_url'] = self.factus_qr_url
        item['is_electronicinvoice'] = self.is_electronicinvoice
        item['email_sent_count'] = self.email_sent_count
        if self.attachment:
            item['attachment'] = self.attachment.url
        else:
            item['attachment'] = None

        return item

    class Meta:
        verbose_name = 'Venta'
        verbose_name_plural = 'Ventas'
        default_permissions = ()
        permissions = (
            ('view_sale', 'Can view Venta'),
            ('add_sale', 'Can add Venta'),
            ('add_bar', 'Can add Venta Barra'),
            ('delete_sale', 'Can delete Venta'),
            ('view_sale_client', 'Can view_sale_client Venta'),
            ('delivered_sale', 'Can delivered Venta'),
            ('discounts_sale', 'Can discounts Venta'),
            ('report_sales_menu', 'can view sales report'),
            ('report_employee_menu', 'can view sales employee report'),
            ('report_employee_debe', 'can view sales employee debe report'),
            ('report_employee_gain', 'can view employee gain report'),
            ('sale_by_product', 'can view sales by product report'),
            ('list_employee', 'can view list employee'),
        )


class SaleDetail(models.Model):
    sale = models.ForeignKey(Sale, on_delete=models.CASCADE)
    product = models.ForeignKey(Product, on_delete=models.PROTECT)
    cant = models.IntegerField(default=0)
    price = models.DecimalField(max_digits=9, decimal_places=2, default=0.00)
    price_with_vat = models.DecimalField(max_digits=9, decimal_places=2, default=0.00)
    subtotal = models.DecimalField(max_digits=9, decimal_places=2, default=0.00)
    iva = models.DecimalField(max_digits=9, decimal_places=2, default=0.00)
    total_iva = models.DecimalField(max_digits=9, decimal_places=2, default=0.00)
    dscto = models.DecimalField(max_digits=9, decimal_places=2, default=0.00)
    total_dscto = models.DecimalField(max_digits=9, decimal_places=2, default=0.00)
    total = models.DecimalField(max_digits=9, decimal_places=2, default=0.00)
    is_active = models.BooleanField(default=True, verbose_name='Estado')

    def __str__(self):
        return self.product.name

    def get_iva_percent(self):
        return int(self.iva * 100)

    def toJSON(self):
        item = model_to_dict(self, exclude=['sale'])
        item['product'] = self.product.toJSON()
        item['price'] = float(self.price)
        item['price_with_vat'] = float(self.price_with_vat)
        item['subtotal'] = float(self.subtotal)
        item['iva'] = float(self.subtotal)
        item['total_iva'] = float(self.subtotal)
        item['dscto'] = float(self.dscto)
        item['total_dscto'] = float(self.total_dscto)
        item['total'] = float(self.total)
        return item

    class Meta:
        verbose_name = 'Detalle de Venta'
        verbose_name_plural = 'Detalle de Ventas'
        default_permissions = ()

class Price(models.Model):
    company = models.ForeignKey(Company, on_delete=models.PROTECT, verbose_name='Compañia')
    client = models.ForeignKey(Client, on_delete=models.PROTECT, verbose_name='Cliente')
    employee = models.ForeignKey(User, on_delete=models.PROTECT, verbose_name='Empleado')
    creation_date = models.DateTimeField(auto_now_add=True, verbose_name='Fecha y hora de registro')
    date_joined = models.DateField(default=datetime.now, verbose_name='Fecha de registro')
    subtotal_12 = models.DecimalField(max_digits=9, decimal_places=2, default=0.00, verbose_name='Subtotal 12%')
    subtotal_0 = models.DecimalField(max_digits=9, decimal_places=2, default=0.00, verbose_name='Subtotal 0%')
    dscto = models.DecimalField(max_digits=9, decimal_places=2, default=0.00, verbose_name='Descuento')
    total_dscto = models.DecimalField(max_digits=9, decimal_places=2, default=0.00, verbose_name='Valor del descuento')
    iva = models.DecimalField(max_digits=9, decimal_places=2, default=0.00, verbose_name='Iva')
    total_iva = models.DecimalField(max_digits=9, decimal_places=2, default=0.00, verbose_name='Valor de iva')
    total = models.DecimalField(max_digits=9, decimal_places=2, default=0.00, verbose_name='Total a pagar')
    cash = models.DecimalField(max_digits=9, decimal_places=2, default=0.00, verbose_name='Efectivo recibido')
    change = models.DecimalField(max_digits=9, decimal_places=2, default=0.00, verbose_name='Cambio')
    is_active = models.BooleanField(default=True, verbose_name='Estado')

    def __str__(self):
        return self.client.get_full_name()

    def get_subtotal_without_taxes(self):
        return float(self.pricedetail_set.filter().aggregate(result=Coalesce(Sum('subtotal'), 0.00, output_field=FloatField())).get('result'))

    def get_full_subtotal(self):
        return float(self.subtotal_0) + float(self.subtotal_12)

    def calculate_invoice(self):
        self.subtotal_0 = float(self.pricedetail_set.filter(product__with_tax=False).aggregate(result=Coalesce(Sum('total'), 0.00, output_field=FloatField())).get('result'))
        self.subtotal_12 = float(self.pricedetail_set.filter(product__with_tax=True).aggregate(result=Coalesce(Sum('total'), 0.00, output_field=FloatField())).get('result'))
        self.total_iva = float(self.pricedetail_set.filter(product__with_tax=True).aggregate(result=Coalesce(Sum('total_iva'), 0.00, output_field=FloatField())).get('result'))
        self.total_dscto = float(self.get_full_subtotal()) * float(self.dscto)
        self.total = float(self.get_full_subtotal()) + float(self.total_iva) - float(self.total_dscto)
        self.save()

    def calculate_detail(self):
        for detail in self.pricedetail_set.filter():
            detail.price = float(detail.price)
            detail.iva = float(self.iva)
            detail.price_with_vat = detail.price + (detail.price * detail.iva)
            detail.subtotal = detail.price * detail.cant
            detail.total_dscto = detail.subtotal * float(detail.dscto)
            detail.total_iva = (detail.subtotal - detail.total_dscto) * detail.iva
            detail.total = detail.subtotal - detail.total_dscto
            detail.save()

    def toJSON(self):
        item = model_to_dict(self, exclude=['company', 'creation_date'])
        item['client'] = self.client.toJSON()
        item['employee'] = self.employee.toJSON()
        item['date_joined'] = self.date_joined.strftime('%Y-%m-%d')
        item['subtotal_12'] = float(self.subtotal_12)
        item['subtotal_0'] = float(self.subtotal_0)
        item['subtotal'] = float(self.get_subtotal_without_taxes())
        item['dscto'] = float(self.dscto)
        item['total_dscto'] = float(self.total_dscto)
        item['iva'] = float(self.iva)
        item['total_iva'] = float(self.total_iva)
        item['total'] = float(self.total)
        item['cash'] = float(self.cash)
        item['change'] = float(self.change)
        return item

    class Meta:
        verbose_name = 'Cotización'
        verbose_name_plural = 'Cotizaciones'
        default_permissions = ()
        permissions = (
            ('view_price', 'Can view Cotizacion'),
            ('add_price', 'Can add Cotizacion'),
            ('delete_price', 'Can delete Cotizacion'),
            ('view_price_client', 'Can view_price_client Cotizacion'),
        )


class PriceDetail(models.Model):
    price_id = models.ForeignKey(Price, on_delete=models.CASCADE)
    product = models.ForeignKey(Product, on_delete=models.PROTECT)
    cant = models.IntegerField(default=0)
    price = models.DecimalField(max_digits=9, decimal_places=2, default=0.00)
    price_with_vat = models.DecimalField(max_digits=9, decimal_places=2, default=0.00)
    subtotal = models.DecimalField(max_digits=9, decimal_places=2, default=0.00)
    iva = models.DecimalField(max_digits=9, decimal_places=2, default=0.00)
    total_iva = models.DecimalField(max_digits=9, decimal_places=2, default=0.00)
    dscto = models.DecimalField(max_digits=9, decimal_places=2, default=0.00)
    total_dscto = models.DecimalField(max_digits=9, decimal_places=2, default=0.00)
    total = models.DecimalField(max_digits=9, decimal_places=2, default=0.00)
    is_active = models.BooleanField(default=True, verbose_name='Estado')

    def __str__(self):
        return self.product.name

    def get_iva_percent(self):
        return int(self.iva * 100)

    def toJSON(self):
        item = model_to_dict(self, exclude=['price'])
        item['product'] = self.product.toJSON()
        item['price'] = float(self.price)
        item['price_with_vat'] = float(self.price_with_vat)
        item['subtotal'] = float(self.subtotal)
        item['iva'] = float(self.subtotal)
        item['total_iva'] = float(self.subtotal)
        item['dscto'] = float(self.dscto)
        item['total_dscto'] = float(self.total_dscto)
        item['total'] = float(self.total)
        return item

    class Meta:
        verbose_name = 'Detalle de Cotización'
        verbose_name_plural = 'Detalle de Cotización'
        default_permissions = ()


class Buy(models.Model):
    company = models.ForeignKey(Company, on_delete=models.PROTECT, verbose_name='Compañia')
    provider = models.ForeignKey(Provider, on_delete=models.PROTECT, verbose_name='Proveedor')
    employee = models.ForeignKey(User, on_delete=models.PROTECT, verbose_name='Empleado')
    creation_date = models.DateTimeField(auto_now_add=True, verbose_name='Fecha y hora de registro')
    date_joined = models.DateField(default=datetime.now, verbose_name='Fecha de registro')
    subtotal_12 = models.DecimalField(max_digits=9, decimal_places=2, default=0.00, verbose_name='Subtotal 12%')
    subtotal_0 = models.DecimalField(max_digits=9, decimal_places=2, default=0.00, verbose_name='Subtotal 0%')
    dscto = models.DecimalField(max_digits=9, decimal_places=2, default=0.00, verbose_name='Descuento')
    total_dscto = models.DecimalField(max_digits=9, decimal_places=2, default=0.00, verbose_name='Valor del descuento')
    iva = models.DecimalField(max_digits=9, decimal_places=2, default=0.00, verbose_name='Iva')
    total_iva = models.DecimalField(max_digits=9, decimal_places=2, default=0.00, verbose_name='Valor de iva')
    total = models.DecimalField(max_digits=9, decimal_places=2, default=0.00, verbose_name='Total a pagar')
    cash = models.DecimalField(max_digits=9, decimal_places=2, default=0.00, verbose_name='Efectivo pagado')
    change = models.DecimalField(max_digits=9, decimal_places=2, default=0.00, verbose_name='Cambio')
    paymentmethod = models.CharField(max_length=50, choices=PAYMENTMETHODS, default=PAYMENTMETHODS[0][0], verbose_name='Método de pago')
    transfermethods = models.CharField(max_length=50, choices=TRANSFERMETHODS, default=TRANSFERMETHODS[0][0], verbose_name='Tipo transferencia', null=True)
    is_active = models.BooleanField(default=True, verbose_name='Estado')

    def __str__(self):
        return self.provider.get_full_name()

    def get_subtotal_without_taxes(self):
        return float(self.buydetail_set.filter().aggregate(result=Coalesce(Sum('subtotal'), 0.00, output_field=FloatField())).get('result'))

    def get_full_subtotal(self):
        return float(self.subtotal_0) + float(self.subtotal_12)

    def calculate_invoice(self):
        self.subtotal_0 = float(self.buydetail_set.filter(product__with_tax=False).aggregate(result=Coalesce(Sum('total'), 0.00, output_field=FloatField())).get('result'))
        self.subtotal_12 = float(self.buydetail_set.filter(product__with_tax=True).aggregate(result=Coalesce(Sum('total'), 0.00, output_field=FloatField())).get('result'))
        self.total_iva = float(self.buydetail_set.filter(product__with_tax=True).aggregate(result=Coalesce(Sum('total_iva'), 0.00, output_field=FloatField())).get('result'))
        self.total_dscto = float(self.get_full_subtotal()) * float(self.dscto)
        self.total = float(self.get_full_subtotal()) - float(self.total_dscto)
        self.save()

    def calculate_detail(self):
        for detail in self.buydetail_set.filter():
            detail.price = float(detail.price)
            detail.iva = float(self.iva)
            detail.price_with_vat = detail.price + (detail.price * detail.iva)
            detail.subtotal = detail.price * detail.cant
            detail.total_dscto = detail.subtotal * float(detail.dscto)
            detail.total_iva = (detail.subtotal - detail.total_dscto) * detail.iva
            detail.total = detail.subtotal - detail.total_dscto
            detail.save()

    def toJSON(self):
        item = model_to_dict(self, exclude=['company', 'creation_date'])
        item['provider'] = self.provider.toJSON()
        item['employee'] = self.employee.toJSON()
        item['date_joined'] = self.date_joined.strftime('%Y-%m-%d')
        item['subtotal_12'] = float(self.subtotal_12)
        item['subtotal_0'] = float(self.subtotal_0)
        item['subtotal'] = float(self.get_subtotal_without_taxes())
        item['dscto'] = float(self.dscto)
        item['total_dscto'] = float(self.total_dscto)
        item['iva'] = float(self.iva)
        item['total_iva'] = float(self.total_iva)
        item['total'] = float(self.total)
        item['cash'] = float(self.cash)
        item['change'] = float(self.change)
        item['paymentmethod'] = {'id': self.paymentmethod, 'name': self.get_paymentmethod_display()}
        item['transfermethods'] = {'id': self.transfermethods, 'name': self.get_transfermethods_display()}
        return item

    class Meta:
        verbose_name = 'Compra'
        verbose_name_plural = 'Compras'
        default_permissions = ()
        permissions = (
            ('view_buy', 'Can view Compra'),
            ('add_buy', 'Can add Compra'),
            ('delete_buy', 'Can delete Compra'),
            ('view_buy_provider', 'Can view_buy_provider Compra'),
        )


class BuyDetail(models.Model):
    buy_id = models.ForeignKey(Buy, on_delete=models.CASCADE)
    product = models.ForeignKey(Product, on_delete=models.PROTECT)
    cant = models.IntegerField(default=0)
    price = models.DecimalField(max_digits=9, decimal_places=2, default=0.00)
    price_with_vat = models.DecimalField(max_digits=9, decimal_places=2, default=0.00)
    subtotal = models.DecimalField(max_digits=9, decimal_places=2, default=0.00)
    iva = models.DecimalField(max_digits=9, decimal_places=2, default=0.00)
    total_iva = models.DecimalField(max_digits=9, decimal_places=2, default=0.00)
    dscto = models.DecimalField(max_digits=9, decimal_places=2, default=0.00)
    total_dscto = models.DecimalField(max_digits=9, decimal_places=2, default=0.00)
    total = models.DecimalField(max_digits=9, decimal_places=2, default=0.00)
    is_active = models.BooleanField(default=True, verbose_name='Estado')

    def __str__(self):
        return self.product.name

    def get_iva_percent(self):
        return int(self.iva * 100)

    def toJSON(self):
        item = model_to_dict(self, exclude=['buy'])
        item['product'] = self.product.toJSON()
        item['price'] = float(self.price)
        item['price_with_vat'] = float(self.price_with_vat)
        item['subtotal'] = float(self.subtotal)
        item['iva'] = float(self.subtotal)
        item['total_iva'] = float(self.subtotal)
        item['dscto'] = float(self.dscto)
        item['total_dscto'] = float(self.total_dscto)
        item['total'] = float(self.total)
        return item

    class Meta:
        verbose_name = 'Detalle de Compra'
        verbose_name_plural = 'Detalle de Compra'
        default_permissions = ()

class Expenses(models.Model):
    source = models.CharField(max_length=50, choices=EXPENSES, default=EXPENSES[0][0], verbose_name='Fuente', null=True)
    user = models.ForeignKey(User, on_delete=models.PROTECT, verbose_name='Responsable')
    reason = models.CharField(max_length=200, verbose_name='Motivo')
    description = models.TextField(null=True, blank=True, verbose_name='Descripción')
    amount = models.DecimalField(max_digits=10, decimal_places=2, verbose_name='Valor')
    created_at = models.DateField(default=datetime.now, verbose_name='Fecha de creación')

    def __str__(self):
        return self.source

    def toJSON(self):
        item = model_to_dict(self)
        item['user'] = self.user.names or self.user.username
        item['created_at'] = self.created_at.strftime('%Y-%m-%d')
        item['amount'] = float(self.amount)
        item['source'] = {'id': self.source, 'name': self.get_source_display()}
        return item

    class Meta:
        verbose_name = 'Gasto'
        verbose_name_plural = 'Gastos'
        default_permissions = ()
        permissions = (
            ('view_bill', 'Can view Gasto'),
            ('add_expenses', 'Can Add Gasto'),
            ('change_expenses', 'Can Update Gasto'),
            ('delete_expenses', 'Can Delete Gasto'),
        )

class ProductAutoAdd(models.Model):
    trigger_product = models.ForeignKey(Product, related_name='auto_triggers', on_delete=models.CASCADE, verbose_name='Producto base')
    auto_product = models.ForeignKey(Product, related_name='auto_adds', on_delete=models.CASCADE, verbose_name='Producto descuento')
    quantity = models.DecimalField(max_digits=9, decimal_places=2, default=0.00, verbose_name='Cantidad')    

    def __str__(self):
        return f'{self.trigger_product} -> {self.auto_product} (x{self.quantity})'
    
class SaleCreditPayment(models.Model):
    sale = models.ForeignKey(Sale, on_delete=models.CASCADE)
    paymentmethod = models.CharField(max_length=50, choices=PAYMENTMETHODS, default=PAYMENTMETHODS[0][0], verbose_name='Método de pago')
    transfermethods = models.CharField(max_length=50, choices=TRANSFERMETHODS, default=TRANSFERMETHODS[0][0], verbose_name='Tipo transferencia', null=True)
    total = models.DecimalField(max_digits=9, decimal_places=2, default=0.00, verbose_name='Valor pago')
    date_payment = models.DateField(default=datetime.now, verbose_name='Fecha de pago')

    def __str__(self):
        return f"{self.sale.client.get_full_name()}"
    
    def toJSON(self):
        item = model_to_dict(self, exclude=['sale'])
        item['paymentmethod'] = {'id': self.paymentmethod, 'name': self.get_paymentmethod_display()}
        item['transfermethods'] = {'id': self.transfermethods, 'name': self.get_transfermethods_display()}
        item['total'] = float(self.total)
        item['date_payment'] = self.date_payment.strftime('%Y-%m-%d')
        return item

    class Meta:
        verbose_name = 'Pago Crédito'
        verbose_name_plural = 'Pagos Créditos'
        default_permissions = ()

class Employee(models.Model):
    dni = models.CharField(max_length=13, unique=True, verbose_name='Número de cedula')
    names = models.CharField(max_length=150, null=True, blank=True, verbose_name='Nombres')
    image = models.ImageField(upload_to='user/%Y/%m/%d', null=True, blank=True, verbose_name='Imagen')
    email = models.EmailField(null=True, blank=True, verbose_name='Correo electrónico')
    phone = models.CharField(max_length=15, blank=True, null=True, verbose_name='Telefono')
    address = models.CharField(max_length=255, blank=True, null=True,verbose_name='Dirección')
    birth_date = models.DateField(verbose_name='Fecha de nacimiento')
    contract_type = models.CharField(max_length=50, choices=TIPO_CONTRATO, default=TIPO_CONTRATO[0][0], verbose_name='Tipo de contrato')
    salary = models.DecimalField(max_digits=10, decimal_places=2, verbose_name='Salario neto')
    base_salary = models.DecimalField(max_digits=10, decimal_places=2, verbose_name='Salario base',default='1423500')
    start_date = models.DateField(verbose_name='Fecha de ingreso')
    retire_date = models.DateField(blank=True, null=True,verbose_name='Fecha de retiro')
    eps = models.CharField(max_length=100,null=True, verbose_name="Entidad Promotora de Salud")
    afp = models.CharField(max_length=100,null=True, verbose_name="Fondo de pensiones")
    arl = models.CharField(max_length=100,null=True, verbose_name="Administradora de Riesgos Laborales")
    caja_compensacion = models.CharField(max_length=100, blank=True, null=True,verbose_name='Caja de compensacion')
    is_active = models.BooleanField(default=True, verbose_name='Estado')
    social_security = models.BooleanField(default=True, verbose_name='Seguridad social')
    register_date = models.DateTimeField(auto_now_add=True, verbose_name='Fecha de registro')
    updated_date = models.DateTimeField(auto_now_add=True, null=True)

    class Meta:
        verbose_name = 'Empleado'
        verbose_name_plural = 'Empleados'
        ordering = ['names']

    def __str__(self):
        return f"{self.names}"
    
    def toJSON(self):
        item = model_to_dict(self)
        # Si usas un campo con choices, mostrar su texto legible:
        item['contract_type'] = self.get_contract_type_display()
        # Convertir decimales a float para evitar errores con json.dumps
        item['salary'] = float(self.salary)
        item['base_salary'] = float(self.base_salary)
        # Añadir campos calculados si quieres mostrarlos en la tabla o reportes
        item['aporte_salud_empleado'] = float(self.aporte_salud_empleado)
        item['aporte_pension_empleado'] = float(self.aporte_pension_empleado)
        item['aporte_salud_empresa'] = float(self.aporte_salud_empresa)
        item['aporte_pension_empresa'] = float(self.aporte_pension_empresa)
        item['aporte_arl_empresa'] = float(self.aporte_arl_empresa)
        item['total_empleado'] = float(self.total_empleado)
        item['total_empresa'] = float(self.total_empresa)
        item['total_seguridad_social'] = float(self.total_seguridad_social)

        item['birth_date'] = self.birth_date.strftime("%Y-%m-%d") if self.birth_date else ""
        item['start_date'] = self.start_date.strftime("%Y-%m-%d") if self.start_date else ""
        item['retire_date'] = self.retire_date.strftime("%Y-%m-%d") if self.retire_date else ""
        item['register_date'] = self.register_date.strftime("%Y-%m-%d %H:%M:%S") if self.register_date else ""
        item['updated_date'] = self.updated_date.strftime("%Y-%m-%d %H:%M:%S") if self.updated_date else ""

        item['image'] = self.image.url if self.image else None
        return item
    
    # --- Cálculos automáticos ---
    @property
    def aporte_salud_empleado(self):
        return round(self.base_salary * Decimal('0.04'), 2)

    @property
    def aporte_pension_empleado(self):
        return round(self.base_salary * Decimal('0.04'), 2)

    @property
    def aporte_salud_empresa(self):
        return round(self.base_salary * Decimal('0.085'), 2)

    @property
    def aporte_pension_empresa(self):
        return round(self.base_salary * Decimal('0.12'), 2)

    @property
    def aporte_arl_empresa(self):
        # Nivel de riesgo 1 por defecto (0.522%)
        return round(self.base_salary * Decimal('0.00522'), 2)

    @property
    def aporte_caja_empresa(self):
        return round(self.base_salary * Decimal('0.04'), 2)

    @property
    def aporte_sena_empresa(self):
        return round(self.base_salary * Decimal('0.02'), 2)

    @property
    def aporte_icbf_empresa(self):
        return round(self.base_salary * Decimal('0.03'), 2)

    @property
    def total_empleado(self):
        return self.aporte_salud_empleado + self.aporte_pension_empleado

    @property
    def total_empresa(self):
        return (
            self.aporte_salud_empresa +
            self.aporte_pension_empresa +
            self.aporte_arl_empresa 
            #+
            #self.aporte_caja_empresa 
            #+
            #self.aporte_sena_empresa +
            #self.aporte_icbf_empresa
        )

    @property
    def total_seguridad_social(self):
        return self.total_empleado + self.total_empresa
    
class Payroll(models.Model):
    employee = models.ForeignKey('Employee', on_delete=models.CASCADE, related_name='payrolls', verbose_name='Empleado')
    period = models.DateField(help_text="Mes y año de la nómina (usar el primer día del mes)", verbose_name='Periodo')
    period_type = models.CharField(max_length=2, choices=PERIODO_NOMINA, default='Q1', verbose_name='Tipo periodo')

    days_worked = models.PositiveIntegerField(default=15, verbose_name='Dias trabajados')
    base_salary = models.DecimalField(max_digits=12, decimal_places=2, verbose_name='Salario base')
    transportation_allowance = models.DecimalField(max_digits=12, decimal_places=2, default=0, verbose_name='Auxilio transporte')

    overtime_hours_value = models.DecimalField(max_digits=12, decimal_places=2, default=0, verbose_name='Valor horas extras')
    other_earnings = models.DecimalField(max_digits=12, decimal_places=2, default=0, verbose_name='Otros ingresos')
    deductions = models.DecimalField(max_digits=12, decimal_places=2, default=0, verbose_name='Deducciones')

    total_earned = models.DecimalField(max_digits=12, decimal_places=2, editable=False, verbose_name='Total devengado')
    total_payable = models.DecimalField(max_digits=12, decimal_places=2, editable=False, verbose_name='Total a pagar')
    social_security = models.DecimalField(max_digits=12, decimal_places=2, default=0, verbose_name='Seguridad social')

    generated_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = 'Nomina'
        verbose_name_plural = 'Nominas'
        ordering = ['-period', 'period_type']

    def __str__(self):
        return f"Payroll {self.get_period_type_display()} {self.period.strftime('%Y-%m')} - {self.employee.first_name}"

    from decimal import Decimal, ROUND_HALF_UP

    def calculate_totals(self):
        employee = self.employee

        # 🔹 salario proporcional real según días trabajados
        proportional_salary = (employee.salary / Decimal('30')) * Decimal(self.days_worked)

        transportation = Decimal(self.transportation_allowance or 0)
        overtime = Decimal(self.overtime_hours_value or 0)
        others = Decimal(self.other_earnings or 0)
        deductions = Decimal(self.deductions or 0)

        # 🔹 IBC (Ingreso Base Cotización)
        ibc = (employee.base_salary / Decimal('30')) * Decimal(self.days_worked)

        # 🔹 Seguridad social sobre IBC
        if employee.social_security:
            eps = ibc * Decimal('0.04')
            afp = ibc * Decimal('0.04')
            arl = ibc * Decimal('0.00522')
            seguridad_social = eps + afp + arl
        else:
            seguridad_social = Decimal('0.00')

        # 🔹 Total devengado
        total_earned = proportional_salary + transportation + overtime + others

        # 🔹 Total a pagar
        total_payable = total_earned - deductions - seguridad_social

        # 🔹 Guardar valores redondeados
        self.base_salary = proportional_salary.quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)
        self.social_security = seguridad_social.quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)
        self.total_earned = total_earned.quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)
        self.total_payable = total_payable.quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)

    def save(self, *args, **kwargs):
        self.calculate_totals()
        super().save(*args, **kwargs)

class InventoryGroup(models.Model):
    name = models.CharField(max_length=50, unique=True, verbose_name='Grupo Inventario')

    def __str__(self):
        return self.name
    
class UserInventoryGroup(models.Model):
    user = models.ForeignKey(User, on_delete=models.PROTECT, verbose_name='Empleado')
    group = models.ForeignKey(InventoryGroup, on_delete=models.CASCADE, verbose_name='Grupo Inventario')

    def __str__(self):
        return f'{self.user.username} - {self.group.name}'
    
class ProductInventoryGroupStock(models.Model):
    product = models.ForeignKey(Product, on_delete=models.CASCADE)
    group = models.ForeignKey(InventoryGroup, on_delete=models.CASCADE)
    stock = models.IntegerField(default=0, verbose_name='Stock')

    class Meta:
        unique_together = ('product', 'group')

    def __str__(self):
        return f'{self.product.name} - {self.group.name} ({self.stock})'

class Table(models.Model):
    name = models.CharField(max_length=50, verbose_name='Nombre mesa')
    capacity = models.PositiveIntegerField(default=1, verbose_name ='Capacidad')
    is_active = models.BooleanField(default=True, verbose_name='Estado')

    def toJSON(self):
        item = model_to_dict(self)
        return item

    def __str__(self):
        return self.name

    class Meta:
        verbose_name = 'Mesa'
        verbose_name_plural = 'Mesas'

class Order(models.Model):
    table = models.ForeignKey(Table, on_delete=models.PROTECT)
    employee = models.ForeignKey(User, on_delete=models.PROTECT)
    client = models.ForeignKey(Client, null=True, blank=True, on_delete=models.PROTECT)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default=STATUS_CHOICES[0][0], verbose_name='Estado')
    total = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    created_at = models.DateTimeField(auto_now_add=True)
    observations = models.TextField(null=True,blank=True,verbose_name='Observaciones')

    def toJSON(self):
        item = model_to_dict(self)
        item['employee'] = self.employee.toJSON()
        item['status_display'] = self.get_status_display()
        item['created_at'] = self.created_at.strftime('%Y-%m-%d %H:%M:%S')
        return item
    
    def __str__(self):
        return f'Orden #{self.id} - {self.get_status_display()}'

    class Meta:
        verbose_name = 'Orden'
        verbose_name_plural = 'Órdenes'
        default_permissions = ()
        permissions = (
            ('view_order', 'Puede ver órdenes'),
            ('add_order', 'Puede crear órdenes'),
            ('delete_order', 'Puede eliminar órdenes'),
        )

class OrderDetail(models.Model):
    order = models.ForeignKey(Order, on_delete=models.CASCADE)
    product = models.ForeignKey(Product, on_delete=models.PROTECT, verbose_name='Producto')
    cant = models.PositiveIntegerField(verbose_name='Cantidad')
    price = models.DecimalField(max_digits=10, decimal_places=2, verbose_name='Precio unitario')
    dscto = models.DecimalField(max_digits=5, decimal_places=2, default=0, verbose_name='Descuento (%)')

    def subtotal(self):
        return round(self.cant * self.price, 2)

    def get_discount_value(self):
        return round(self.get_subtotal() * (self.dscto / 100), 2)

    def get_subtotal_with_discount(self):
        return round(self.get_subtotal() - self.get_discount_value(), 2)

    def get_iva_value(self):
        return round(self.get_subtotal_with_discount() * (self.iva_rate / 100), 2)

    def get_total(self):
        return round(self.get_subtotal_with_discount() + self.get_iva_value(), 2)

    def toJSON(self):
        item = model_to_dict(self, exclude=['order'])
        item['product'] = self.product.toJSON()
        item['subtotal'] = float(self.get_subtotal())
        item['discount_value'] = float(self.get_discount_value())
        item['iva_value'] = float(self.get_iva_value())
        item['total'] = float(self.get_total())
        return item

    def __str__(self):
        return f'{self.product} x {self.cant}'

    class Meta:
        verbose_name = 'Detalle de orden'
        verbose_name_plural = 'Detalles de orden'

class EmployeeTransaction(models.Model):
    employee = models.ForeignKey(Employee, on_delete=models.PROTECT, verbose_name='Empleado')
    transaction_type = models.CharField(max_length=20, choices=EMPLOYEE_TRANSACTION_CHOICES, verbose_name='Tipo')
    source = models.CharField(max_length=20, choices=EXPENSES, verbose_name='Desde')
    amount = models.DecimalField(max_digits=9, decimal_places=2, default=0, verbose_name='Valor')
    description = models.TextField(blank=True, verbose_name='Description')
    created_by = models.ForeignKey(User, on_delete=models.PROTECT, related_name='created_transactions')
    created_at = models.DateTimeField(auto_now_add=True)
    is_paid = models.BooleanField(default=False)
    balance = models.DecimalField(max_digits=9, decimal_places=2, default=0)

    def save(self, *args, **kwargs):
        if not self.balance:
            self.balance = self.amount
        super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.employee} - {self.get_transaction_type_display()} - {self.amount}"

    def toJSON(self):
        return {
            "id": self.id,
            "employee": self.employee.names,
            "transaction_type": self.get_transaction_type_display(),
            "source": self.get_source_display(),
            "amount": float(self.amount),
            "balance": float(self.balance),
            "products": [
                {
                    "name": d.product.name,
                    "quantity": d.quantity
                } for d in self.employeetransactiondetail_set.all()
            ],
            "description": self.description,
            "created_by": self.created_by.username,
            "created_at": self.created_at.strftime("%Y-%m-%d %H:%M"),
            "is_paid": self.is_paid
        }

    class Meta:
        verbose_name = "Movimiento empleado"
        verbose_name_plural = "Movimientos empleados"

        default_permissions = ()

        permissions = (
            ("view_employee_transaction", "Puede ver movimientos empleados"),
            ("add_employee_transaction", "Puede registrar movimientos empleados"),
            ("change_employee_transaction", "Puede editar movimientos empleados"),
            ("delete_employee_transaction", "Puede eliminar movimientos empleados"),
            ("approve_employee_transaction", "Puede aprobar préstamos"),
            ("pay_employee_transaction", "Puede registrar pagos"),
            ("report_employee_transaction", "Puede ver reportes de movimientos"),
        )

class EmployeeTransactionDetail(models.Model):
    transaction = models.ForeignKey(EmployeeTransaction, on_delete=models.CASCADE)
    product = models.ForeignKey(Product, on_delete=models.PROTECT, verbose_name='Producto')
    quantity = models.IntegerField(default=1, verbose_name='Cantidad')

    def save(self, *args, **kwargs):

        if not self.product.is_service:
            if self.product.stock < self.quantity:
                raise Exception(f"No hay suficiente stock de {self.product.name}")

            self.product.stock -= self.quantity
            self.product.save()

        super().save(*args, **kwargs)
        
class CashClosing(models.Model):

    user = models.ForeignKey(User, on_delete=models.PROTECT)
    created_at = models.DateTimeField(auto_now_add=True)
    total_sales = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    cash_sales = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    credit_sales = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    debit_sales = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    transfer_sales = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    expenses = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    expected_cash = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    base_cash = models.DecimalField(max_digits=9,decimal_places=2,default=0.00,verbose_name='Base Inicial')
    real_cash = models.DecimalField(max_digits=10, decimal_places=2)
    difference = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    observations = models.TextField(blank=True, null=True)
    is_active = models.BooleanField(default=True)

    def save(self, *args, **kwargs):
        self.difference = self.real_cash - self.expected_cash
        super().save(*args, **kwargs)

    def __str__(self):
        return f'Cierre #{self.id} - {self.user.username}'

    def toJSON(self):
        item = model_to_dict(self)
        item['user'] = {
            'id': self.user.id,
            'names': self.user.names
        }
        item['created_at'] = self.created_at.strftime('%Y-%m-%d %H:%M')
        item['total_sales'] = float(self.total_sales)
        item['cash_sales'] = float(self.cash_sales)
        item['credit_sales'] = float(self.credit_sales)
        item['debit_sales'] = float(self.debit_sales)
        item['transfer_sales'] = float(self.transfer_sales)
        item['expenses'] = float(self.expenses)
        item['expected_cash'] = float(self.expected_cash)
        item['base_cash'] = float(self.base_cash)
        item['real_cash'] = float(self.real_cash)
        item['difference'] = float(self.difference)
        return item

    class Meta:
        verbose_name = 'Cierre de Caja'
        verbose_name_plural = 'Cierres de Caja'
        ordering = ['-created_at']

class ObservationTemplate(models.Model):
    name = models.CharField(max_length=150, verbose_name='Nombre de la plantilla')
    code = models.CharField(max_length=50, unique=True, verbose_name='Código único (ej: contado, credito)')
    content = models.TextField(verbose_name='Contenido de la observación')
    is_active = models.BooleanField(default=True, verbose_name='Está activa')

    def __str__(self):
        return self.title

    class Meta:
        verbose_name = 'Plantilla de Observación'
        verbose_name_plural = 'Plantillas de Observaciones'


class CreditNote(models.Model):
    company = models.ForeignKey(Company, on_delete=models.PROTECT, verbose_name='Compañia')
    client = models.ForeignKey(Client, on_delete=models.PROTECT, verbose_name='Cliente')
    employee = models.ForeignKey(User, on_delete=models.PROTECT, verbose_name='Empleado')
    creation_date = models.DateTimeField(auto_now_add=True, verbose_name='Fecha y hora de registro')
    date_joined = models.DateField(default=datetime.now, verbose_name='Fecha de registro')

    # Tipo de operación DIAN/Factus: '20' con referencia a factura, '22' sin referencia
    operation_type = models.CharField(max_length=2, choices=CREDIT_NOTE_OPERATION_TYPE, default=CREDIT_NOTE_OPERATION_TYPE[0][0], verbose_name='Tipo de operación')
    correction_concept = models.CharField(max_length=1, choices=CREDIT_NOTE_CORRECTION_CONCEPT, default=CREDIT_NOTE_CORRECTION_CONCEPT[0][0], verbose_name='Motivo')

    # Solo aplica cuando operation_type == '20' (con referencia a factura)
    reference_sale = models.ForeignKey(Sale, on_delete=models.PROTECT, null=True, blank=True, verbose_name='Factura referenciada')
    reference_bill_number = models.CharField(max_length=50, null=True, blank=True, verbose_name='N° de factura referenciada')
    reference_cufe = models.TextField(null=True, blank=True, verbose_name='CUFE de la factura referenciada')

    # Solo obligatorio cuando operation_type == '22' (sin referencia a factura)
    billing_period_start_date = models.DateField(null=True, blank=True, verbose_name='Periodo de facturación - Inicio')
    billing_period_end_date = models.DateField(null=True, blank=True, verbose_name='Periodo de facturación - Fin')

    subtotal_12 = models.DecimalField(max_digits=9, decimal_places=2, default=0.00, verbose_name='Subtotal 12%')
    subtotal_12_sin_iva = models.DecimalField(max_digits=9, decimal_places=2, default=0.00, verbose_name='Valor Bruto')
    subtotal_0 = models.DecimalField(max_digits=9, decimal_places=2, default=0.00, verbose_name='Subtotal 0%')
    dscto = models.DecimalField(max_digits=9, decimal_places=2, default=0.00, verbose_name='Descuento')
    total_dscto = models.DecimalField(max_digits=9, decimal_places=2, default=0.00, verbose_name='Valor del descuento')
    iva = models.DecimalField(max_digits=9, decimal_places=2, default=0.00, verbose_name='Iva')
    total_iva = models.DecimalField(max_digits=9, decimal_places=2, default=0.00, verbose_name='Valor de iva')
    total = models.DecimalField(max_digits=9, decimal_places=2, default=0.00, verbose_name='Total nota crédito')

    paymentmethod = models.CharField(max_length=50, choices=PAYMENTMETHODS, default=PAYMENTMETHODS[0][0], verbose_name='Método de pago')
    transfermethods = models.CharField(max_length=50, choices=TRANSFERMETHODS, default=TRANSFERMETHODS[0][0], verbose_name='Tipo transferencia', null=True, blank=True)
    typemethods = models.CharField(max_length=50, choices=TYPETMETHODS, default=TYPETMETHODS[0][0], verbose_name='Tipo pago', null=True, blank=True)
    expiration_date = models.DateField(null=True, blank=True, verbose_name='Fecha de vencimiento')
    nequi_value = models.DecimalField(max_digits=9, decimal_places=2, default=0.00, verbose_name='Valor Nequi')
    daviplata_value = models.DecimalField(max_digits=9, decimal_places=2, default=0.00, verbose_name='Valor Daviplata')

    description = models.CharField(max_length=500, null=True, blank=True, verbose_name='Observación')
    is_active = models.BooleanField(default=True, verbose_name='Estado')

    # Campos de integración con Factus
    factus_credit_note_number = models.CharField(max_length=50, null=True, blank=True)
    factus_status = models.CharField(max_length=20, null=True, blank=True)
    factus_pdf_url = models.URLField(max_length=500, null=True, blank=True)
    factus_xml_url = models.URLField(max_length=500, null=True, blank=True)
    factus_cufe = models.TextField(null=True, blank=True)
    factus_resolution = models.TextField(null=True, blank=True)
    factus_prefix = models.TextField(null=True, blank=True)
    factus_range_from = models.TextField(null=True, blank=True)
    factus_range_to = models.TextField(null=True, blank=True)
    factus_date_from = models.TextField(null=True, blank=True)
    factus_date_to = models.TextField(null=True, blank=True)
    factus_qr_url = models.URLField(null=True, blank=True)
    email_sent_count = models.PositiveIntegerField(default=0, verbose_name="Correos enviados")

    def __str__(self):
        return self.client.get_full_name()

    def is_with_reference(self):
        return self.operation_type == '20'

    def can_edit_items(self):
        """Solo la anulación de factura (motivo 2) bloquea la edición de ítems:
        la nota debe reflejar exactamente lo facturado."""
        return self.correction_concept != '2'

    def get_full_subtotal(self):
        return float(self.subtotal_0) + float(self.subtotal_12)

    def calculate_detail(self):
        for detail in self.creditnotedetail_set.filter():
            detail.price = float(detail.price)
            detail.iva = float(self.iva)
            detail.price_with_vat = detail.price + (detail.price * detail.iva)
            detail.subtotal = detail.price * detail.cant
            detail.total_dscto = detail.subtotal * float(detail.dscto)
            detail.total_iva = (detail.subtotal - detail.total_dscto) * detail.iva
            detail.total = detail.subtotal - detail.total_dscto
            detail.save()

    def calculate_invoice(self):
        self.subtotal_0 = float(self.creditnotedetail_set.filter(product__with_tax=False).aggregate(result=Coalesce(Sum('total'), 0.00, output_field=FloatField())).get('result'))
        self.subtotal_12 = float(self.creditnotedetail_set.filter(product__with_tax=True).aggregate(result=Coalesce(Sum('total'), 0.00, output_field=FloatField())).get('result'))
        subtotal = float(self.get_full_subtotal())
        discount_rate = float(self.dscto or 0)
        self.total_dscto = subtotal * discount_rate

        iva_before_global_discount = float(self.creditnotedetail_set.filter(product__with_tax=True).aggregate(result=Coalesce(Sum('total_iva'), 0.00, output_field=FloatField())).get('result'))
        self.total_iva = iva_before_global_discount * (1 - discount_rate)
        self.subtotal_12_sin_iva = self.subtotal_12 * (1 - discount_rate)
        self.total = (subtotal - float(self.total_dscto)) + float(self.total_iva)
        self.save()

    def toJSON(self):
        item = model_to_dict(self, exclude=['company', 'creation_date'])
        item['client'] = self.client.toJSON()
        item['employee'] = self.employee.toJSON()
        item['date_joined'] = self.date_joined.strftime('%Y-%m-%d')
        local_date = self.creation_date.astimezone(ZoneInfo("America/Bogota"))
        item['creation_time'] = local_date.strftime('%I:%M:%S %p')
        item['datetime_full'] = local_date.strftime('%Y-%m-%d %I:%M %p')
        item['operation_type'] = {'id': self.operation_type, 'name': self.get_operation_type_display()}
        item['correction_concept'] = {'id': self.correction_concept, 'name': self.get_correction_concept_display()}
        item['reference_sale_id'] = self.reference_sale_id
        item['reference_bill_number'] = self.reference_bill_number
        item['reference_cufe'] = self.reference_cufe
        item['billing_period_start_date'] = (self.billing_period_start_date.strftime('%Y-%m-%d') if self.billing_period_start_date else None)
        item['billing_period_end_date'] = (self.billing_period_end_date.strftime('%Y-%m-%d') if self.billing_period_end_date else None)
        item['subtotal_12'] = float(self.subtotal_12)
        item['subtotal_12_sin_iva'] = float(self.subtotal_12_sin_iva)
        item['subtotal_0'] = float(self.subtotal_0)
        item['subtotal'] = float(self.get_full_subtotal())
        item['dscto'] = float(self.dscto)
        item['total_dscto'] = float(self.total_dscto)
        item['iva'] = float(self.iva)
        item['total_iva'] = float(self.total_iva)
        item['total'] = float(self.total)
        item['paymentmethod'] = {'id': self.paymentmethod, 'name': self.get_paymentmethod_display()}
        item['transfermethods'] = {'id': self.transfermethods, 'name': self.get_transfermethods_display()}
        item['typemethods'] = {'id': self.typemethods, 'name': self.get_typemethods_display()}
        item['expiration_date'] = (self.expiration_date.strftime('%Y-%m-%d') if self.expiration_date else None)
        item['nequi_value'] = float(self.nequi_value)
        item['daviplata_value'] = float(self.daviplata_value)
        item['factus_credit_note_number'] = self.factus_credit_note_number
        item['factus_status'] = self.factus_status
        item['factus_pdf_url'] = self.factus_pdf_url
        item['factus_xml_url'] = self.factus_xml_url
        item['factus_cufe'] = self.factus_cufe
        item['factus_resolution'] = self.factus_resolution
        item['factus_qr_url'] = self.factus_qr_url
        item['email_sent_count'] = self.email_sent_count
        return item

    class Meta:
        verbose_name = 'Nota Crédito'
        verbose_name_plural = 'Notas Crédito'
        default_permissions = ()
        permissions = (
            ('view_creditnote', 'Can view Nota Crédito'),
            ('add_creditnote', 'Can add Nota Crédito'),
            ('delete_creditnote', 'Can delete Nota Crédito'),
        )


class CreditNoteDetail(models.Model):
    credit_note = models.ForeignKey(CreditNote, on_delete=models.CASCADE)
    sale_detail = models.ForeignKey(SaleDetail, on_delete=models.SET_NULL, null=True, blank=True, verbose_name='Línea de factura de origen')
    product = models.ForeignKey(Product, on_delete=models.PROTECT)
    cant = models.IntegerField(default=0)
    price = models.DecimalField(max_digits=9, decimal_places=2, default=0.00)
    price_with_vat = models.DecimalField(max_digits=9, decimal_places=2, default=0.00)
    subtotal = models.DecimalField(max_digits=9, decimal_places=2, default=0.00)
    iva = models.DecimalField(max_digits=9, decimal_places=2, default=0.00)
    total_iva = models.DecimalField(max_digits=9, decimal_places=2, default=0.00)
    dscto = models.DecimalField(max_digits=9, decimal_places=2, default=0.00)
    total_dscto = models.DecimalField(max_digits=9, decimal_places=2, default=0.00)
    total = models.DecimalField(max_digits=9, decimal_places=2, default=0.00)

    def __str__(self):
        return self.product.name

    def get_iva_percent(self):
        return int(self.iva * 100)

    def toJSON(self):
        item = model_to_dict(self, exclude=['credit_note'])
        item['product'] = self.product.toJSON()
        item['price'] = float(self.price)
        item['price_with_vat'] = float(self.price_with_vat)
        item['subtotal'] = float(self.subtotal)
        item['iva'] = float(self.iva)
        item['total_iva'] = float(self.total_iva)
        item['dscto'] = float(self.dscto)
        item['total_dscto'] = float(self.total_dscto)
        item['total'] = float(self.total)
        return item

    class Meta:
        verbose_name = 'Detalle de Nota Crédito'
        verbose_name_plural = 'Detalle de Notas Crédito'
        default_permissions = ()


class FactusCredential(models.Model):
    """Credenciales propias de esta empresa (tenant) para conectarse a la API
    de Factus. Al vivir en una app de TENANT_APPS, cada tenant solo ve y
    administra sus propias filas — no requiere relación explícita al tenant.

    Puede haber varias filas (ej. una de Sandbox y otra de Producción); la
    marcada como activa (``is_active``) es la que usa ``core.services.factus``
    en cada llamada. El ``save()`` garantiza que solo una quede activa a la vez.
    """
    name = models.CharField(max_length=100, verbose_name='Nombre', help_text='Ej: Producción, Sandbox de pruebas')
    environment = models.CharField(max_length=20, choices=FACTUS_ENVIRONMENT, default=FACTUS_ENVIRONMENT[1][0], verbose_name='Ambiente')
    api_url = models.URLField(max_length=200, verbose_name='URL de la API')
    client_id = models.CharField(max_length=100, verbose_name='Client ID')
    client_secret = models.CharField(max_length=200, verbose_name='Client Secret')
    username = models.CharField(max_length=150, verbose_name='Usuario')
    password = models.CharField(max_length=200, verbose_name='Contraseña')
    is_active = models.BooleanField(default=False, verbose_name='Activa')
    creation_date = models.DateTimeField(auto_now_add=True, verbose_name='Fecha de creación')

    def __str__(self):
        return f"{self.name} ({self.get_environment_display()})"

    def save(self, *args, **kwargs):
        if self.is_active:
            # Garantiza que nunca haya dos credenciales activas a la vez: al
            # activar esta, se desactivan todas las demás del mismo tenant.
            FactusCredential.objects.exclude(pk=self.pk).update(is_active=False)
        super().save(*args, **kwargs)

    def toJSON(self):
        item = model_to_dict(self, exclude=['client_secret', 'password'])
        item['environment'] = {'id': self.environment, 'name': self.get_environment_display()}
        item['creation_date'] = self.creation_date.strftime('%Y-%m-%d %H:%M') if self.creation_date else None
        return item

    class Meta:
        verbose_name = 'Credencial de Factus'
        verbose_name_plural = 'Credenciales de Factus'
        default_permissions = ()
        permissions = (
            ('view_factuscredential', 'Can view Credencial de Factus'),
            ('add_factuscredential', 'Can add Credencial de Factus'),
            ('change_factuscredential', 'Can change Credencial de Factus'),
            ('delete_factuscredential', 'Can delete Credencial de Factus'),
        )