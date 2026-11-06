"""Deja una empresa SIN clientes, vehículos, solicitudes de cotización ni pólizas, con los ID otra vez desde 1.

    venv/bin/python manage.py limpiar_clientes --schema gali                       # solo muestra qué borraría
    venv/bin/python manage.py limpiar_clientes --schema gali --confirmar gali      # borra (antes saca un respaldo)

Se conserva todo lo demás: usuarios, roles, aseguradoras y sus credenciales, coberturas, asesores, plantillas y cuentas
de correo, datos de la empresa, agente de la oficina…

Qué borra (y reinicia sus ID): clientes y sus contactos, vehículos, solicitudes de cotización (cotizaciones, planes,
valores manuales, correos enviados, historial) y pólizas con sus cuotas; también los PDF de las cotizaciones (los del
portal y los subidos a mano).

Protecciones:
- Sin --confirmar <schema> no borra nada: solo cuenta.
- Nunca en el schema «public».
- Antes de borrar saca un respaldo de esa empresa (manage.py respaldo_crear --schema …). Si el respaldo falla, no borra.
- Si el POS de la empresa tiene facturas, órdenes, precios o notas crédito ligados a clientes, se detiene: borrar los
  clientes se las llevaría. Solo sigue con --incluir-pos.
"""
from django.core.cache import cache
from django.core.management import call_command
from django.core.management.base import BaseCommand, CommandError
from django.db import connection, transaction
from django_tenants.utils import get_public_schema_name, schema_context

# (tabla, descripción) en el orden en que se informan. Se vacían todas en un solo TRUNCATE.
TABLAS = (
    ('pos_client', 'Clientes'),
    ('pos_clientcontact', 'Contactos de clientes'),
    ('policies_vehiculo', 'Vehículos (solicitudes)'),
    ('policies_cotizacion', 'Cotizaciones de los bots'),
    ('policies_cotizacionplan', 'Planes de las cotizaciones'),
    ('policies_valorexterno', 'Valores registrados a mano'),
    ('policies_historialvehiculo', 'Historial de los vehículos'),
    ('policies_correoenviado', 'Correos de cotización enviados'),
    ('policies_poliza', 'Pólizas'),
    ('policies_cuotapoliza', 'Cuotas de las pólizas'),
)
# Tablas del POS que apuntan a los clientes: un TRUNCATE … CASCADE también las vaciaría.
POS_LIGADAS = (
    ('pos_sale', 'Facturas electrónicas'),
    ('pos_order', 'Órdenes'),
    ('pos_price', 'Precios especiales por cliente'),
    ('pos_creditnote', 'Notas crédito'),
)


class Command(BaseCommand):
    help = 'Borra clientes, vehículos, solicitudes de cotización y pólizas de una empresa y reinicia sus ID.'

    def add_arguments(self, parser):
        parser.add_argument('--schema', required=True, help='Empresa (schema), ej. gali.')
        parser.add_argument('--confirmar', default='', help='Repita el schema para borrar de verdad.')
        parser.add_argument('--incluir-pos', action='store_true',
                            help='Borrar también facturas/órdenes/precios/notas crédito del POS ligados a los clientes.')

    def handle(self, *args, **opciones):
        from core.tenants.models import Client as Empresa

        schema = opciones['schema'].strip()
        if schema == get_public_schema_name():
            raise CommandError('Nunca en el schema público.')
        empresa = Empresa.objects.filter(schema_name=schema).first()
        if empresa is None:
            raise CommandError(f'No existe la empresa «{schema}».')
        borrar = opciones['confirmar'].strip() == schema

        with schema_context(schema):
            conteo = {t: self._contar(schema, t) for t, _ in TABLAS + POS_LIGADAS}
        self.stdout.write(self.style.MIGRATE_HEADING(f'\nEmpresa: {empresa.name} (schema «{schema}»)'))
        for tabla, nombre in TABLAS:
            self.stdout.write(f'  {nombre:<36} {conteo[tabla]:>8}')
        pos = [(n, conteo[t]) for t, n in POS_LIGADAS if conteo[t]]
        if pos:
            self.stdout.write(self.style.WARNING('\n  También hay datos del POS ligados a los clientes:'))
            for nombre, n in pos:
                self.stdout.write(self.style.WARNING(f'    {nombre:<34} {n:>8}'))

        if not borrar:
            self.stdout.write(self.style.NOTICE(
                f'\nNo se borró nada (solo conteo). Para borrar:\n'
                f'  venv/bin/python manage.py limpiar_clientes --schema {schema} --confirmar {schema}\n'))
            return
        if pos and not opciones['incluir_pos']:
            raise CommandError('Hay datos del POS ligados a los clientes y se borrarían con ellos. No se borró nada. '
                               'Si de verdad quiere borrarlos también, agregue --incluir-pos.')

        self.stdout.write(self.style.MIGRATE_HEADING('\n1) Respaldo de la empresa antes de borrar…'))
        try:
            call_command('respaldo_crear', schema=schema)
        except Exception as exc:
            raise CommandError(f'No se pudo sacar el respaldo ({exc}). No se borró nada.') from exc

        with schema_context(schema):
            archivos = self._archivos()
            self.stdout.write(self.style.MIGRATE_HEADING('2) Borrando y reiniciando los ID…'))
            tablas = ', '.join(f'"{schema}"."{t}"' for t, _ in TABLAS)
            with transaction.atomic(), connection.cursor() as cursor:
                cursor.execute(f'TRUNCATE TABLE {tablas} RESTART IDENTITY CASCADE')
            borrados = self._borrar_archivos(archivos)
            despues = {t: self._contar(schema, t) for t, _ in TABLAS}
        cache.clear()  # la campana de notificaciones guarda sus datos unos minutos

        self.stdout.write(self.style.MIGRATE_HEADING('3) Resultado'))
        for tabla, nombre in TABLAS:
            self.stdout.write(f'  {nombre:<36} {despues[tabla]:>8}')
        self.stdout.write(f'  PDF de cotizaciones borrados          {borrados:>8}')
        self.stdout.write(self.style.SUCCESS(f'\nListo: {empresa.name} quedó sin clientes, vehículos, solicitudes ni '
                                             'pólizas, y los ID vuelven a empezar en 1.\n'))

    @staticmethod
    def _contar(schema, tabla):
        with connection.cursor() as cursor:
            cursor.execute(f'SELECT COUNT(*) FROM "{schema}"."{tabla}"')
            return cursor.fetchone()[0]

    @staticmethod
    def _archivos():
        """(storage, nombre) de los PDF que quedarán huérfanos: se borran después de vaciar las tablas."""
        from core.policies.models import Cotizacion, ValorExterno

        archivos = []
        for modelo, campo in ((Cotizacion, 'pdf'), (ValorExterno, 'documento')):
            storage = modelo._meta.get_field(campo).storage
            for nombre in modelo.objects.exclude(**{campo: ''}).exclude(**{f'{campo}__isnull': True}).values_list(campo, flat=True):
                archivos.append((storage, nombre))
        return archivos

    def _borrar_archivos(self, archivos):
        borrados = 0
        for storage, nombre in archivos:
            try:
                if storage.exists(nombre):
                    storage.delete(nombre)
                    borrados += 1
            except Exception as exc:
                self.stdout.write(self.style.WARNING(f'  No se pudo borrar {nombre}: {exc}'))
        return borrados
