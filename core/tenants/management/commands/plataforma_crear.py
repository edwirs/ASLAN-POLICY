import environ
from django.core.management.base import BaseCommand
from django_tenants.utils import get_public_schema_name, get_tenant_model

from core.tenants.models import Domain

env = environ.Env()


class Command(BaseCommand):
    help = (
        'Crea la empresa interna «public» y sus dominios para abrir el panel de la plataforma (admin.<dominio base> y admin.localhost). '
        'Es idempotente: se puede correr de nuevo sin duplicar nada.'
    )

    def add_arguments(self, parser):
        parser.add_argument('--dominio', action='append', help='Dominio extra para el panel (se puede repetir).')

    def handle(self, *args, **options):
        base = env('BASE_DOMAIN', default='aslantecnologia.online')
        dominios = [f'admin.{base}', 'admin.localhost', *(options['dominio'] or [])]
        Empresa = get_tenant_model()
        publica = Empresa.objects.filter(schema_name=get_public_schema_name()).first()
        if publica is None:
            publica = Empresa(schema_name=get_public_schema_name(), name='Plataforma ASLAN', nit='PLATAFORMA', aslani_ia_activa=False, on_trial=False)
            # ¡IMPORTANTE! El schema «public» YA existe y no se debe tocar. Con auto_create_schema=True, si algo fallaba al "crearlo",
            # django-tenants lo BORRABA (delete(force_drop=True)) junto con la lista de empresas. Así que se registra SIN crear nada.
            publica.auto_create_schema = False
            publica.save()
            Domain.objects.filter(tenant=publica).exclude(domain__in=dominios).delete()  # quita el dominio automático «public.<base>»
            self.stdout.write(self.style.SUCCESS('Empresa interna «public» creada.'))
        for dominio in dominios:
            _, creado = Domain.objects.get_or_create(domain=dominio, defaults={'tenant': publica, 'is_primary': dominio == dominios[0]})
            self.stdout.write(f'  {"+" if creado else "="} {dominio}')
        self.stdout.write(self.style.SUCCESS(f'\nPanel listo en: https://{dominios[0]}  (local: http://admin.localhost:8000). Falta el acceso: manage.py plataforma_clave'))
