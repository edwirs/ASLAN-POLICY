from django.core.management.base import BaseCommand, CommandError
from django_tenants.utils import get_public_schema_name, get_tenant_model, schema_context

from core.policies.services import asistente


class Command(BaseCommand):
    help = (
        'Plan de Aslani (el asistente con IA) de cada empresa: activar o apagar la IA y fijar las preguntas por mes. '
        'Sin opciones muestra, por empresa, el plan y lo consumido este mes. La bolsa se renueva el día 1 y no se acumula.'
    )

    def add_arguments(self, parser):
        parser.add_argument('--schema', help='Empresa (esquema). Sin esto se listan todas.')
        parser.add_argument('--preguntas', type=int, help='Preguntas por mes (ej. 900).')
        parser.add_argument('--ia', choices=['si', 'no'], help='Activar o apagar la IA de esa empresa (apagada = solo modo básico).')

    def handle(self, *args, **options):
        Empresa = get_tenant_model()
        if options['preguntas'] is not None or options['ia']:
            if not options['schema']:
                raise CommandError('Indica la empresa con --schema para cambiar su plan.')
            empresa = Empresa.objects.filter(schema_name=options['schema']).first()
            if not empresa:
                raise CommandError(f'No existe la empresa "{options["schema"]}".')
            if options['preguntas'] is not None:
                if options['preguntas'] < 0:
                    raise CommandError('Las preguntas por mes no pueden ser negativas.')
                empresa.aslani_preguntas_mes = options['preguntas']
            if options['ia']:
                empresa.aslani_ia_activa = options['ia'] == 'si'
            empresa.save(update_fields=['aslani_preguntas_mes', 'aslani_ia_activa'])
            self.stdout.write(self.style.SUCCESS(f'{empresa.name}: IA {"activa" if empresa.aslani_ia_activa else "apagada"}, {empresa.aslani_preguntas_mes} preguntas por mes.'))

        empresas = Empresa.objects.exclude(schema_name=get_public_schema_name())
        if options['schema']:
            empresas = empresas.filter(schema_name=options['schema'])
        self.stdout.write(f'\n{"Empresa":<34}{"IA":<9}{"Plan/mes":>9}{"Usadas":>9}{"Quedan":>9}   Se renueva')
        for e in empresas.order_by('name'):
            with schema_context(e.schema_name):
                c = asistente.cupo(None)
            self.stdout.write(f'{e.name[:33]:<34}{"activa" if e.aslani_ia_activa else "apagada":<9}{c["limite"]:>9}{c["usadas"]:>9}{c["restantes"]:>9}   {c["renueva"]}')
