"""Agente local («Agente ASLAN»): un programa en un PC de la oficina que le presta su navegador a los bots.

Cómo encaja todo:

    bot (servidor) ──ws://127.0.0.1──▶ relevo (manage.py relay_agentes) ◀──wss:// /agente/ws/── agente (oficina)
                                                                                      └─▶ Chrome del PC de la oficina

- El bot no cambia: en vez de abrir Chromium en el servidor, se conecta (Playwright `connect`) al relevo, y el relevo
  le pasa los mensajes al agente, que maneja el Chrome de la oficina. El portal ve la IP de la oficina (la que la
  aseguradora ya autorizó) y, si hace falta una persona (captcha de Mapfre), la ventana sale en ese PC.
- Las contraseñas de los portales no se guardan en el PC: el bot las escribe en el navegador, como hoy.
- El agente solo hace conexiones de salida (HTTPS/443): no hay que abrir puertos en la oficina.

Este módulo es la parte «de datos»: códigos de vinculación, llaves, quién está en línea y a qué agente va cada bot.
"""
import hashlib
import hmac
import secrets
from datetime import timedelta

from django.conf import settings
from django.db import transaction
from django.utils import timezone

ALFABETO_CODIGO = 'ABCDEFGHJKMNPQRSTUVWXYZ23456789'  # sin 0/O, 1/I/L: se dicta y se copia sin confusiones
MINUTOS_CODIGO = 15


def _hash(texto):
    return hashlib.sha256(texto.encode('utf-8')).hexdigest()


def _normalizar_codigo(codigo):
    return ''.join(c for c in str(codigo or '').upper() if c.isalnum())


def nuevo_codigo(empresa, usuario=''):
    """Código de un solo uso para vincular un equipo a la empresa. Devuelve (código «ABCD-EFGH», vence)."""
    from core.tenants.models import CodigoVinculacion

    CodigoVinculacion.objects.filter(vence__lt=timezone.now() - timedelta(days=1)).delete()
    crudo = ''.join(secrets.choice(ALFABETO_CODIGO) for _ in range(8))
    vence = timezone.now() + timedelta(minutes=MINUTOS_CODIGO)
    CodigoVinculacion.objects.create(empresa=empresa, codigo_hash=_hash(crudo), usuario=usuario or '', vence=vence)
    return f'{crudo[:4]}-{crudo[4:]}', vence


class VinculacionError(Exception):
    pass


def vincular(codigo, nombre, sistema='', version='', ip=''):
    """Canjea el código por una llave para el agente. Devuelve (agente, llave): la llave solo se ve esta vez."""
    from core.tenants.models import AgenteLocal, CodigoVinculacion

    crudo = _normalizar_codigo(codigo)
    if len(crudo) != 8:
        raise VinculacionError('El código tiene 8 letras y números (ej. ABCD-EFGH).')
    with transaction.atomic():
        registro = (CodigoVinculacion.objects.select_for_update().select_related('empresa')
                    .filter(codigo_hash=_hash(crudo)).first())
        if registro is None or registro.usado or registro.vence < timezone.now():
            raise VinculacionError('El código no existe, ya se usó o venció. Genere uno nuevo en ASLAN › Configuraciones › '
                                   'Agente de la oficina.')
        registro.usado = True
        registro.save(update_fields=['usado'])
        llave = secrets.token_urlsafe(32)
        agente = AgenteLocal.objects.create(
            empresa=registro.empresa, usuario=registro.usuario, llave_hash=_hash(llave),
            nombre=(nombre or 'Equipo sin nombre').strip()[:80], sistema=(sistema or '')[:80],
            version=(version or '')[:20], ip=(ip or '')[:45])
    return agente, llave


def por_llave(llave):
    """El agente vinculado dueño de esa llave, o None."""
    from core.tenants.models import AgenteLocal

    if not llave or len(llave) > 200:
        return None
    return AgenteLocal.objects.select_related('empresa').filter(llave_hash=_hash(llave), activo=True).first()


def en_linea(agente):
    if agente is None or not agente.activo or not agente.conectado or agente.ultima_senal is None:
        return False
    return agente.ultima_senal >= timezone.now() - timedelta(seconds=settings.AGENTE_SEGUNDOS_EN_LINEA)


def agentes_de(schema_name):
    from core.tenants.models import AgenteLocal

    return AgenteLocal.objects.filter(empresa__schema_name=schema_name, activo=True)


def agente_disponible(schema_name, usuario=''):
    """El agente en línea que debe atender un bot de esa empresa: el de quien pidió la cotización si está prendido
    (así la ventana de Mapfre le sale a él), si no el que dio señal más reciente. None si no hay ninguno en línea."""
    candidatos = [a for a in agentes_de(schema_name).order_by('-ultima_senal') if en_linea(a)]
    if not candidatos:
        return None
    propios = [a for a in candidatos if usuario and a.usuario == usuario]
    return (propios or candidatos)[0]


def hay_agente_en_linea(schema_name):
    return any(en_linea(a) for a in agentes_de(schema_name))


def clave_relay():
    """Secreto que presentan los bots al relevo (los agentes usan su propia llave)."""
    if settings.AGENTE_RELAY_CLAVE:
        return settings.AGENTE_RELAY_CLAVE
    return hmac.new(settings.SECRET_KEY.encode('utf-8'), b'aslan-relay-agentes', hashlib.sha256).hexdigest()


def url_sesion(agente, headless=True):
    """Dirección (solo local) por la que un bot abre el navegador del agente a través del relevo."""
    return (f'ws://127.0.0.1:{settings.AGENTE_RELAY_PUERTO}/interno/sesion/{agente.pk}'
            f'?headless={1 if headless else 0}')


def version_playwright_local():
    try:
        from importlib.metadata import version
        return version('playwright')
    except Exception:
        return ''


def _mayor_menor(version):
    partes = str(version or '').split('.')
    return tuple(partes[:2]) if len(partes) >= 2 else None


def compatible(agente):
    """Playwright solo se entiende entre la misma versión (mayor.menor) en el servidor y en el agente."""
    local, remoto = _mayor_menor(version_playwright_local()), _mayor_menor(agente.version_playwright)
    return local is None or remoto is None or local == remoto


def _version_tupla(texto):
    try:
        return tuple(int(p) for p in str(texto).split('.')[:3])
    except ValueError:
        return (0,)


def requiere_actualizar(agente):
    return _version_tupla(agente.version) < _version_tupla(settings.AGENTE_VERSION_MINIMA)


def resumen(agente):
    """Para la pantalla «Agente de la oficina»."""
    senal = timezone.localtime(agente.ultima_senal).strftime('%d/%m/%Y %I:%M %p') if agente.ultima_senal else 'Nunca'
    return {
        'id': agente.pk, 'nombre': agente.nombre, 'usuario': agente.usuario or '—', 'en_linea': en_linea(agente),
        'ultima_senal': senal, 'version': agente.version or '—', 'sistema': agente.sistema or '—',
        'navegador': agente.navegador or '—', 'ip': agente.ip or '—',
        'vinculado': timezone.localtime(agente.creado).strftime('%d/%m/%Y'),
        'actualizar': requiere_actualizar(agente) or not compatible(agente),
    }
