from django.apps import AppConfig


class SecurityConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'core.security'

    def ready(self):
        from django_tenants.signals import post_schema_sync
        from django_tenants.utils import schema_context

        def seed_default_roles(sender, tenant, **kwargs):
            # Un tenant nuevo nace solo con el rol "Solo lectura"; el resto de roles los crea
            # el cliente desde Seguridad > Roles y Permisos.
            from core.security.bootstrap import ensure_readonly_role
            with schema_context(tenant.schema_name):
                ensure_readonly_role()

        post_schema_sync.connect(seed_default_roles, dispatch_uid='security_seed_default_roles')
