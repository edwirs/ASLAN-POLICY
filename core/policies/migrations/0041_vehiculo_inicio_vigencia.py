"""Inicio de vigencia de la póliza para solicitudes nuevas y la palabra «renovación» del correo parametrizada.

- `Vehiculo.inicio_vigencia`: la escribe el asesor en la modal del comparativo cuando el vehículo aún no tiene póliza con
  nosotros (con póliza se toma sola: el día siguiente al fin de la vigencia).
- En las plantillas de correo «para la renovación de la póliza» pasa a «para la {tramite} de la póliza»: {tramite} vale
  «renovación» si el vehículo ya tiene póliza con nosotros y «emisión» si es una solicitud nueva. Solo cambia el texto
  que venía de fábrica; si una empresa lo reescribió, se respeta.
"""
import re

from django.db import migrations, models

ANTERIOR = re.compile(r'para la renovaci(?:ó|&oacute;)n de la p(?:ó|&oacute;)liza', re.I)
NUEVO = 'para la {tramite} de la póliza'


def adelante(apps, schema_editor):
    PlantillaCorreo = apps.get_model('policies', 'PlantillaCorreo')
    for plantilla in PlantillaCorreo.objects.all():
        cuerpo = ANTERIOR.sub(NUEVO, plantilla.cuerpo or '')
        if cuerpo != plantilla.cuerpo:
            plantilla.cuerpo = cuerpo
            plantilla.save(update_fields=['cuerpo'])


def atras(apps, schema_editor):
    PlantillaCorreo = apps.get_model('policies', 'PlantillaCorreo')
    for plantilla in PlantillaCorreo.objects.filter(cuerpo__contains=NUEVO):
        plantilla.cuerpo = plantilla.cuerpo.replace(NUEVO, 'para la renovación de la póliza')
        plantilla.save(update_fields=['cuerpo'])


class Migration(migrations.Migration):

    dependencies = [
        ('policies', '0040_mapfre_super_trebol'),
    ]

    operations = [
        migrations.AddField(
            model_name='vehiculo',
            name='inicio_vigencia',
            field=models.DateField(blank=True, null=True, verbose_name='Fecha inicio de vigencia de la póliza'),
        ),
        migrations.RunPython(adelante, atras),
    ]
