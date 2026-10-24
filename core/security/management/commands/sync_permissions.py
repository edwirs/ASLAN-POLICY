from django.apps import apps
from django.contrib.auth.models import Group, Permission
from django.contrib.contenttypes.models import ContentType
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django_tenants.utils import get_public_schema_name, get_tenant_model, schema_context

from core.security import registry


class Command(BaseCommand):
    help = (
        'Sincroniza los permisos del registro (core/security/registry.py) en cada tenant: '
        'crea los que falten, deja sus descripciones en español, entrega los permisos nuevos '
        'a los roles que tenían los antiguos y le da todo al rol Administrador. '
        'Es idempotente: se puede correr en cada despliegue.'
    )

    def add_arguments(self, parser):
        parser.add_argument('--schema', help='Solo este esquema (por defecto, todos los tenants).')
        parser.add_argument('--dry-run', action='store_true', help='Muestra qué haría sin guardar nada.')
        parser.add_argument('--admin-group', default='Administrador',
                            help='Nombre del rol que recibe todos los permisos (por defecto "Administrador").')
        parser.add_argument('--create-admin-role', action='store_true',
                            help='Crea el rol Administrador si el tenant no lo tiene.')
        parser.add_argument('--create-readonly-role', action='store_true',
                            help='Crea el rol "Solo lectura" si el tenant no lo tiene (los nuevos ya lo reciben solos).')

    def handle(self, *args, **options):
        errors = registry.validate()
        if errors:
            raise CommandError('El registro de permisos es inconsistente:\n  - ' + '\n  - '.join(errors))

        if options['schema']:
            schemas = [options['schema']]
        else:
            schemas = list(
                get_tenant_model().objects.exclude(schema_name=get_public_schema_name())
                .values_list('schema_name', flat=True)
            )
        if not schemas:
            self.stdout.write('No hay tenants para sincronizar.')
            return

        for schema in schemas:
            self.stdout.write(self.style.MIGRATE_HEADING(f'== Tenant "{schema}" =='))
            with schema_context(schema):
                if options['dry_run']:
                    self.sync_schema(options)
                else:
                    with transaction.atomic():
                        self.sync_schema(options)

    def sync_schema(self, options):
        dry = options['dry_run']
        created = renamed = 0
        perm_objs = {}
        declared = set()

        for model_key, perms in registry.PERMISSIONS.items():
            app_label, model_name = model_key.split('.')
            content_type = ContentType.objects.get_for_model(
                apps.get_model(app_label, model_name), for_concrete_model=False)
            for codename, label in perms:
                declared.add((app_label, codename))
                perm = Permission.objects.filter(content_type=content_type, codename=codename).first()
                if perm is None:
                    created += 1
                    if not dry:
                        perm = Permission.objects.create(content_type=content_type, codename=codename, name=label)
                elif perm.name != label:
                    renamed += 1
                    if not dry:
                        perm.name = label
                        perm.save(update_fields=['name'])
                perm_objs[f'{app_label}.{codename}'] = perm

        # Compatibilidad: quien tenía el permiso antiguo recibe los nuevos (solo se agrega).
        granted = 0
        for old, new_list in registry.LEGACY_MAP.items():
            old_app, old_code = old.split('.')
            old_perm = Permission.objects.filter(content_type__app_label=old_app, codename=old_code).first()
            if old_perm is None:
                continue
            for group in Group.objects.filter(permissions=old_perm):
                current = set(group.permissions.values_list('pk', flat=True))
                missing = [perm_objs[n] for n in new_list if perm_objs.get(n) and perm_objs[n].pk not in current]
                if missing:
                    granted += len(missing)
                    if not dry:
                        group.permissions.add(*missing)

        if options['create_readonly_role'] and not dry:
            from core.security.bootstrap import ensure_readonly_role
            role, was_created = ensure_readonly_role()
            self.stdout.write(f'  rol "{role.name}": {"creado" if was_created else "ya existía"}')

        # El rol Administrador recibe todo el catálogo.
        admin_added = 0
        admin = Group.objects.filter(name=options['admin_group']).first()
        if admin is None and options['create_admin_role'] and not dry:
            admin = Group.objects.create(name=options['admin_group'])
            self.stdout.write(f'  rol "{admin.name}": creado')
        if admin:
            current = set(admin.permissions.values_list('pk', flat=True))
            missing = [p for p in perm_objs.values() if p is not None and p.pk not in current]
            admin_added = len(missing)
            if missing and not dry:
                admin.permissions.add(*missing)

        # Permisos que existen en la BD pero no están en el registro: modelos auxiliares
        # (catálogos, detalles) o permisos retirados. Solo se informa, nunca se borra.
        known_apps = {k.split('.')[0] for k in registry.PERMISSIONS}
        outside = [
            p for p in Permission.objects.filter(content_type__app_label__in=known_apps)
            if (p.content_type.app_label, p.codename) not in declared
        ]
        in_use = sum(1 for p in outside if Group.objects.filter(permissions=p).exists())

        prefix = '[simulación] ' if dry else ''
        self.stdout.write(f'  {prefix}permisos creados: {created} | descripciones actualizadas: {renamed}')
        self.stdout.write(f'  {prefix}permisos nuevos entregados a roles por compatibilidad: {granted}')
        if admin:
            self.stdout.write(f'  {prefix}permisos agregados a "{admin.name}": {admin_added}')
        else:
            self.stdout.write(self.style.WARNING(f'  No existe el rol "{options["admin_group"]}"; se omitió.'))
        self.stdout.write(
            f'  permisos fuera del registro (modelos auxiliares o retirados): {len(outside)} '
            f'({in_use} asignados a algún rol; no se borra nada)'
        )
