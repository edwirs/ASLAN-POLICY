from django.core.management.base import BaseCommand, CommandError

from core.tenants import respaldos


class Command(BaseCommand):
    help = (
        'Hace un respaldo de la base de datos (completo o de una empresa), lo verifica y borra los viejos. '
        'Pensado para programarse todos los días con cron (ver el panel de la plataforma › Respaldos).'
    )

    def add_arguments(self, parser):
        parser.add_argument('--schema', help='Respalda solo esta empresa (por defecto: todo).')
        parser.add_argument('--retener', type=int, help='Días que se conservan (por defecto RESPALDOS_RETENCION_DIAS).')

    def handle(self, *args, **options):
        try:
            r = respaldos.crear(options['schema'], options['retener'])
        except respaldos.RespaldoError as e:
            raise CommandError(str(e))
        self.stdout.write(self.style.SUCCESS(f'Respaldo listo: {r["ruta"]} ({r["tamano"]})'))
