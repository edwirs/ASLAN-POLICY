"""Panel de la plataforma (solo ASLAN): empresas, sus dominios, su plan de Aslani y el consumo.

Vive en el schema «public» (el de las tablas compartidas), que no tiene usuarios ni sesiones: por eso el acceso es propio y
simple, pensado para UN dueño: usuario + clave cifrada en `.env.secrets` y una cookie firmada con vencimiento. Las plantillas
se dibujan SIN `request` a propósito: así no corren los procesadores de contexto de las empresas (que consultan tablas que
en «public» no existen).
"""
import hashlib
import hmac
import ipaddress
import logging
import re
from datetime import date

from django.conf import settings
from django.contrib.auth.hashers import check_password
from django.core import signing
from django.core.cache import cache
from django.db import connection
from django.db.models import Count, Sum
from django.http import Http404, HttpResponse, HttpResponseRedirect
from django.middleware.csrf import get_token
from django.template.loader import get_template
from django.urls import reverse
from django.views.decorators.http import require_POST
from django_tenants.utils import get_public_schema_name, get_tenant_model, schema_context

from core.tenants import totp
from core.tenants.models import AccesoPlataforma, Auditoria, Domain

logger = logging.getLogger(__name__)

COOKIE = 'aslan-plataforma'
SAL = 'plataforma-acceso'
VIGENCIA = 8 * 3600        # la sesión del panel dura 8 horas
MAX_INTENTOS = 5           # intentos de ingreso fallidos por dirección IP
BLOQUEO = 15 * 60          # …y cuánto dura el bloqueo
RE_DOMINIO = re.compile(r'^(?=.{4,253}$)([a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?\.)+[a-z]{2,63}$|^[a-z0-9-]+\.localhost$')


# ---------------------------------------------------------------------------------------------------------------------
# Acceso
# ---------------------------------------------------------------------------------------------------------------------
def acceso_guardado():
    """El acceso que se cambió desde el panel (clave propia, 2FA, IPs). None = rige lo de .env.secrets."""
    return AccesoPlataforma.objects.order_by('id').first()


def credenciales():
    """(usuario, clave_hash) vigentes: los del panel si ya se cambiaron, si no los de .env.secrets."""
    guardado = acceso_guardado()
    if guardado:
        return guardado.usuario, guardado.clave_hash
    return settings.PLATAFORMA_USUARIO, settings.PLATAFORMA_CLAVE_HASH


def _configurada():
    return all(credenciales())


def version_clave(clave_hash):
    """Huella de la clave: va dentro de la cookie, así que cambiar la clave cierra todas las sesiones abiertas."""
    return hashlib.sha256(clave_hash.encode()).hexdigest()[:12]


def ips_permitidas():
    guardado = acceso_guardado()
    return [i.strip() for i in (guardado.ips_permitidas if guardado else '').split(',') if i.strip()]


def ip_permitida(request):
    lista = ips_permitidas()
    if not lista:
        return True
    try:
        direccion = ipaddress.ip_address(_ip(request))
        return any(direccion in ipaddress.ip_network(r, strict=False) for r in lista)
    except ValueError:
        return False


def _sesion_cookie(respuesta, usuario):
    _, clave_hash = credenciales()
    respuesta.set_cookie(COOKIE, signing.dumps({'u': usuario, 'v': version_clave(clave_hash)}, salt=SAL), max_age=VIGENCIA,
                         httponly=True, samesite='Lax', secure=not settings.DEBUG)
    return respuesta


def _autenticado(request):
    if not _configurada() or not ip_permitida(request):
        return False
    try:
        datos = signing.loads(request.COOKIES.get(COOKIE, ''), salt=SAL, max_age=VIGENCIA)
    except signing.BadSignature:
        return False
    usuario, clave_hash = credenciales()
    return hmac.compare_digest(str(datos.get('u', '')), usuario) and hmac.compare_digest(str(datos.get('v', '')), version_clave(clave_hash))


def requiere_acceso(vista):
    def envoltura(request, *args, **kwargs):
        if not _autenticado(request):
            return HttpResponseRedirect(reverse('plataforma_ingresar'))
        return vista(request, *args, **kwargs)
    envoltura.__name__ = vista.__name__
    return envoltura


def _responder(request, plantilla, contexto=None, status=200):
    contexto = {**(contexto or {}), 'csrf_token': get_token(request), 'autenticado': _autenticado(request)}
    return HttpResponse(get_template(plantilla).render(contexto), status=status)


def _ip(request):
    """IP de quien llama. Detrás de un proxy de confianza (nginx) hay que activar PLATAFORMA_CONFIAR_PROXY: se toma la última del
    X-Forwarded-For, que es la que vio el proxy (las anteriores las puede inventar quien llama)."""
    if settings.PLATAFORMA_CONFIAR_PROXY and request.META.get('HTTP_X_FORWARDED_FOR'):
        return request.META['HTTP_X_FORWARDED_FOR'].split(',')[-1].strip()
    return request.META.get('REMOTE_ADDR', '?')


def auditar(request, accion, schema='', detalle=''):
    """Deja constancia (quién desde qué IP, qué y sobre qué empresa) de TODA acción que cambia algo desde el panel."""
    Auditoria.objects.create(accion=accion[:60], schema=schema[:63], detalle=str(detalle)[:300], ip=_ip(request)[:45])
    logger.info('Plataforma [%s] %s %s %s', _ip(request), accion, schema, detalle)


def inicio(request):
    return HttpResponseRedirect(reverse('plataforma_empresas' if _autenticado(request) else 'plataforma_ingresar'))


def _bloqueado(request):
    return cache.get(f'plataforma:intentos:{_ip(request)}', 0) >= MAX_INTENTOS


def _fallo(request, usuario, motivo):
    clave = f'plataforma:intentos:{_ip(request)}'
    cache.set(clave, cache.get(clave, 0) + 1, BLOQUEO)
    auditar(request, 'ingreso_fallido', detalle=f'{usuario[:60]} · {motivo}')


def _entrar(request, usuario):
    cache.delete(f'plataforma:intentos:{_ip(request)}')
    auditar(request, 'ingreso', detalle=usuario)
    return _sesion_cookie(HttpResponseRedirect(reverse('plataforma_empresas')), usuario)


def ingresar(request):
    if not _configurada():
        return _responder(request, 'plataforma/login.html', {'sin_configurar': True})
    if not ip_permitida(request):
        auditar(request, 'ingreso_ip_no_permitida')
        return _responder(request, 'plataforma/login.html', {'error': 'Este panel no está disponible desde tu dirección.'}, status=403)
    if request.method != 'POST':
        return _responder(request, 'plataforma/login.html')
    if _bloqueado(request):
        return _responder(request, 'plataforma/login.html', {'error': 'Demasiados intentos. Espera unos minutos e intenta de nuevo.'}, status=429)
    usuario_ok, hash_ok = credenciales()
    guardado = acceso_guardado()
    # Segundo paso: el código de 6 dígitos (el primer paso ya se comprobó y viene firmado, válido 5 minutos).
    if request.POST.get('previo'):
        try:
            previo = signing.loads(request.POST['previo'], salt=SAL + '-previo', max_age=300)
        except signing.BadSignature:
            return _responder(request, 'plataforma/login.html', {'error': 'Pasaron más de 5 minutos. Ingresa de nuevo.'}, status=401)
        paso = totp.verificar(guardado.totp_secreto, request.POST.get('codigo', '')) if guardado and guardado.totp_activo else None
        if paso is None or not cache.add(f'plataforma:totp:{paso}', 1, 120):  # un código no se puede usar dos veces
            _fallo(request, previo['u'], 'código de verificación')
            return _responder(request, 'plataforma/login.html', {'paso2': True, 'previo': request.POST['previo'], 'error': 'Código incorrecto o ya usado.'}, status=401)
        return _entrar(request, previo['u'])
    usuario, clave = request.POST.get('usuario', '').strip(), request.POST.get('clave', '')
    ok_usuario = hmac.compare_digest(usuario, usuario_ok)
    ok_clave = check_password(clave, hash_ok)  # siempre se verifica, para no revelar si el usuario existe
    if not (ok_usuario and ok_clave):
        _fallo(request, usuario, 'usuario o clave')
        return _responder(request, 'plataforma/login.html', {'error': 'Usuario o clave incorrectos.'}, status=401)
    if guardado and guardado.totp_activo:
        return _responder(request, 'plataforma/login.html', {'paso2': True, 'previo': signing.dumps({'u': usuario}, salt=SAL + '-previo')})
    return _entrar(request, usuario)


def salir(request):
    respuesta = HttpResponseRedirect(reverse('plataforma_ingresar'))
    respuesta.delete_cookie(COOKIE)
    return respuesta


# ---------------------------------------------------------------------------------------------------------------------
# Empresas
# ---------------------------------------------------------------------------------------------------------------------
def _pesos(valor):
    return '$' + f'{int(round(valor)):,}'.replace(',', '.')


def _dato_empresa(e):
    """Una empresa con su plan de Aslani y lo que ha consumido este mes (se entra a su schema para contar)."""
    from core.policies.services import asistente  # import local: evita ciclos al cargar las URLs

    from core.tenants import estado

    d = {'e': e, 'estado': estado.estado_suscripcion(e), 'dominios': list(Domain.objects.filter(tenant=e).order_by('-is_primary', 'domain')), 'cupo': None, 'usuarios': None, 'solicitudes': None}
    try:
        with schema_context(e.schema_name):
            from core.policies.models import Vehiculo
            from core.user.models import User
            d['cupo'] = asistente.cupo(None)
            d['usuarios'] = User.objects.filter(is_active=True).count()
            d['solicitudes'] = Vehiculo.objects.count()
    except Exception:
        logger.exception('No se pudo leer la empresa "%s"', e.schema_name)
    try:
        d['consumo'] = consumo_mes(e.schema_name)
    except Exception:
        logger.exception('No se pudo leer el consumo real de "%s"', e.schema_name)
        d['consumo'] = None
    if d['consumo']:
        d['costo_real'] = _pesos(d['consumo']['cop'])
        d['margen'] = margen(e.aslani_precio_cop, d['consumo']['cop'])
        if d['margen']:
            d['margen_neto'] = _pesos(d['margen']['neto'] - d['margen']['comision'])
            d['margen_ganancia'] = ('-' if d['margen']['ganancia'] < 0 else '') + _pesos(abs(d['margen']['ganancia']))
    if d['cupo']:
        d['costo_estimado'] = _pesos(d['cupo']['usadas'] * settings.ASISTENTE_COSTO_PREGUNTA_COP)
        d['porcentaje'] = round(d['cupo']['usadas'] * 100 / d['cupo']['limite']) if d['cupo']['limite'] else 0
    return d


def consumo_mes(schema):
    """Lo que Anthropic cobró de verdad a esta empresa en el mes en curso (de los tokens registrados), con el margen del plan.
    None si no hay registros todavía (entonces el panel muestra solo el estimado)."""
    from core.policies.models import AsistenteConsumo
    from core.policies.services import asistente

    inicio, siguiente = None, None
    with schema_context(schema):
        inicio, siguiente = asistente._mes()
        filas = AsistenteConsumo.objects.filter(created_at__date__gte=inicio, created_at__date__lt=siguiente)
        t = filas.aggregate(n=Count('id'), usd=Sum('costo_usd'), entrada=Sum('tokens_entrada'), salida=Sum('tokens_salida'),
                            leer=Sum('tokens_cache_lectura'), escribir=Sum('tokens_cache_escritura'), llamadas=Sum('llamadas'))
    if not t['n']:
        return None
    usd = float(t['usd'] or 0)
    return {'preguntas': t['n'], 'llamadas': t['llamadas'] or 0, 'usd': usd, 'cop': usd * settings.ASISTENTE_TRM_COP,
            'entrada': t['entrada'] or 0, 'salida': t['salida'] or 0, 'cache': (t['leer'] or 0) + (t['escribir'] or 0),
            'promedio_cop': usd * settings.ASISTENTE_TRM_COP / t['n']}


def margen(precio_cop, costo_cop):
    """Lo que le queda a ASLAN de un plan: precio sin IVA − comisión de la pasarela (sobre lo que paga el cliente) − costo de Anthropic."""
    if not precio_cop:
        return None
    neto = precio_cop / (1 + settings.IVA)
    comision = precio_cop * settings.PASARELA_COMISION
    return {'neto': neto, 'comision': comision, 'ganancia': neto - comision - costo_cop}


def _empresa_o_404(schema):
    e = get_tenant_model().objects.filter(schema_name=schema).exclude(schema_name=get_public_schema_name()).first()
    if e is None:
        raise Http404
    return e


@requiere_acceso
def empresas(request):
    datos = [_dato_empresa(e) for e in get_tenant_model().objects.exclude(schema_name=get_public_schema_name()).order_by('name')]
    from core.tenants.gestion import ingresos_del_mes

    usadas = sum(d['cupo']['usadas'] for d in datos if d['cupo'])
    # Costo del mes: el real (tokens) donde ya hay registro; para las preguntas sin registro, el estimado.
    costo = sum(d['consumo']['cop'] + max(d['cupo']['usadas'] - d['consumo']['preguntas'], 0) * settings.ASISTENTE_COSTO_PREGUNTA_COP if d['consumo']
                else d['cupo']['usadas'] * settings.ASISTENTE_COSTO_PREGUNTA_COP for d in datos if d['cupo'])
    resumen = {'empresas': len(datos), 'activas_ia': sum(1 for d in datos if d['e'].aslani_ia_activa),
               'usadas': usadas, 'costo': _pesos(costo), 'ingresos': _pesos(ingresos_del_mes()),
               'costo_cop_pregunta': settings.ASISTENTE_COSTO_PREGUNTA_COP}
    return _responder(request, 'plataforma/empresas.html', {'seccion': 'empresas', 'empresas': datos, 'resumen': resumen, 'aviso': request.GET.get('ok')})


@requiere_acceso
def empresa(request, schema):
    e = _empresa_o_404(schema)
    d = _dato_empresa(e)
    meses = []
    try:
        with schema_context(e.schema_name):
            from core.policies.models import AsistenteUso
            from core.policies.services.asistente import MESES_ES
            por_mes = {}
            for fecha, n in AsistenteUso.objects.values_list('fecha', 'preguntas'):
                por_mes[(fecha.year, fecha.month)] = por_mes.get((fecha.year, fecha.month), 0) + n
            meses = [{'mes': f'{MESES_ES[m - 1].capitalize()} {a}', 'preguntas': n, 'costo': _pesos(n * settings.ASISTENTE_COSTO_PREGUNTA_COP)}
                     for (a, m), n in sorted(por_mes.items(), reverse=True)[:6]]
    except Exception:
        logger.exception('No se pudo leer el consumo de "%s"', schema)
    from core.tenants import estado

    pagos = list(e.pagos.all()[:30])
    for pago in pagos:
        pago.valor = _pesos(pago.monto_cop)
    return _responder(request, 'plataforma/empresa.html', {
        'seccion': 'empresas', 'd': d, 'e': e, 'estado': d['estado'], 'pagos': pagos, 'hoy': estado.hoy(), 'gracia': settings.GRACIA_DIAS,
        'total_pagado': _pesos(sum(p.monto_cop for p in e.pagos.all())) if pagos else '', 'meses': meses, 'aviso': request.GET.get('ok'), 'error': request.GET.get('error'),
        'costo_cop_pregunta': settings.ASISTENTE_COSTO_PREGUNTA_COP})


def _volver(schema, ok=None, error=None):
    url = reverse('plataforma_empresa', args=[schema])
    return HttpResponseRedirect(f'{url}?ok={ok}' if ok else f'{url}?error={error}')


@requiere_acceso
@require_POST
def guardar_plan(request, schema):
    e = _empresa_o_404(schema)
    try:
        preguntas = int(request.POST.get('preguntas', ''))
        if not 0 <= preguntas <= 1_000_000:
            raise ValueError
    except ValueError:
        return _volver(schema, error='Las preguntas por mes deben ser un número entre 0 y 1.000.000.')
    try:
        precio = int(request.POST.get('precio', '0').replace('.', '').strip() or 0)
        hasta = date.fromisoformat(request.POST['hasta']) if request.POST.get('hasta') else None
        if not 0 <= precio <= 100_000_000:
            raise ValueError
    except ValueError:
        return _volver(schema, error='El precio o la fecha de «Aslani IA pagada hasta» no son válidos.')
    e.aslani_ia_activa = request.POST.get('ia') == 'on'
    e.aslani_preguntas_mes = preguntas
    e.aslani_precio_cop = precio
    e.aslani_hasta = hasta
    e.save(update_fields=['aslani_ia_activa', 'aslani_preguntas_mes', 'aslani_precio_cop', 'aslani_hasta'])
    auditar(request, 'plan_aslani', schema, f'IA {"sí" if e.aslani_ia_activa else "no"}, {preguntas} preguntas/mes, ${precio}, hasta {hasta or "—"}')
    return _volver(schema, ok='Plan de Aslani guardado.')


@requiere_acceso
@require_POST
def guardar_facturacion(request, schema):
    e = _empresa_o_404(schema)
    hasta = request.POST.get('pagado_hasta', '').strip()
    try:
        e.paid_until = date.fromisoformat(hasta) if hasta else None
    except ValueError:
        return _volver(schema, error='La fecha de «pagado hasta» no es válida.')
    e.on_trial = request.POST.get('en_prueba') == 'on'
    e.nota = request.POST.get('nota', '').strip()[:2000]
    plan = request.POST.get('plan', '')
    e.plan = plan if plan in get_tenant_model().MESES_PLAN else ''
    e.save(update_fields=['paid_until', 'on_trial', 'nota', 'plan'])
    auditar(request, 'facturacion', schema, f'plan {e.plan or "—"}, pagado hasta {e.paid_until or "—"}, prueba {"sí" if e.on_trial else "no"}')
    return _volver(schema, ok='Datos de facturación guardados.')


@requiere_acceso
@require_POST
def agregar_dominio(request, schema):
    e = _empresa_o_404(schema)
    dominio = request.POST.get('dominio', '').strip().lower()
    if not RE_DOMINIO.match(dominio):
        return _volver(schema, error='Escribe solo el dominio, sin https:// ni rutas (ej. empresa.aslantecnologia.online).')
    if Domain.objects.filter(domain=dominio).exists():
        return _volver(schema, error=f'El dominio {dominio} ya está registrado.')
    Domain.objects.create(domain=dominio, tenant=e, is_primary=False)
    auditar(request, 'dominio_agregado', schema, dominio)
    return _volver(schema, ok=f'Dominio {dominio} agregado. Recuerda apuntarlo en el DNS hacia el servidor.')


@requiere_acceso
@require_POST
def quitar_dominio(request, schema, pk):
    e = _empresa_o_404(schema)
    dominio = Domain.objects.filter(pk=pk, tenant=e).first()
    if dominio is None:
        raise Http404
    if dominio.is_primary:
        return _volver(schema, error='No se puede quitar el dominio principal de la empresa.')
    dominio.delete()
    auditar(request, 'dominio_quitado', schema, dominio.domain)
    return _volver(schema, ok=f'Dominio {dominio.domain} quitado.')
