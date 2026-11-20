"""Módulo «Seguimiento de correos» (Cotizador): permiso para verlo y uno por cada acción sobre la cola.

- Ver el módulo y cancelar un pendiente: los reciben los roles que ya pueden enviar la cotización por correo (antes
  cancelaban con ese permiso), para que nada cambie al actualizar.
- Enviar ahora, corregir destinatarios, reprogramar y reintentar: solo el rol Administrador; a los demás se les dan en
  Roles y Permisos.
Solo agrega: no quita permisos a nadie."""
from django.db import migrations

PERMISOS = (
    ('send_cotizacion_correo', 'Enviar la cotización por correo al cliente'),
    ('view_correoenviado', 'Ver el seguimiento de correos (enviados, pendientes de envío y con error)'),
    ('cancel_correoenviado', 'Cancelar el envío de un correo pendiente'),
    ('send_correoenviado_ahora', 'Enviar ya un correo pendiente, sin esperar la hora hábil'),
    ('change_correoenviado', 'Corregir los destinatarios (Para y CC) de un correo pendiente o con error'),
    ('reprogram_correoenviado', 'Reprogramar la fecha y hora de envío de un correo pendiente'),
    ('retry_correoenviado', 'Reintentar el envío de un correo que no salió'),
)
DE_QUIEN_ENVIA = ('view_correoenviado', 'cancel_correoenviado')


def adelante(apps, schema_editor):
    ContentType = apps.get_model('contenttypes', 'ContentType')
    Permission = apps.get_model('auth', 'Permission')
    Group = apps.get_model('auth', 'Group')
    tipo, _ = ContentType.objects.get_or_create(app_label='policies', model='correoenviado')
    permisos = {codename: Permission.objects.get_or_create(content_type=tipo, codename=codename, defaults={'name': nombre})[0]
                for codename, nombre in PERMISOS}
    for grupo in Group.objects.filter(permissions=permisos['send_cotizacion_correo']):
        grupo.permissions.add(*[permisos[c] for c in DE_QUIEN_ENVIA])
    for grupo in Group.objects.filter(name='Administrador'):
        grupo.permissions.add(*permisos.values())


class Migration(migrations.Migration):

    dependencies = [
        ('policies', '0042_plantilla_promocion_solo_mejores'),
        ('auth', '0012_alter_user_first_name_max_length'),
        ('contenttypes', '0002_remove_content_type_name'),
    ]

    operations = [
        migrations.AlterModelOptions(
            name='correoenviado',
            options={'default_permissions': (), 'ordering': ['-created_at', '-id'], 'permissions': PERMISOS,
                     'verbose_name': 'Correo enviado', 'verbose_name_plural': 'Correos enviados'},
        ),
        migrations.RunPython(adelante, migrations.RunPython.noop),
    ]
