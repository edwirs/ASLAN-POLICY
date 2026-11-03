from django.db import migrations

# Antes esta migración sembraba en cada empresa una credencial de Factus escrita aquí mismo (secretos en el código).
# Ya se aplicó donde hacía falta; se deja vacía para que el archivo pueda ir al repositorio sin credenciales y la cadena
# de migraciones siga completa. Las credenciales de Factus se cargan desde la pantalla «Credenciales Factus» de cada empresa.


def noop(apps, schema_editor):
    pass


class Migration(migrations.Migration):

    dependencies = [
        ('pos', '0028_factuscredential'),
    ]

    operations = [
        migrations.RunPython(noop, noop),
    ]
