import django.utils.timezone
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('policies', '0002_alter_vehiculo_modelo_alter_vehiculo_referencia'),
    ]

    operations = [
        migrations.AddField(
            model_name='vehiculo',
            name='created_at',
            field=models.DateTimeField(auto_now_add=True, default=django.utils.timezone.now, verbose_name='Fecha de registro'),
            preserve_default=False,
        ),
    ]
