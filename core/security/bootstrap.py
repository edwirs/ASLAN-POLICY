"""Roles iniciales de un tenant."""
from django.contrib.auth.models import Group, Permission

from core.security import registry


def ensure_readonly_role():
    """Crea (si falta) el rol "Solo lectura" en el esquema activo.

    Solo puede entrar a ver los módulos, sin crear, editar, eliminar ni ejecutar acciones.
    No toca un rol que ya exista con ese nombre (el cliente pudo haberlo personalizado).
    Devuelve ``(rol, creado)``.
    """
    role, created = Group.objects.get_or_create(name=registry.READONLY_ROLE_NAME)
    if created:
        wanted = set(registry.readonly_permissions())
        perms = [
            p.pk for p in Permission.objects.select_related('content_type')
            if f'{p.content_type.app_label}.{p.codename}' in wanted
        ]
        role.permissions.set(perms)
    return role, created
