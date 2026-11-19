"""Mapfre: el producto que cuenta en el comparativo pasa a ser «Super Trebol» (antes «Super Trebol 117»).

Solo cambia las credenciales que tenían guardado el valor anterior por defecto; si una empresa eligió otro producto, se
respeta. Las que no lo tienen guardado ya toman el nuevo valor por defecto (services/credenciales.py)."""
from django.db import migrations

ANTERIOR = 'super trebol 117'
NUEVO = 'Super Trebol'


def _normalizar(texto):
    return ' '.join(str(texto or '').split()).lower()


def adelante(apps, schema_editor):
    Credencial = apps.get_model('policies', 'AseguradoraCredencial')
    for credencial in Credencial.objects.filter(aseguradora__name='Mapfre'):
        parametros = dict(credencial.parametros or {})
        if _normalizar(parametros.get('producto_destacado')) == ANTERIOR:
            parametros['producto_destacado'] = NUEVO
            credencial.parametros = parametros
            credencial.save(update_fields=['parametros'])


class Migration(migrations.Migration):

    dependencies = [
        ('policies', '0039_cola_correos'),
    ]

    operations = [
        migrations.RunPython(adelante, migrations.RunPython.noop),
    ]
