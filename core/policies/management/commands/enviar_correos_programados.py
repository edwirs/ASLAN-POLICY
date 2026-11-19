import logging

from django.core.management.base import BaseCommand
from django_tenants.utils import get_public_schema_name, get_tenant_model, schema_context

from core.policies.services import correo, horario_habil

logger = logging.getLogger(__name__)


class Command(BaseCommand):
    help = ('Envía los correos de cotización programados cuya hora ya llegó, solo dentro del horario hábil de Colombia '
            '(lunes a viernes 8:00-17:00, sábados 8:00-12:00, sin festivos). Lo corre cada minuto el timer '
            'aslan-correos del servidor (deploy/correos).')

    def add_arguments(self, parser):
        parser.add_argument('--schema', help='Solo esta empresa (esquema). Sin esto, todas.')
        parser.add_argument('--limite', type=int, default=10, help='Máximo de correos por empresa en cada corrida.')

    def handle(self, *args, **options):
        if not horario_habil.en_horario():
            return  # fuera del horario no se envía nada (y no se ensucia el registro cada minuto)
        empresas = get_tenant_model().objects.exclude(schema_name=get_public_schema_name())
        if options['schema']:
            empresas = empresas.filter(schema_name=options['schema'])
        for empresa in empresas:
            try:
                with schema_context(empresa.schema_name):
                    enviados, fallidos = correo.enviar_pendientes(limite=options['limite'])
            except Exception:
                logger.exception('Error enviando los correos programados de %s', empresa.schema_name)
                continue
            if enviados or fallidos:
                self.stdout.write(f'{empresa.schema_name}: {enviados} enviados, {fallidos} sin enviar (reintento o error)')
