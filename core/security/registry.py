"""Catálogo único de permisos y módulos de ASLAN MultiAgente de Seguros.

Es la fuente de verdad de tres cosas, para que nunca se desincronicen:

1. ``PERMISSIONS``: permisos de cada modelo, con su descripción en español.
2. ``MENU``: estructura del menú lateral. Cada ítem declara qué permiso lo hace
   visible; un padre aparece solo si al menos un hijo es visible.
3. ``Item.perms``: permisos que se administran por módulo en la pantalla de
   roles (matriz módulo x acción).

Este archivo es solo datos: no importa modelos, para poder usarse desde
``models.py`` sin dependencias circulares.

Convención: ``view_*`` Ver, ``add_*`` Crear, ``change_*`` Editar,
``delete_*`` Eliminar, más las acciones propias de cada módulo. Los codenames
que ya existían se conservan para no perder las asignaciones de los roles
actuales; solo cambia la descripción (a español).
"""
from dataclasses import dataclass
from typing import Optional, Tuple

# Rol del sistema: siempre tiene todos los permisos y no se puede editar ni borrar.
ADMIN_ROLE_NAME = 'Administrador'

_VERBS = {'view': 'Ver', 'add': 'Crear', 'change': 'Editar', 'delete': 'Eliminar'}
_CRUD = ('view', 'add', 'change', 'delete')


def crud(suffix, plural, actions=_CRUD):
    """Permisos estándar de un modelo: [(codename, descripción), ...]."""
    return [(f'{a}_{suffix}', f'{_VERBS[a]} {plural}') for a in actions]


def crud_q(app, suffix, actions=_CRUD):
    """Mismos permisos de ``crud`` pero como nombres calificados ``app.codename``."""
    return tuple(f'{app}.{a}_{suffix}' for a in actions)


def q(app, *codenames):
    return tuple(f'{app}.{c}' for c in codenames)


# --------------------------------------------------------------------------
# Permisos por modelo ('app_label.NombreModelo' -> [(codename, descripción)])
# --------------------------------------------------------------------------
PERMISSIONS = {
    # Catálogos
    'pos.Client': crud('client', 'clientes'),
    'pos.Category': crud('category', 'categorías'),
    'pos.Product': crud('product', 'productos'),

    # Facturas
    'pos.Sale': [
        ('view_sale', 'Ver facturas electrónicas'),
        ('add_sale', 'Crear facturas electrónicas'),
        ('delete_sale', 'Eliminar facturas electrónicas'),
    ],
    'pos.CreditNote': crud('creditnote', 'notas crédito', ('view', 'add', 'delete')),

    # Cotizador y vehículos
    'policies.Vehiculo': [
        ('view_vehiculo', 'Ver solicitudes de cotización'),
        ('add_vehiculo', 'Crear solicitudes de cotización'),
        ('view_vehiculo_registrado', 'Ver vehículos registrados'),
        ('view_comparativo', 'Ver el comparativo de aseguradoras de un vehículo'),
        ('add_valor_externo', 'Registrar valores de aseguradoras sin bot'),
        ('use_asistente', 'Usar el asistente Aslani (chat de consultas)'),
    ],

    # Configuraciones
    'pos.Company': [
        ('view_company', 'Ver los datos de la empresa'),
    ],
    'pos.FactusCredential': crud('factuscredential', 'credenciales de Factus'),
    'security.Dashboard': [
        ('view_dashboard', 'Ver la configuración del dashboard'),
    ],
    'policies.Aseguradora': [
        ('view_aseguradora', 'Ver aseguradoras y sus datos de acceso'),
        ('add_aseguradora', 'Crear aseguradoras'),
        ('change_aseguradora', 'Editar datos de acceso y activar o inactivar aseguradoras'),
    ],
    'policies.Asesor': [
        ('view_asesor', 'Ver asesores internos y externos'),
        ('add_asesor', 'Crear asesores'),
        ('change_asesor', 'Editar asesores, su comisión y activarlos o inactivarlos'),
    ],

    # Seguridad
    'user.User': crud('user', 'usuarios'),
    'security.Role': crud('role', 'roles'),
    'security.UserAccess': [
        ('view_user_access', 'Ver accesos de usuarios'),
        ('delete_user_access', 'Eliminar accesos de usuarios'),
    ],
}


def perms_for(model_key):
    """Tupla para ``Meta.permissions`` del modelo ``'app.Modelo'``."""
    return tuple(PERMISSIONS[model_key])


# --------------------------------------------------------------------------
# Menú lateral / módulos
# --------------------------------------------------------------------------
@dataclass(frozen=True)
class Item:
    key: str
    label: str
    url_name: str
    # Permiso ``app.codename`` que hace visible el ítem; None = cualquier
    # usuario autenticado (p. ej. cambiar su propia contraseña).
    view_perm: Optional[str]
    # Permisos que se administran para este módulo en la matriz de roles.
    # Un ítem sin ``perms`` aparece en el menú pero no en la matriz (su permiso
    # de entrada se administra en otro módulo).
    perms: Tuple[str, ...] = ()
    icon: str = 'far fa-circle'
    # Módulo comercial al que pertenece ('cotizador', 'asesores', 'cartera'): si la empresa no lo contrató, el ítem no sale en el menú.
    modulo: str = ''


@dataclass(frozen=True)
class Section:
    label: str
    icon: str
    children: tuple = ()


MENU = (
    Item('clients', 'Clientes', 'client_list', 'pos.view_client',
         crud_q('pos', 'client'), icon='fas fa-user-plus'),
    Item('categories', 'Categorías', 'category_list', 'pos.view_category',
         crud_q('pos', 'category'), icon='fas fa-layer-group'),
    Item('products', 'Productos', 'product_list', 'pos.view_product',
         crud_q('pos', 'product'), icon='fas fa-boxes'),
    Section('Facturas', 'fas fa-file-text', (
        Item('electronic_invoices', 'Facturas Electrónicas', 'sale_Fe_admin_list', 'pos.view_sale',
             q('pos', 'view_sale', 'add_sale', 'delete_sale')),
        Item('credit_notes', 'Notas Crédito', 'credit_note_Fe_admin_list', 'pos.view_creditnote',
             crud_q('pos', 'creditnote', ('view', 'add', 'delete'))),
    )),
    Section('Cotizador', 'fa-solid fa-car-side', (
        Item('quote_new', 'Nueva solicitud', 'solicitud_cotizacion_create', 'policies.add_vehiculo', modulo='cotizador'),
        Item('quote_list', 'Solicitudes registradas', 'vehiculo_list', 'policies.view_vehiculo',
             q('policies', 'view_vehiculo', 'add_vehiculo', 'view_comparativo', 'add_valor_externo', 'use_asistente'), modulo='cotizador'),
    )),
    Section('Vehículos', 'fa-solid fa-car', (
        Item('vehicles', 'Vehículos registrados', 'vehiculo_registrado_list', 'policies.view_vehiculo_registrado',
             q('policies', 'view_vehiculo_registrado'), modulo='cotizador'),
    )),
    Section('Configuraciones', 'fas fa-wrench', (
        Section('Generales', 'fas fa-sliders-h', (
            Item('company', 'Compañia', 'company_update', 'pos.view_company',
                 q('pos', 'view_company')),
            Item('factus_credentials', 'Credenciales Factus', 'factus_credential_list',
                 'pos.view_factuscredential', crud_q('pos', 'factuscredential')),
            Item('dashboard_config', 'Conf. Dashboard', 'dashboard_update', 'security.view_dashboard',
                 q('security', 'view_dashboard')),
            Item('profile', 'Actualizar Perfil', 'user_update_profile', None),
        )),
        Item('insurers', 'Aseguradoras', 'aseguradora_list', 'policies.view_aseguradora',
             q('policies', 'view_aseguradora', 'add_aseguradora', 'change_aseguradora'), modulo='cotizador'),
        Item('advisors', 'Asesores', 'asesor_list', 'policies.view_asesor',
             q('policies', 'view_asesor', 'add_asesor', 'change_asesor'), modulo='asesores'),
    )),
    Section('Seguridad', 'fas fa-lock', (
        Item('users', 'Usuarios', 'user_list', 'user.view_user', crud_q('user', 'user')),
        Item('roles', 'Roles y Permisos', 'role_list', 'security.view_role', crud_q('security', 'role')),
        Item('user_access', 'Accesos', 'user_access_list', 'security.view_user_access',
             q('security', 'view_user_access', 'delete_user_access')),
        Item('password', 'Actualizar Contraseña', 'user_update_password', None),
    )),
)


def iter_items(nodes=MENU):
    """Recorre todos los ``Item`` del menú (aplanando las secciones)."""
    for node in nodes:
        if isinstance(node, Section):
            yield from iter_items(node.children)
        else:
            yield node


# --------------------------------------------------------------------------
# Compatibilidad: quien tenía el permiso antiguo recibe los nuevos
# (siempre solo se AGREGA, nunca se quita). Hoy no hay permisos separados.
# --------------------------------------------------------------------------
LEGACY_MAP = {}


# --------------------------------------------------------------------------
# Matriz de la pantalla de roles: módulo x columna
# --------------------------------------------------------------------------
MATRIX_COLUMNS = (
    ('view', 'Ver'), ('add', 'Crear'), ('change', 'Editar'), ('delete', 'Eliminar'),
)


# Pantallas cuyo acceso NO entra en el rol "Solo lectura": guardan datos sensibles
# (credenciales de Factus y de las aseguradoras, comisiones y datos de pago de los asesores) o son de administración (usuarios, roles, accesos).
READONLY_EXCLUDE = frozenset({
    'company', 'factus_credentials', 'dashboard_config', 'insurers', 'advisors',
    'users', 'roles', 'user_access',
})
READONLY_ROLE_NAME = 'Solo lectura'


def readonly_permissions():
    """Permisos del rol "Solo lectura": solo entrar a ver los módulos, ninguna acción."""
    return sorted(
        i.view_perm for i in iter_items()
        if i.view_perm and i.perms and i.key not in READONLY_EXCLUDE
    )


def permission_labels():
    """{'app.codename': descripción} de todo el catálogo."""
    return {f"{k.split('.')[0]}.{c}": label for k, perms in PERMISSIONS.items() for c, label in perms}


def columns_for(item):
    """Reparte los permisos de un módulo en columnas Ver/Crear/Editar/Eliminar/Otras.

    El permiso ``view_perm`` va en "Ver" (da acceso a la pantalla); ``add_x``, ``change_x`` y
    ``delete_x`` van a su columna cuando ``x`` es el mismo sufijo que el de ver; el resto
    cae en "Otras acciones".
    Devuelve ``{'view': 'app.cod'|None, 'add': ..., 'change': ..., 'delete': ..., 'others': [(full, label)]}``.
    """
    labels = permission_labels()
    cols = {key: None for key, _ in MATRIX_COLUMNS}
    others = []
    suffix = item.view_perm.split('.', 1)[1].split('_', 1)[1] if item.view_perm else None
    for full in item.perms:
        codename = full.split('.', 1)[1]
        verb, _, rest = codename.partition('_')
        if full == item.view_perm:
            cols['view'] = full
        elif verb in ('add', 'change', 'delete') and rest == suffix and cols[verb] is None:
            cols[verb] = full
        else:
            others.append((full, labels[full]))
    cols['others'] = others
    return cols


def matrix_sections():
    """Módulos agrupados por sección del menú, listos para pintar la matriz."""
    sections = []

    def rows_for(items):
        return [
            {'key': i.key, 'label': i.label, 'readonly_ok': i.key not in READONLY_EXCLUDE,
             'cols': cols, 'cols_list': [(k, cols[k]) for k, _ in MATRIX_COLUMNS]}
            for i in items if i.perms
            for cols in (columns_for(i),)
        ]

    def collect(nodes, label):
        rows = rows_for(n for n in nodes if not isinstance(n, Section))
        if rows:
            sections.append({'label': label, 'rows': rows})
        for node in nodes:
            if isinstance(node, Section):
                collect(node.children, f'{label} › {node.label}')

    # Los ítems sueltos del primer nivel se agrupan en una sola sección "General".
    collect(tuple(n for n in MENU if not isinstance(n, Section)), 'General')
    for node in MENU:
        if isinstance(node, Section):
            collect(node.children, node.label)
    return sections


def validate():
    """Verifica la coherencia interna del catálogo. Devuelve lista de errores."""
    errors = []
    declared = {}
    for model_key, perms in PERMISSIONS.items():
        app = model_key.split('.')[0]
        for codename, label in perms:
            full = f'{app}.{codename}'
            if full in declared:
                errors.append(f'Permiso duplicado: {full}')
            declared[full] = label
            if not label.strip():
                errors.append(f'Permiso sin descripción: {full}')

    used = {}
    keys = set()
    for item in iter_items():
        if item.key in keys:
            errors.append(f'Módulo duplicado: {item.key}')
        keys.add(item.key)
        if item.view_perm is not None and item.view_perm not in declared:
            errors.append(f'{item.key}: view_perm {item.view_perm} no está en el catálogo')
        if item.perms and item.view_perm is not None and item.view_perm not in item.perms:
            errors.append(f'{item.key}: view_perm {item.view_perm} no está en sus perms')
        for p in item.perms:
            if p not in declared:
                errors.append(f'{item.key}: permiso inexistente {p}')
            if p in used:
                errors.append(f'{p} aparece en dos módulos: {used[p]} y {item.key}')
            used[p] = item.key

    visible_only = {i.view_perm for i in iter_items() if i.view_perm and not i.perms}
    for p in declared:
        if p not in used and p not in visible_only:
            errors.append(f'Permiso sin módulo asignado: {p}')

    for old, new in LEGACY_MAP.items():
        for p in new:
            if p not in declared:
                errors.append(f'LEGACY_MAP apunta a un permiso inexistente: {p}')
    return errors
