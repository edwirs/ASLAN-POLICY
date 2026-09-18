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
    auto_create_schema = True

    def __str__(self):
        return self.name


class Domain(DomainMixin):
    pass

# Este signal se dispara justo después de que se crea una nueva empresa (Client)
@receiver(post_save, sender=Client)
def create_default_domain(sender, instance, created, **kwargs):
    if created:
        # Asume que el dominio será 'schema_name.critera.online'
        # Puedes cambiar 'critera.online' por tu dominio principal
        BASE_DOMAIN = env("BASE_DOMAIN", default="aslantecnologia.online")
        domain_name = f"{instance.schema_name}.{BASE_DOMAIN}"
        
        # Crea el objeto Domain asociado al tenant recién creado
        Domain.objects.create(
            domain=domain_name, 
            tenant=instance, 
            is_primary=True
        )