"""Seguimiento de correos: permiso para «Reenviar» un correo ya enviado (el cliente no lo encuentra).

Lo reciben los roles que pueden enviar la cotización por correo (reenviar es volver a enviar lo mismo) y el
Administrador. Solo agrega: no quita permisos a nadie."""
from django.db import migrations

PERMISOS = (
    ('send_cotizacion_correo', 'Enviar la cotización por correo al cliente'),
    ('view_correoenviado', 'Ver el seguimiento de correos (enviados, pendientes de envío y con error)'),
    ('cancel_correoenviado', 'Cancelar el envío de un correo pendiente'),
    ('send_correoenviado_ahora', 'Enviar ya un correo pendiente, sin esperar la hora hábil'),
    ('change_correoenviado', 'Corregir los destinatarios (Para y CC) de un correo pendiente o con error'),
    ('reprogram_correoenviado', 'Reprogramar la fecha y hora de envío de un correo pendiente'),
    ('retry_correoenviado', 'Reintentar el envío de un correo que no salió'),
    ('resend_correoenviado', 'Reenviar un correo ya enviado (el mismo correo, a los mismos u otros destinatarios)'),
)


def adelante(apps, schema_editor):
    ContentType = apps.get_model('contenttypes', 'ContentType')
    Permission = apps.get_model('auth', 'Permission')
    Group = apps.get_model('auth', 'Group')
    tipo, _ = ContentType.objects.get_or_create(app_label='policies', model='correoenviado')
    codename, nombre = PERMISOS[-1]
    reenviar, _ = Permission.objects.get_or_create(content_type=tipo, codename=codename, defaults={'name': nombre})
    enviar = Permission.objects.filter(content_type=tipo, codename='send_cotizacion_correo').first()
    grupos = Group.objects.filter(name='Administrador')
    if enviar is not None:
        grupos = grupos | Group.objects.filter(permissions=enviar)
    for grupo in grupos.distinct():
        grupo.permissions.add(reenviar)


class Migration(migrations.Migration):

    dependencies = [
        ('policies', '0043_permiso_seguimiento_correos'),
    ]

    operations = [
        migrations.AlterModelOptions(
            name='correoenviado',
            options={'default_permissions': (), 'ordering': ['-created_at', '-id'], 'permissions': PERMISOS,
                     'verbose_name': 'Correo enviado', 'verbose_name_plural': 'Correos enviados'},
        ),
        migrations.RunPython(adelante, migrations.RunPython.noop),
    ]
