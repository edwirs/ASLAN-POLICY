import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('pos', '0018_alter_client_options_client_commercial_name_and_more'),
        ('policies', '0007_aseguradoracredencial_sucursal'),
    ]

    operations = [
        migrations.AddField(
            model_name='cotizacion',
            name='tomador',
            field=models.ForeignKey(
                default=1,
                help_text='Dueño del vehículo al momento de esta cotización. No cambia si el vehículo cambia de '
                          'propietario después, para no alterar el historial.',
                on_delete=django.db.models.deletion.PROTECT,
                related_name='cotizaciones',
                to='pos.client',
                verbose_name='Tomador',
            ),
            preserve_default=False,
        ),
    ]
