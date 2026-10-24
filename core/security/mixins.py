from crum import get_current_request
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.http import HttpResponseRedirect
from django.utils.decorators import method_decorator

from config import settings


class GroupSessionMixin(object):
    @method_decorator(login_required)
    def dispatch(self, request, *args, **kwargs):
        if request.user.is_superuser:
            return super().dispatch(request, *args, **kwargs)
        if 'group' not in request.session:
            return HttpResponseRedirect(settings.LOGIN_REDIRECT_URL)
        return super().dispatch(request, *args, **kwargs)


class GroupPermissionMixin(GroupSessionMixin, object):
    permission_required = None

    def get_permissions(self):
        permissions = []
        if isinstance(self.permission_required, str):
            permissions.append(self.permission_required)
        else:
            permissions = list(self.permission_required)
        return permissions

    @staticmethod
    def has_permission(group, permission):
        """Comprueba un permiso de grupo, admitiendo ``app_label.codename``.

        Los codenames no son globalmente únicos: por ejemplo, ``tenants.Client``
        y ``pos.Client`` pueden tener ambos ``view_client``. Para los permisos
        calificados se debe comprobar también la aplicación que los define.
        """
        if '.' in permission:
            app_label, codename = permission.split('.', 1)
            return group.permissions.filter(
                content_type__app_label=app_label,
                codename=codename,
            ).exists()
        return group.permissions.filter(codename=permission).exists()

    def get_last_url(self):
        request = get_current_request()
        if 'url_last' in request.session:
            if request.session['url_last'] != request.path:
                return request.session['url_last']
        return settings.LOGIN_REDIRECT_URL

    def get(self, request, *args, **kwargs):
        if request.user.is_superuser:
            request.session['url_last'] = request.path
            return super().get(request, *args, **kwargs)
        group = request.session.get('group')
        permission_list = self.get_permissions()
        if not group or not all(self.has_permission(group, permission) for permission in permission_list):
            messages.error(request, 'Tu perfil no cuenta con el permiso necesario para ingresar')
            return HttpResponseRedirect(self.get_last_url())
        request.session['url_last'] = request.path
        return super().get(request, *args, **kwargs)


class StrictPermissionMixin(object):
    """Exige los permisos en TODOS los métodos HTTP (GET y POST) y con la unión de roles.

    A diferencia de ``GroupPermissionMixin`` (que solo revisa el GET y el rol activo en la
    sesión), aquí se usa ``user.has_perms``: un usuario con varios roles tiene la unión de
    sus permisos. ``permission_required`` usa nombres calificados ``app.codename``.
    """
    permission_required = ()

    def get_permissions(self):
        if isinstance(self.permission_required, str):
            return [self.permission_required]
        return list(self.permission_required)

    def dispatch(self, request, *args, **kwargs):
        if not request.user.is_authenticated:
            return self.handle_no_permission(request)
        if not request.user.has_perms(self.get_permissions()):
            return self.handle_no_permission(request, forbidden=True)
        return super().dispatch(request, *args, **kwargs)

    def handle_no_permission(self, request, forbidden=False):
        from django.http import JsonResponse
        from django.contrib.auth.views import redirect_to_login
        message = 'Su perfil no cuenta con el permiso necesario para realizar esta acción.'
        if request.method != 'GET' or request.headers.get('x-requested-with') == 'XMLHttpRequest':
            return JsonResponse({'error': message}, status=403 if forbidden else 401)
        if forbidden:
            messages.error(request, message)
            return HttpResponseRedirect(settings.LOGIN_REDIRECT_URL)
        return redirect_to_login(request.get_full_path())
