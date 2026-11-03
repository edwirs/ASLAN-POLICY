from django.core.management.base import BaseCommand
from django_tenants.utils import get_public_schema_name, get_tenant_model, schema_context

from core.policies.services import pdf_cotizaciones


class Command(BaseCommand):
    help = ('Borra los PDF que descargaron los bots hace más de 10 días y que no quedaron entre las 2 más baratas de su '
            'vehículo ni se enviaron al cliente. También corre solo cada vez que un bot descarga un PDF.')

    def add_arguments(self, parser):
        parser.add_argument('--schema', help='Solo esta empresa (esquema). Sin esto, todas.')

    def handle(self, *args, **options):
        empresas = get_tenant_model().objects.exclude(schema_name=get_public_schema_name())
        if options['schema']:
            empresas = empresas.filter(schema_name=options['schema'])
        for empresa in empresas:
            with schema_context(empresa.schema_name):
                borrados = pdf_cotizaciones.limpiar_vencidos()
            self.stdout.write(f'{empresa.schema_name}: {borrados} PDF borrados')
