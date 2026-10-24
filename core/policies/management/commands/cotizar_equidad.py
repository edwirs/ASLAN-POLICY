from django.core.management.base import BaseCommand, CommandError
from django_tenants.utils import schema_context

from core.policies.models import Aseguradora, Cotizacion, TipoPoliza, Vehiculo
from core.policies.services.bots.equidad import EquidadBot
from core.user.models import User

ASEGURADORA_NOMBRE = 'La Equidad Seguros'


class Command(BaseCommand):
    help = (
        'Ejecuta el bot de cotización de La Equidad para un vehículo ya registrado. '
        'Pensado para probar el bot manualmente antes de conectarlo a un botón en la interfaz.'
    )

    def add_arguments(self, parser):
        parser.add_argument('--schema', required=True, help='Schema del tenant (ej. gali)')
        parser.add_argument('--placa', required=True, help='Placa del vehículo ya registrado en Solicitudes')
        parser.add_argument('--asesor', required=True, help='Username del asesor que queda como responsable de la cotización')
        parser.add_argument('--cero-km', action='store_true', help='Marca el vehículo como 0 kilómetros para esta cotización')
        parser.add_argument('--headed', action='store_true', help='Corre el navegador visible (para depurar selectores), en vez de headless')

    def handle(self, *args, **options):
        with schema_context(options['schema']):
            try:
                vehiculo = Vehiculo.objects.get(placa=options['placa'].upper())
            except Vehiculo.DoesNotExist:
                raise CommandError(f'No existe un vehículo con placa {options["placa"]}. Regístrelo primero en Solicitudes.')

            try:
                asesor = User.objects.get(username=options['asesor'])
            except User.DoesNotExist:
                raise CommandError(f'No existe el usuario "{options["asesor"]}".')

            aseguradora, _ = Aseguradora.objects.get_or_create(name=ASEGURADORA_NOMBRE)
            tipo_poliza, _ = TipoPoliza.objects.get_or_create(code='todo-riesgo', defaults={'name': 'Todo Riesgo'})

            if options['cero_km']:
                vehiculo.es_cero_km = True
                vehiculo.save(update_fields=['es_cero_km'])

            cotizacion = Cotizacion.objects.create(
                vehiculo=vehiculo,
                tomador=vehiculo.tomador,
                asesor=asesor,
                aseguradora=aseguradora,
                tipo_poliza=tipo_poliza,
            )

            self.stdout.write(f'Cotización #{cotizacion.id} creada. Iniciando bot (headless={not options["headed"]})...')

            bot = EquidadBot(cotizacion, headless=not options['headed'])
            bot.run()

            cotizacion.refresh_from_db()
            self.stdout.write(self.style.SUCCESS(f'Estado final del bot: {cotizacion.estado_bot}'))
            if cotizacion.mensaje_bot:
                self.stdout.write(f'Mensaje: {cotizacion.mensaje_bot}')
            for plan in cotizacion.planes.all():
                self.stdout.write(f'  Plan {plan.nombre_plan}: ${plan.prima_total}')
