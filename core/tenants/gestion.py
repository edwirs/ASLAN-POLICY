"""Panel de la plataforma, parte 2: respaldos, pagos, módulos contratados, anuncios, auditoría, salud y herramientas de soporte.

Usa los mismos ayudantes que `plataforma.py` (acceso, plantillas sin `request`, auditoría). Todo cambio queda en `Auditoria`.
"""
import calendar
import logging
import os
import secrets
import shutil
import time
from datetime import date, timedelta
from urllib.parse import urlencode

from django.conf import settings
from django.core import signing
from django.core.cache import cache
from django.db import connection
from django.db.models import Count, Sum
from django.http import FileResponse, Http404, HttpResponseRedirect, JsonResponse
from django.urls import reverse
from django.views.decorators.http import require_POST
from django_tenants.utils import get_public_schema_name, get_tenant_model, schema_context

from core.tenants import creacion, estado, respaldos
from core.tenants.models import Anuncio, Auditoria, Client, Domain, Pago
from core.tenants.plataforma import (_empresa_o_404, _pesos, _responder, _volver, auditar, requiere_acceso)

logger = logging.getLogger(__name__)

SAL_SOPORTE = 'acceso-soporte'


def _redirigir(nombre, ok=None, error=None, args=()):
    url = reverse(nombre, args=args)
    return HttpResponseRedirect(f'{url}?' + urlencode({'ok': ok} if ok else {'error': error}))


def _empresas():
    return get_tenant_model().objects.exclude(schema_name=get_public_schema_name()).order_by('name')


# ---------------------------------------------------------------------------------------------------------------------
# Respaldos
# ---------------------------------------------------------------------------------------------------------------------
@requiere_acceso
def respaldos_pagina(request):
    lista = respaldos.listar()
    for r in lista:
        r['tamano'] = respaldos.formato_tamano(r['bytes'])
        r['restaurar'] = respaldos.comando_restaurar(r['nombre'])
    cron = f'0 2 * * * cd "{settings.BASE_DIR}" && venv/bin/python manage.py respaldo_crear >> respaldos/cron.log 2>&1'
    return _responder(request, 'plataforma/respaldos.html', {
        'seccion': 'respaldos', 'lista': lista, 'estado': respaldos.estado(), 'empresas': _empresas(), 'cron': cron,
        'carpeta': respaldos.directorio(), 'retencion': settings.RESPALDOS_RETENCION_DIAS,
        'total': respaldos.formato_tamano(sum(i['bytes'] for i in lista)),
        'aviso': request.GET.get('ok'), 'error': request.GET.get('error')})


@requiere_acceso
@require_POST
def respaldos_crear(request):
    schema = request.POST.get('schema', '').strip() or None
    if schema and not _empresas().filter(schema_name=schema).exists():
        return _redirigir('plataforma_respaldos', error='Esa empresa no existe.')
    try:
        info = respaldos.crear(schema)
    except respaldos.RespaldoError as exc:
        auditar(request, 'respaldo_fallido', schema or '', str(exc))
        return _redirigir('plataforma_respaldos', error=str(exc))
    auditar(request, 'respaldo_creado', schema or '', info['nombre'])
    return _redirigir('plataforma_respaldos', ok=f'Respaldo creado: {info["nombre"]} ({respaldos.formato_tamano(info["bytes"])}).')


@requiere_acceso
def respaldos_descargar(request, nombre):
    ruta = respaldos.ruta_segura(nombre)
    if not ruta:
        raise Http404
    auditar(request, 'respaldo_descargado', detalle=nombre)
    return FileResponse(open(ruta, 'rb'), as_attachment=True, filename=nombre)


@requiere_acceso
@require_POST
def respaldos_verificar(request, nombre):
    ok, detalle = respaldos.verificar(nombre)
    if ok:
        return _redirigir('plataforma_respaldos', ok=f'{nombre} está sano ({detalle}).')
    return _redirigir('plataforma_respaldos', error=f'{nombre} NO se pudo leer: {detalle}')


@requiere_acceso
@require_POST
def respaldos_eliminar(request, nombre):
    try:
        respaldos.eliminar(nombre)
    except respaldos.RespaldoError as exc:
        return _redirigir('plataforma_respaldos', error=str(exc))
    auditar(request, 'respaldo_eliminado', detalle=nombre)
    return _redirigir('plataforma_respaldos', ok=f'{nombre} eliminado.')


# ---------------------------------------------------------------------------------------------------------------------
# Pagos y vencimientos
# ---------------------------------------------------------------------------------------------------------------------
def sumar_meses(desde, meses):
    """`desde` + N meses sin salirse del calendario (31 de enero + 1 mes = 28/29 de febrero)."""
    m = desde.month - 1 + meses
    anio, mes = desde.year + m // 12, m % 12 + 1
    return date(anio, mes, min(desde.day, calendar.monthrange(anio, mes)[1]))


@requiere_acceso
@require_POST
def pago_registrar(request, schema):
    e = _empresa_o_404(schema)
    try:
        monto = int(request.POST.get('monto', '').replace('.', '').replace(',', '').strip())
        meses = int(request.POST.get('meses', '1'))
        fecha = date.fromisoformat(request.POST.get('fecha', '')) if request.POST.get('fecha') else estado.hoy()
        tipo = request.POST.get('tipo', '')
        plan = request.POST.get('plan', '')
        if plan and plan not in Client.MESES_PLAN:
            raise ValueError
        if tipo not in dict(Pago.TIPOS) or not 0 < monto <= 1_000_000_000 or not 0 <= meses <= 36:
            raise ValueError
    except ValueError:
        return _volver(schema, error='Revisa el pago: concepto, monto (mayor que cero), meses (0 a 36) y fecha.')
    Pago.objects.create(empresa=e, fecha=fecha, tipo=tipo, monto_cop=monto, meses=meses, nota=request.POST.get('nota', '').strip()[:200])
    efecto = 'solo registrado'
    if meses and tipo == 'suscripcion':
        e.paid_until = sumar_meses(max(e.paid_until or fecha, estado.hoy()), meses)
        e.on_trial, e.suspendida = False, False
        if plan:
            e.plan = plan
        e.save(update_fields=['paid_until', 'on_trial', 'suspendida', 'plan'])
        efecto = f'suscripción hasta {e.paid_until:%d/%m/%Y}'
    elif meses and tipo == 'aslani':
        e.aslani_hasta = sumar_meses(max(e.aslani_hasta or fecha, estado.hoy()), meses)
        e.aslani_ia_activa = True
        e.save(update_fields=['aslani_hasta', 'aslani_ia_activa'])
        efecto = f'Aslani IA hasta {e.aslani_hasta:%d/%m/%Y}'
    auditar(request, 'pago_registrado', schema, f'{tipo} {_pesos(monto)} · {efecto}')
    return _volver(schema, ok=f'Pago de {_pesos(monto)} registrado ({efecto}).')


@requiere_acceso
@require_POST
def pago_eliminar(request, schema, pk):
    e = _empresa_o_404(schema)
    pago = Pago.objects.filter(pk=pk, empresa=e).first()
    if pago is None:
        raise Http404
    pago.delete()
    auditar(request, 'pago_eliminado', schema, f'{pago.tipo} {_pesos(pago.monto_cop)} del {pago.fecha}')
    return _volver(schema, ok='Pago eliminado del historial (las fechas de vencimiento no se tocan; ajústalas en Facturación si hace falta).')


def ingresos_del_mes():
    inicio = estado.hoy().replace(day=1)
    return Pago.objects.filter(fecha__gte=inicio).aggregate(t=Sum('monto_cop'))['t'] or 0


# ---------------------------------------------------------------------------------------------------------------------
# Módulos contratados y suspensión
# ---------------------------------------------------------------------------------------------------------------------
@requiere_acceso
@require_POST
def guardar_modulos(request, schema):
    e = _empresa_o_404(schema)
    antes = (e.modulo_cotizador, e.modulo_asesores, e.modulo_cartera, e.suspendida)
    e.modulo_cotizador = request.POST.get('cotizador') == 'on'
    e.modulo_asesores = request.POST.get('asesores') == 'on'
    e.modulo_cartera = request.POST.get('cartera') == 'on'
    e.suspendida = request.POST.get('suspendida') == 'on'
    e.save(update_fields=['modulo_cotizador', 'modulo_asesores', 'modulo_cartera', 'suspendida'])
    despues = (e.modulo_cotizador, e.modulo_asesores, e.modulo_cartera, e.suspendida)
    if antes != despues:
        auditar(request, 'modulos', schema, f'cotizador={e.modulo_cotizador} asesores={e.modulo_asesores} cartera={e.modulo_cartera} suspendida={e.suspendida}')
    return _volver(schema, ok='Módulos y acceso guardados. Rigen de inmediato para esa empresa.')


# ---------------------------------------------------------------------------------------------------------------------
# Anuncios
# ---------------------------------------------------------------------------------------------------------------------
@requiere_acceso
def anuncios_pagina(request):
    dia = estado.hoy()
    lista = Anuncio.objects.all()[:100]
    for a in lista:
        a.vigente = a.activo and a.desde <= dia <= a.hasta
    return _responder(request, 'plataforma/anuncios.html', {
        'seccion': 'anuncios', 'lista': lista, 'empresas': _empresas(), 'niveles': Anuncio.NIVELES, 'hoy': dia,
        'hasta_defecto': dia + timedelta(days=7), 'aviso': request.GET.get('ok'), 'error': request.GET.get('error')})


@requiere_acceso
@require_POST
def anuncio_crear(request):
    try:
        desde = date.fromisoformat(request.POST['desde'])
        hasta = date.fromisoformat(request.POST['hasta'])
        titulo, mensaje = request.POST['titulo'].strip(), request.POST['mensaje'].strip()
        nivel, schema = request.POST.get('nivel', 'info'), request.POST.get('schema', '').strip()
        if not titulo or not mensaje or hasta < desde or nivel not in dict(Anuncio.NIVELES):
            raise ValueError
        if schema and not _empresas().filter(schema_name=schema).exists():
            raise ValueError
    except (ValueError, KeyError):
        return _redirigir('plataforma_anuncios', error='Revisa el anuncio: título, mensaje y fechas (la final no puede ser anterior a la inicial).')
    Anuncio.objects.create(titulo=titulo[:80], mensaje=mensaje[:400], nivel=nivel, schema=schema, desde=desde, hasta=hasta)
    auditar(request, 'anuncio_creado', schema, titulo[:80])
    return _redirigir('plataforma_anuncios', ok='Anuncio publicado: lo verán los usuarios mientras esté vigente.')


@requiere_acceso
@require_POST
def anuncio_cambiar(request, pk):
    a = Anuncio.objects.filter(pk=pk).first()
    if a is None:
        raise Http404
    if request.POST.get('accion') == 'eliminar':
        a.delete()
        auditar(request, 'anuncio_eliminado', a.schema, a.titulo)
        return _redirigir('plataforma_anuncios', ok='Anuncio eliminado.')
    a.activo = not a.activo
    a.save(update_fields=['activo'])
    auditar(request, 'anuncio_activado' if a.activo else 'anuncio_desactivado', a.schema, a.titulo)
    return _redirigir('plataforma_anuncios', ok='Anuncio activado.' if a.activo else 'Anuncio desactivado.')


# ---------------------------------------------------------------------------------------------------------------------
# Auditoría
# ---------------------------------------------------------------------------------------------------------------------
@requiere_acceso
def auditoria_pagina(request):
    filas = Auditoria.objects.all()
    q = request.GET.get('q', '').strip()
    if q:
        filas = filas.filter(accion__icontains=q) | filas.filter(schema__icontains=q) | filas.filter(detalle__icontains=q)
    return _responder(request, 'plataforma/auditoria.html', {'seccion': 'auditoria', 'filas': filas.order_by('-fecha', '-id')[:300], 'q': q})


# ---------------------------------------------------------------------------------------------------------------------
# Salud de la plataforma
# ---------------------------------------------------------------------------------------------------------------------
def _revision(nombre, nivel, valor, detalle=''):
    return {'nombre': nombre, 'nivel': nivel, 'valor': valor, 'detalle': detalle}


def _migraciones_pendientes(esquema):
    """Migraciones sin aplicar en ese esquema. «public» solo lleva las apps compartidas y las empresas las suyas: las demás no cuentan."""
    from django.apps import apps
    from django.db.migrations.executor import MigrationExecutor

    lista = settings.SHARED_APPS if esquema == get_public_schema_name() else settings.TENANT_APPS
    etiquetas = {apps.get_containing_app_config(a).label for a in lista}
    with schema_context(esquema):
        ejecutor = MigrationExecutor(connection)
        return sum(1 for m, _ in ejecutor.migration_plan(ejecutor.loader.graph.leaf_nodes()) if m.app_label in etiquetas)


def _salud_empresa(e):
    """Lo que hay que mirar de una empresa: vencimiento, bots que fallaron, claves de aseguradora vencidas, usuarios bloqueados."""
    from core.security.choices import LOGIN_ATTEMPT

    fila = {'e': e, 'estado': estado.estado_suscripcion(e), 'errores_bot': None, 'claves_vencidas': None, 'bloqueados': None, 'migraciones': None}
    try:
        with schema_context(e.schema_name):
            from core.policies.models import AseguradoraCredencial, Cotizacion
            from core.user.models import User

            desde = estado.hoy() - timedelta(days=1)
            fila['errores_bot'] = Cotizacion.objects.filter(estado_bot='error', created_at__date__gte=desde).count()
            fila['claves_vencidas'] = AseguradoraCredencial.objects.filter(requiere_cambio_clave=True).count()
            fila['bloqueados'] = User.objects.filter(is_active=False).count()
        fila['migraciones'] = _migraciones_pendientes(e.schema_name)
    except Exception:
        logger.exception('Salud: no se pudo revisar "%s"', e.schema_name)
    return fila


@requiere_acceso
def salud_pagina(request):
    revisiones = []
    t0 = time.perf_counter()
    try:
        with connection.cursor() as c:
            c.execute('SELECT pg_database_size(current_database())')
            tam = c.fetchone()[0]
        ms = round((time.perf_counter() - t0) * 1000)
        revisiones.append(_revision('Base de datos', 'verde' if ms < 300 else 'ambar', f'responde en {ms} ms', f'Tamaño: {respaldos.formato_tamano(tam)}'))
    except Exception as exc:
        revisiones.append(_revision('Base de datos', 'rojo', 'no responde', str(exc)[:120]))
    uso = shutil.disk_usage(settings.BASE_DIR)
    pct = round(uso.used * 100 / uso.total)
    revisiones.append(_revision('Disco del servidor', 'verde' if pct < 80 else 'ambar' if pct < 90 else 'rojo',
                                f'{pct}% usado', f'Libres {respaldos.formato_tamano(uso.free)} de {respaldos.formato_tamano(uso.total)}'))
    r = respaldos.estado()
    revisiones.append(_revision('Respaldos', r['nivel'], r['mensaje'], f'Último completo: {r["ultimo"]["creado"]:%d/%m/%Y %H:%M}' if r['ultimo'] else 'Ve a Respaldos y haz uno ahora.'))
    if not settings.ANTHROPIC_API_KEY:
        revisiones.append(_revision('Aslani (IA)', 'ambar', 'sin llave', 'Sin ANTHROPIC_API_KEY: Aslani responde en modo básico.'))
    elif cache.get('aslani:ia_caida'):
        revisiones.append(_revision('Aslani (IA)', 'rojo', 'con fallas', 'La API falló hace poco (sin saldo o sin conexión): Aslani está en modo básico unos minutos.'))
    else:
        revisiones.append(_revision('Aslani (IA)', 'verde', 'lista', f'Modelo {settings.ASISTENTE_MODELO}'))
    try:
        pendientes = _migraciones_pendientes(get_public_schema_name())
        revisiones.append(_revision('Migraciones (plataforma)', 'verde' if not pendientes else 'rojo', 'al día' if not pendientes else f'{pendientes} pendientes',
                                    '' if not pendientes else 'Corre: manage.py migrate_schemas --shared'))
    except Exception as exc:
        revisiones.append(_revision('Migraciones (plataforma)', 'ambar', 'no se pudo revisar', str(exc)[:120]))
    empresas = [_salud_empresa(e) for e in _empresas()]
    pendientes_emp = sum(1 for f in empresas if f['migraciones'])
    if pendientes_emp:
        revisiones.append(_revision('Migraciones (empresas)', 'rojo', f'{pendientes_emp} empresa(s) con pendientes', 'Corre: manage.py migrate_schemas'))
    peor = 'rojo' if any(x['nivel'] == 'rojo' for x in revisiones) else 'ambar' if any(x['nivel'] == 'ambar' for x in revisiones) else 'verde'
    return _responder(request, 'plataforma/salud.html', {
        'seccion': 'salud', 'revisiones': revisiones, 'empresas': empresas, 'general': peor, 'version': settings.APP_VERSION,
        'revisado': estado.hoy()})


# ---------------------------------------------------------------------------------------------------------------------
# Soporte: usuarios de una empresa
# ---------------------------------------------------------------------------------------------------------------------
def _usuarios(schema):
    from core.security.choices import LOGIN_ATTEMPT
    from core.security.models import UserAccess
    from core.user.models import User

    with schema_context(schema):
        hoy = estado.hoy()
        fallos = dict(UserAccess.objects.filter(login_attempt=LOGIN_ATTEMPT[1][0], date_joined=hoy).values_list('user_id').annotate(n=Count('id')))
        return [{'pk': u.pk, 'username': u.username, 'nombre': u.names or '', 'email': u.email or '', 'activo': u.is_active,
                 'superusuario': u.is_superuser, 'ultimo': u.last_login, 'fallos_hoy': fallos.get(u.pk, 0),
                 'roles': ', '.join(g.name for g in u.groups.all())}
                for u in User.objects.prefetch_related('groups').order_by('-is_superuser', 'username')]


@requiere_acceso
def soporte_pagina(request, schema):
    e = _empresa_o_404(schema)
    return _responder(request, 'plataforma/soporte.html', {
        'e': e, 'usuarios': _usuarios(schema), 'aviso': request.GET.get('ok'), 'error': request.GET.get('error')})


@requiere_acceso
@require_POST
def soporte_desbloquear(request, schema, pk):
    from core.security.choices import LOGIN_ATTEMPT
    from core.security.models import UserAccess
    from core.user.models import User

    _empresa_o_404(schema)
    with schema_context(schema):
        u = User.objects.filter(pk=pk).first()
        if u is None:
            raise Http404
        u.is_active = True
        u.save(update_fields=['is_active'])
        UserAccess.objects.filter(user=u, login_attempt=LOGIN_ATTEMPT[1][0], date_joined=estado.hoy()).delete()  # el contador del día vuelve a 0
    auditar(request, 'usuario_desbloqueado', schema, u.username)
    return _redirigir('plataforma_soporte', ok=f'{u.username} quedó activo y con sus intentos en cero.', args=[schema])


@requiere_acceso
@require_POST
def soporte_clave(request, schema, pk):
    """Genera una clave nueva para un usuario de la empresa. Se muestra UNA vez, en esta misma respuesta (no viaja por la URL)."""
    from core.security.choices import LOGIN_ATTEMPT
    from core.security.models import UserAccess
    from core.user.models import User

    e = _empresa_o_404(schema)
    nueva = secrets.token_urlsafe(9)
    with schema_context(schema):
        u = User.objects.filter(pk=pk).first()
        if u is None:
            raise Http404
        u.set_password(nueva)
        u.is_active = True
        u.save()
        UserAccess.objects.filter(user=u, login_attempt=LOGIN_ATTEMPT[1][0], date_joined=estado.hoy()).delete()
    auditar(request, 'clave_restablecida', schema, u.username)
    return _responder(request, 'plataforma/soporte.html', {
        'e': e, 'usuarios': _usuarios(schema), 'clave_nueva': {'usuario': u.username, 'clave': nueva}})


def _url_empresa(request, e):
    """Dirección de la empresa con el esquema y el puerto del panel. Prefiere el dominio de la misma «familia» que el panel
    (admin.localhost → gali.localhost) y, si no hay, el principal; así sirve igual en local y en producción."""
    dominios = list(Domain.objects.filter(tenant=e).order_by('-is_primary', 'domain'))
    host, _, puerto = request.get_host().partition(':')
    familia = host.rsplit('.', 1)[-1]
    dominio = next((d for d in dominios if d.domain.rsplit('.', 1)[-1] == familia), dominios[0] if dominios else None)
    if dominio is None:
        return None
    return f'{request.scheme}://{dominio.domain}' + (f':{puerto}' if puerto else '')


@requiere_acceso
@require_POST
def soporte_entrar(request, schema, pk):
    """«Entrar como» un usuario de la empresa: token firmado, de un solo uso y de 60 s, que la empresa canjea en /acceso-soporte/."""
    e = _empresa_o_404(schema)
    base = _url_empresa(request, e)
    if base is None:
        return _redirigir('plataforma_soporte', error='La empresa no tiene dominio.', args=[schema])
    token = signing.dumps({'u': pk, 's': schema, 'n': secrets.token_hex(8)}, salt=SAL_SOPORTE)
    auditar(request, 'entrar_como', schema, f'usuario #{pk}')
    return HttpResponseRedirect(f'{base}/acceso-soporte/?{urlencode({"t": token})}')


# ---------------------------------------------------------------------------------------------------------------------
# Crear empresa
# ---------------------------------------------------------------------------------------------------------------------
def _entero(texto, defecto, minimo, maximo):
    try:
        return min(max(int(str(texto).strip()), minimo), maximo)
    except ValueError:
        return defecto


@requiere_acceso
def empresa_nueva(request):
    if request.method != 'POST':
        return _responder(request, 'plataforma/nueva_empresa.html', {'seccion': 'empresas', 'planes': Client.PLANES, 'v': {'dias_prueba': 15, 'preguntas': 900, 'plan': 'mensual', 'cotizador': True, 'asesores': True, 'aslani': True}})
    p = request.POST
    datos = {
        'nombre': p.get('nombre', '').strip(), 'nit': p.get('nit', '').strip(), 'email': p.get('email', '').strip().lower(),
        'telefono': p.get('telefono', '').strip()[:20], 'schema': p.get('schema', '').strip().lower() or creacion.sugerir_schema(p.get('nombre', '')),
        'usuario': p.get('usuario', '').strip() or 'admin', 'nombre_admin': p.get('nombre_admin', '').strip()[:150], 'clave': p.get('clave', ''),
        'dias_prueba': _entero(p.get('dias_prueba'), 15, 0, 365), 'preguntas': _entero(p.get('preguntas'), 900, 0, 1_000_000),
        'cotizador': p.get('cotizador') == 'on', 'asesores': p.get('asesores') == 'on', 'cartera': p.get('cartera') == 'on',
        'aslani': p.get('aslani') == 'on', 'plan': p.get('plan', '') if p.get('plan', '') in Client.MESES_PLAN else '', 'nota': p.get('nota', '').strip()[:2000]}
    errores = creacion.validar(datos)
    if errores:
        return _responder(request, 'plataforma/nueva_empresa.html', {'seccion': 'empresas', 'planes': Client.PLANES, 'v': {**datos, 'clave': ''}, 'errores': errores}, status=400)
    auditar(request, 'empresa_creacion_iniciada', datos['schema'], f'{datos["nombre"]} · NIT {datos["nit"]}')
    creacion.iniciar(datos)
    return HttpResponseRedirect(reverse('plataforma_empresa_nueva_avance', args=[datos['schema']]))


@requiere_acceso
def empresa_nueva_avance(request, schema):
    return _responder(request, 'plataforma/nueva_progreso.html', {'seccion': 'empresas', 'schema': schema})


@requiere_acceso
def empresa_nueva_estado(request, schema):
    datos = creacion.leer(schema)
    if datos is None:
        raise Http404
    return JsonResponse(datos)
