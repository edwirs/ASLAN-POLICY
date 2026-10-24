"""Crear una empresa nueva desde el panel de la plataforma: esquema propio, roles, usuario administrador y datos básicos.

Corre en un hilo aparte (crear el esquema aplica todas las migraciones y tarda un par de minutos) y deja su avance en un archivo
temporal que la página consulta cada par de segundos. El archivo es un archivo (y no la memoria) para que funcione aunque el
servidor tenga varios procesos. La clave inicial del administrador se muestra UNA sola vez y se borra al leerla.
"""
import json
import logging
import os
import re
import secrets
import tempfile
import threading
from datetime import timedelta

import environ
from django.conf import settings
from django.core.management import call_command
from django.db import connection, transaction
from django_tenants.utils import get_public_schema_name, get_tenant_model, schema_context

from core.tenants import estado, respaldos
from core.tenants.models import Domain

logger = logging.getLogger(__name__)
env = environ.Env()

RE_SCHEMA = re.compile(r'^[a-z][a-z0-9_]{2,30}$')
RESERVADOS = {'public', 'admin', 'www', 'api', 'mail', 'test', 'default', 'postgres', 'template0', 'template1', 'static', 'media', 'aslan', 'plataforma'}
PASOS = (
    ('respaldo', 'Respaldo de seguridad de toda la base'),
    ('esquema', 'Creando la empresa y su base de datos (aplica todas las migraciones; tarda un par de minutos)'),
    ('datos', 'Cargando roles, permisos, aseguradoras y datos básicos'),
    ('admin', 'Creando el usuario administrador'),
)
ASEGURADORAS_CON_BOT = ('AXA Colpatria', 'HDI', 'La Equidad Seguros', 'Mapfre', 'Qualitas', 'Seguros Mundial', 'Seguros del Estado')
TIPOS_DOCUMENTO = (
    ('Registro civil de nacimiento', 'RC', '11'), ('Tarjeta de identidad', 'TI', '12'), ('Cédula de ciudadanía', 'CC', '13'),
    ('Cédula de extranjería', 'CE', '22'), ('NIT', 'NIT', '31'), ('Pasaporte', 'PA', '41'),
    ('Documento de identificación extranjero', 'DIE', '42'), ('Permiso Especial de Permanencia', 'PEP', '47'),
    ('Permiso por Protección Temporal', 'PPT', '48'), ('Salvo conducto', 'SC', '50'),
)


def sugerir_schema(nombre):
    """«Gali Seguros S.A.S.» → «gali_seguros»: minúsculas, sin tildes ni signos, máximo 30 caracteres."""
    import unicodedata

    base = unicodedata.normalize('NFKD', nombre).encode('ascii', 'ignore').decode().lower()
    base = re.sub(r'\b(s\.?a\.?s?|ltda|s\.?a|e\.?u)\b\.?', ' ', base)
    base = re.sub(r'[^a-z0-9]+', '_', base).strip('_')[:30]
    return base if base[:1].isalpha() else ('e_' + base)[:30]


def validar(datos):
    """{campo: mensaje} con lo que está mal (vacío = todo bien)."""
    errores = {}
    Empresa = get_tenant_model()
    if len(datos['nombre']) < 3:
        errores['nombre'] = 'Escribe la razón social.'
    if not RE_SCHEMA.match(datos['schema']) or datos['schema'] in RESERVADOS or datos['schema'].startswith('pg_'):
        errores['schema'] = 'Solo minúsculas, números y guion bajo; empieza con letra; entre 3 y 31 caracteres; no puede ser un nombre reservado.'
    elif (Empresa.objects.filter(schema_name=datos['schema']).exists() or _esquema_existe(datos['schema'])
          or Domain.objects.filter(domain__startswith=datos['schema'].replace('_', '-') + '.').exists()):
        errores['schema'] = 'Ya existe una empresa o un esquema con ese nombre.'
    if not re.fullmatch(r'[0-9A-Za-z.\-]{5,20}', datos['nit']):
        errores['nit'] = 'NIT no válido (5 a 20 caracteres, solo números, letras, punto y guion).'
    elif Empresa.objects.filter(nit=datos['nit']).exists():
        errores['nit'] = 'Ya hay una empresa con ese NIT.'
    if not re.fullmatch(r'[a-zA-Z0-9_.@+-]{3,40}', datos['usuario']):
        errores['usuario'] = 'Usuario del administrador: 3 a 40 caracteres, sin espacios.'
    if datos['clave'] and len(datos['clave']) < 10:
        errores['clave'] = 'La clave inicial debe tener al menos 10 caracteres (o déjala vacía para generar una).'
    if not re.fullmatch(r'[^@\s]+@[^@\s]+\.[^@\s]+', datos['email']):
        errores['email'] = 'Correo no válido: es donde la empresa recibe avisos.'
    return errores


def _esquema_existe(nombre):
    with connection.cursor() as c:
        c.execute('SELECT 1 FROM information_schema.schemata WHERE schema_name = %s', [nombre])
        return c.fetchone() is not None


# ---------------------------------------------------------------------------------------------------------------------
# Avance (archivo temporal)
# ---------------------------------------------------------------------------------------------------------------------
def _archivo(schema):
    return os.path.join(tempfile.gettempdir(), f'aslan_crear_{schema}.json')


def _guardar(schema, **cambios):
    actual = leer(schema, consumir=False) or {'pasos': [{'clave': k, 'texto': t, 'estado': 'espera'} for k, t in PASOS], 'estado': 'corriendo', 'mensaje': ''}
    actual.update(cambios)
    ruta = _archivo(schema)
    with open(os.open(ruta, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600), 'w') as f:
        json.dump(actual, f)


def leer(schema, consumir=True):
    """Avance de la creación, o None. Si ya terminó, entrega la clave inicial UNA vez (y la borra del archivo)."""
    if not RE_SCHEMA.match(schema):
        return None
    try:
        with open(_archivo(schema)) as f:
            datos = json.load(f)
    except (OSError, ValueError):
        return None
    if consumir and datos.get('clave_inicial'):
        resto = {k: v for k, v in datos.items() if k != 'clave_inicial'}
        with open(os.open(_archivo(schema), os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600), 'w') as f:
            json.dump(resto, f)
    return datos


def _marcar(schema, clave, estado_paso):
    datos = leer(schema, consumir=False)
    for p in datos['pasos']:
        if p['clave'] == clave:
            p['estado'] = estado_paso
    _guardar(schema, pasos=datos['pasos'])


# ---------------------------------------------------------------------------------------------------------------------
# Creación
# ---------------------------------------------------------------------------------------------------------------------
def iniciar(datos):
    """Arranca la creación en un hilo y devuelve de inmediato. `datos` ya pasó por `validar`."""
    _guardar(datos['schema'], estado='corriendo', mensaje='', pasos=[{'clave': k, 'texto': t, 'estado': 'espera'} for k, t in PASOS])
    hilo = threading.Thread(target=_trabajo, args=(datos,), name=f'crear-{datos["schema"]}', daemon=True)
    hilo.start()
    return hilo


def _trabajo(datos):
    schema = datos['schema']
    try:
        crear_empresa(datos)
    except Exception as exc:
        logger.exception('No se pudo crear la empresa "%s"', schema)
        _guardar(schema, estado='error', mensaje=str(exc)[:300] or exc.__class__.__name__)
    finally:
        connection.close()


def crear_empresa(datos):
    """Hace todo el trabajo (síncrono). Lanza una excepción si algo falla; ver `iniciar` para correrlo en segundo plano."""
    schema = datos['schema']
    clave = datos['clave'] or secrets.token_urlsafe(9)
    Empresa = get_tenant_model()

    _marcar(schema, 'respaldo', 'haciendo')
    respaldos.crear()
    _marcar(schema, 'respaldo', 'listo')

    _marcar(schema, 'esquema', 'haciendo')
    hoy = estado.hoy()
    empresa = Empresa(
        schema_name=schema, name=datos['nombre'], nit=datos['nit'], email=datos['email'], phone=datos['telefono'] or None,
        plan=datos.get('plan', ''), on_trial=True, paid_until=hoy + timedelta(days=datos['dias_prueba']), nota=datos['nota'],
        modulo_cotizador=datos['cotizador'], modulo_asesores=datos['asesores'], modulo_cartera=datos['cartera'],
        aslani_ia_activa=datos['aslani'], aslani_preguntas_mes=datos['preguntas'])
    # Aquí SÍ se crea el esquema (es nuevo). Si algo falla en esta línea, django-tenants borra el esquema a medio hacer: lo que se quiere.
    empresa.save()
    if settings.DEBUG:
        Domain.objects.get_or_create(domain=f'{schema.replace("_", "-")}.localhost', defaults={'tenant': empresa, 'is_primary': False})
    _marcar(schema, 'esquema', 'listo')

    try:
        _marcar(schema, 'datos', 'haciendo')
        _sembrar(schema, datos)
        _marcar(schema, 'datos', 'listo')
        _marcar(schema, 'admin', 'haciendo')
        _crear_admin(schema, datos, clave)
        _marcar(schema, 'admin', 'listo')
    except Exception:
        # La empresa quedó creada pero incompleta: se deja el rastro y se avisa. NO se borra nada (puede ser reparable a mano).
        logger.exception('Empresa "%s" creada pero la carga inicial falló', schema)
        raise
    dominios = list(Domain.objects.filter(tenant=empresa).order_by('-is_primary', 'domain').values_list('domain', flat=True))
    _guardar(schema, estado='listo', mensaje='', clave_inicial=clave, usuario=datos['usuario'], dominios=dominios)
    return empresa


def _sembrar(schema, datos):
    from core.policies.models import Aseguradora, TipoPoliza
    from core.pos.models import Company, DocumentType
    from core.security.models import Dashboard

    call_command('sync_permissions', schema=schema, create_admin_role=True, create_readonly_role=True, verbosity=0)
    with schema_context(schema), transaction.atomic():
        Dashboard.objects.get_or_create(name='ASLAN MultiAgente de Seguros', defaults={'icon': 'fas fa-user-tie', 'author': 'ASLAN Tecnología'})
        for nombre, abreviatura, codigo in TIPOS_DOCUMENTO:
            DocumentType.objects.get_or_create(code=codigo, defaults={'name': nombre, 'abbreviation': abreviatura})
        for nombre in ASEGURADORAS_CON_BOT:
            Aseguradora.objects.get_or_create(name=nombre)
        TipoPoliza.objects.get_or_create(code='todo-riesgo', defaults={'name': 'Todo Riesgo'})
        Company.objects.get_or_create(ruc=datos['nit'][:13], defaults={
            'name': datos['nombre'][:50], 'address': '', 'mobile': (datos['telefono'] or '')[:10], 'phone': '', 'email': datos['email'][:50],
            'website': '', 'iva': 0})
    call_command('cargar_coberturas', schema=schema, verbosity=0)  # fichas del comparativo + Bolívar, Allianz y Sura (sin bot)
    with schema_context(schema):
        from core.pos.models import Municipio

        if not Municipio.objects.exists():
            call_command('importar_municipios', verbosity=0)


def _crear_admin(schema, datos, clave):
    from django.contrib.auth.models import Group

    from core.user.models import User

    with schema_context(schema), transaction.atomic():
        usuario = User(username=datos['usuario'], names=datos['nombre_admin'] or datos['usuario'], email=datos['email'], is_active=True,
                       is_staff=True, is_superuser=True)
        usuario.set_password(clave)
        usuario.save()
        usuario.groups.add(Group.objects.get(name='Administrador'))
