from django.core.management.base import BaseCommand
from django.db import transaction
from django_tenants.utils import schema_context

from core.policies.models import Aseguradora, CoberturaAseguradora
from core.policies.services.coberturas import CAMPOS
from core.policies.services.coberturas_semilla import FICHAS, REVISAR

# Aseguradoras que cotizan por terceros (no tienen portal ni bot): se crean si faltan.
SIN_BOT = ('Bolívar', 'Allianz', 'Sura')


class Command(BaseCommand):
    help = (
        'Carga las fichas de coberturas del cuadro comparativo (COMPARATIVO.docx) en las aseguradoras registradas '
        'y crea Bolívar, Allianz y Sura (sin bot) si faltan. No pisa fichas ya existentes (se pueden haber editado), '
        'salvo con --forzar. Una aseguradora del comparativo que no esté registrada (ej. Mapfre) se omite.'
    )

    def add_arguments(self, parser):
        parser.add_argument('--schema', required=True, help='Schema del tenant (ej. gali)')
        parser.add_argument('--forzar', action='store_true', help='Reemplaza también las fichas que ya existen.')

    def handle(self, *args, **options):
        with schema_context(options['schema']), transaction.atomic():
            for nombre in SIN_BOT:
                aseguradora, creada = Aseguradora.objects.get_or_create(name=nombre)
                if creada:
                    self.stdout.write(f'Aseguradora creada (sin bot): {nombre}')

            creadas = actualizadas = omitidas = 0
            for (nombre, producto), datos in FICHAS.items():
                aseguradora = Aseguradora.objects.filter(name=nombre).first()
                if aseguradora is None:
                    self.stdout.write(self.style.WARNING(f'  {nombre} no está registrada: se omite ({producto}).'))
                    continue
                valores = {campo: datos[campo] for campo in CAMPOS}
                observaciones = 'Cargado del comparativo COMPARATIVO.docx (octubre 2026). Revisar y corregir si hace falta.'
                if REVISAR.get((nombre, producto)):
                    campos = ', '.join(REVISAR[(nombre, producto)])
                    observaciones += f' Texto cortado en el comparativo: {campos}.'
                ficha = CoberturaAseguradora.objects.filter(aseguradora=aseguradora, producto=producto).first()
                if ficha is None:
                    CoberturaAseguradora.objects.create(aseguradora=aseguradora, producto=producto, observaciones=observaciones, **valores)
                    creadas += 1
                elif options['forzar']:
                    for campo, valor in valores.items():
                        setattr(ficha, campo, valor)
                    ficha.save()
                    actualizadas += 1
                else:
                    omitidas += 1
            self.stdout.write(self.style.SUCCESS(
                f'Fichas creadas: {creadas} | reemplazadas: {actualizadas} | ya existían (sin tocar): {omitidas}'))
