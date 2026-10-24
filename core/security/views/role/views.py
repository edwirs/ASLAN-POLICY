import json

from django.contrib.auth.models import Permission
from django.db import transaction
from django.http import HttpResponse
from django.urls import reverse_lazy
from django.views.generic import CreateView, DeleteView, TemplateView, UpdateView

from core.security import registry
from core.security.mixins import StrictPermissionMixin
from core.security.models import Role

MODULE_NAME = 'Roles y Permisos'


def _json(data, status=200):
    return HttpResponse(json.dumps(data), content_type='application/json', status=status)


def _registry_keys():
    return set(registry.permission_labels())


def _group_keys(group):
    """Permisos del catálogo que tiene un rol, como ``app.codename``."""
    valid = _registry_keys()
    keys = {f'{app}.{code}' for app, code in group.permissions.values_list('content_type__app_label', 'codename')}
    return keys & valid


def _with_view_permissions(keys):
    """Si un módulo tiene alguna acción marcada, su permiso de ver va incluido (sin él no podría entrar)."""
    keys = set(keys)
    for item in registry.iter_items():
        if item.view_perm and keys & set(item.perms):
            keys.add(item.view_perm)
    return keys


def _permission_objects(keys):
    objs = {}
    for perm in Permission.objects.select_related('content_type'):
        full = f'{perm.content_type.app_label}.{perm.codename}'
        if full in keys:
            objs[full] = perm
    return objs


def _user_keeps_access(user, role, new_keys):
    """Evita que quien edita un rol se quite a sí mismo el acceso a esta pantalla."""
    if user.is_superuser or not role.user_set.filter(pk=user.pk).exists():
        return True
    needed = {'security.view_role', 'security.change_role'}
    granted = set(new_keys)
    for other in user.groups.exclude(pk=role.pk):
        granted |= {f'{a}.{c}' for a, c in other.permissions.values_list('content_type__app_label', 'codename')}
    return needed <= granted


def _save_role(request, role=None):
    name = (request.POST.get('name') or '').strip()
    if not name:
        return {'error': 'Ingrese el nombre del rol.'}
    if len(name) > 150:
        return {'error': 'El nombre del rol no puede superar 150 caracteres.'}
    if name.lower() == registry.ADMIN_ROLE_NAME.lower() and (role is None or role.name != registry.ADMIN_ROLE_NAME):
        return {'error': f'El nombre "{registry.ADMIN_ROLE_NAME}" está reservado para el rol del sistema.'}
    duplicates = Role.objects.filter(name__iexact=name)
    if role is not None:
        duplicates = duplicates.exclude(pk=role.pk)
    if duplicates.exists():
        return {'error': 'Ya existe un rol con ese nombre.'}

    keys = _with_view_permissions(set(request.POST.getlist('permissions')) & _registry_keys())
    if role is not None and not _user_keeps_access(request.user, role, keys):
        return {'error': 'No puede quitarse a usted mismo el acceso a "Roles y Permisos" (Ver y Editar roles).'}

    objs = _permission_objects(keys)
    with transaction.atomic():
        if role is None:
            role = Role.objects.create(name=name)
            current_outside = set()
        else:
            role.name = name
            role.save(update_fields=['name'])
            valid = _registry_keys()
            current_outside = {
                p.pk for p in role.permissions.select_related('content_type')
                if f'{p.content_type.app_label}.{p.codename}' not in valid
            }
        # Los permisos fuera del catálogo (modelos auxiliares) se conservan tal cual.
        role.permissions.set([p.pk for p in objs.values()] + list(current_outside))
    return {}


class RoleMatrixMixin:
    """Datos que necesita la pantalla con la matriz de permisos."""

    def matrix_context(self, selected, readonly=False):
        roles = {r.pk: sorted(_group_keys(r)) for r in Role.objects.exclude(name=registry.ADMIN_ROLE_NAME)}
        preview = []

        def walk(nodes):
            out = []
            for node in nodes:
                if isinstance(node, registry.Section):
                    out.append({'label': node.label, 'icon': node.icon, 'children': walk(node.children)})
                else:
                    out.append({'label': node.label, 'icon': node.icon, 'perm': node.view_perm})
            return out

        preview = walk(registry.MENU)
        return {
            'matrix': registry.matrix_sections(),
            'selected': sorted(selected),
            'readonly': readonly,
            'roles_options': [{'id': r.pk, 'name': r.name} for r in Role.objects.exclude(name=registry.ADMIN_ROLE_NAME).order_by('name')],
            'roles_perms': roles,
            'menu_preview': preview,
            'module_name': MODULE_NAME,
            'list_url': reverse_lazy('role_list'),
        }


class RoleListView(StrictPermissionMixin, TemplateView):
    template_name = 'role/list.html'
    permission_required = 'security.view_role'

    def post(self, request, *args, **kwargs):
        action = request.POST.get('action')
        if action != 'search':
            return _json({'error': 'No ha seleccionado ninguna opción'})
        valid = _registry_keys()
        data = []
        for role in Role.objects.all().order_by('name'):
            keys = _group_keys(role)
            is_system = role.name == registry.ADMIN_ROLE_NAME
            data.append({
                'id': role.pk,
                'name': role.name,
                'is_system': is_system,
                'permissions': len(valid) if is_system else len(keys),
                'total': len(valid),
                'users': role.user_set.count(),
            })
        return _json(data)

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['title'] = 'Listado de Roles'
        context['list_url'] = reverse_lazy('role_list')
        if self.request.user.has_perm('security.add_role'):
            context['create_url'] = reverse_lazy('role_create')
        context['module_name'] = MODULE_NAME
        return context


class RoleCreateView(StrictPermissionMixin, RoleMatrixMixin, CreateView):
    template_name = 'role/form.html'
    model = Role
    fields = ['name']
    permission_required = 'security.add_role'
    success_url = reverse_lazy('role_list')

    def post(self, request, *args, **kwargs):
        if request.POST.get('action') != 'add':
            return _json({'error': 'No ha seleccionado ninguna opción'})
        try:
            return _json(_save_role(request))
        except Exception as e:
            return _json({'error': str(e)})

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context.update(self.matrix_context(selected=set()))
        context['title'] = 'Nuevo Rol'
        context['action'] = 'add'
        context['role_name'] = ''
        return context


class RoleUpdateView(StrictPermissionMixin, RoleMatrixMixin, UpdateView):
    template_name = 'role/form.html'
    model = Role
    fields = ['name']
    permission_required = 'security.change_role'
    success_url = reverse_lazy('role_list')

    def is_system(self):
        return self.object.name == registry.ADMIN_ROLE_NAME

    def post(self, request, *args, **kwargs):
        self.object = self.get_object()
        if self.is_system():
            return _json({'error': 'El rol Administrador es del sistema: siempre tiene todos los permisos y no se puede modificar.'})
        if request.POST.get('action') != 'edit':
            return _json({'error': 'No ha seleccionado ninguna opción'})
        try:
            return _json(_save_role(request, self.object))
        except Exception as e:
            return _json({'error': str(e)})

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        system = self.is_system()
        selected = _registry_keys() if system else _group_keys(self.object)
        context.update(self.matrix_context(selected=selected, readonly=system))
        context['title'] = 'Edición del Rol'
        context['action'] = 'edit'
        context['role_name'] = self.object.name
        context['users_count'] = self.object.user_set.count()
        return context


class RoleDeleteView(StrictPermissionMixin, DeleteView):
    model = Role
    template_name = 'delete.html'
    success_url = reverse_lazy('role_list')
    permission_required = 'security.delete_role'

    def post(self, request, *args, **kwargs):
        try:
            role = self.get_object()
            if role.name == registry.ADMIN_ROLE_NAME:
                return _json({'error': 'El rol Administrador es del sistema y no se puede eliminar.'})
            count = role.user_set.count()
            if count:
                return _json({'error': f'No se puede eliminar: el rol tiene {count} usuario(s) asignado(s). '
                                       'Cámbieles el rol primero.'})
            role.delete()
            return _json({})
        except Exception as e:
            return _json({'error': str(e)})

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['title'] = 'Eliminación de un Rol'
        context['list_url'] = self.success_url
        context['module_name'] = MODULE_NAME
        return context
