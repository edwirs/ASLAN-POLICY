import getpass

from django.contrib.auth.hashers import make_password
from django.core.management.base import BaseCommand, CommandError


class Command(BaseCommand):
    help = (
        'Genera el acceso al panel de la plataforma (solo ASLAN): pide usuario y clave y muestra las dos líneas que van en '
        '.env.secrets. La clave se guarda CIFRADA; este comando no escribe ningún archivo.'
    )

    def add_arguments(self, parser):
        parser.add_argument('--reset-seguridad', action='store_true', help=(
            'Rescate: borra lo configurado desde el panel (clave propia, 2FA y lista de IPs). El acceso vuelve a regirse por '
            'PLATAFORMA_USUARIO / PLATAFORMA_CLAVE_HASH de .env.secrets.'))

    def handle(self, *args, **options):
        if options['reset_seguridad']:
            from core.tenants.models import AccesoPlataforma, Auditoria

            n, _ = AccesoPlataforma.objects.all().delete()
            Auditoria.objects.create(accion='reset_seguridad', detalle='desde la terminal del servidor', ip='terminal')
            self.stdout.write(self.style.SUCCESS(f'Listo ({n} registro borrado). El panel vuelve a usar la clave de .env.secrets, sin 2FA ni lista de IPs.'))
            return
        usuario = input('Usuario del panel (ej. aslan): ').strip()
        if not usuario:
            raise CommandError('El usuario no puede estar vacío.')
        clave = getpass.getpass('Clave (mínimo 12 caracteres): ')
        if len(clave) < 12:
            raise CommandError('Usa una clave de al menos 12 caracteres.')
        if clave != getpass.getpass('Repite la clave: '):
            raise CommandError('Las claves no coinciden.')
        self.stdout.write(self.style.SUCCESS('\nPega estas dos líneas en .env.secrets (y reinicia el servidor):\n'))
        self.stdout.write(f'PLATAFORMA_USUARIO={usuario}')
        self.stdout.write(f'PLATAFORMA_CLAVE_HASH={make_password(clave)}\n')
