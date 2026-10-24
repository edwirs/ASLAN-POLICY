"""Estado comercial de una empresa: módulos contratados, vencimiento de la suscripción y anuncios vigentes.

Lo usan el middleware (bloquea módulos no contratados y empresas suspendidas), los procesadores de contexto (menú y avisos) y
el panel de la plataforma. Todo se calcula con la hora de Colombia.
"""
from django.conf import settings
from django.utils import timezone

MODULOS = ('cotizador', 'asesores', 'cartera')
NOMBRE_MODULO = {'cotizador': 'Cotizador', 'asesores': 'Asesores', 'cartera': 'Cartera'}


def hoy():
    from core.policies.services.panel import TZ_NEGOCIO

    return timezone.localtime(timezone.now(), TZ_NEGOCIO).date()


def modulos_activos(empresa):
    """Conjunto de módulos que la empresa tiene contratados (None = no se sabe: no se filtra nada)."""
    if empresa is None or not hasattr(empresa, 'modulo_cotizador'):
        return None
    return {m for m in MODULOS if getattr(empresa, f'modulo_{m}', False)}


def modulo_de_ruta(ruta):
    """Módulo al que pertenece una URL de las empresas (None = libre). Aslani se controla aparte, con su propio plan."""
    if ruta.startswith('/policies/asistente/'):
        return None
    if ruta.startswith('/policies/asesores/'):
        return 'asesores'
    if ruta.startswith('/policies/'):
        return 'cotizador'
    return None


def estado_suscripcion(empresa):
    """{'nivel', 'dias', 'suspendida', 'mensaje'}: nivel ∈ sin_fecha · ok · por_vencer · gracia · vencida · suspendida.
    `dias` = días que faltan para vencer (negativo si ya venció)."""
    if getattr(empresa, 'suspendida', False):
        return {'nivel': 'suspendida', 'dias': None, 'suspendida': True, 'mensaje': 'El acceso de esta empresa está suspendido.'}
    hasta = getattr(empresa, 'paid_until', None)
    if not hasta:
        return {'nivel': 'sin_fecha', 'dias': None, 'suspendida': False, 'mensaje': ''}
    dias = (hasta - hoy()).days
    if dias > 7:
        return {'nivel': 'ok', 'dias': dias, 'suspendida': False, 'mensaje': ''}
    if dias >= 0:
        cuando = 'hoy' if dias == 0 else 'mañana' if dias == 1 else f'en {dias} días'
        return {'nivel': 'por_vencer', 'dias': dias, 'suspendida': False,
                'mensaje': f'Tu suscripción vence {cuando} ({hasta:%d/%m/%Y}). Comunícate con ASLAN para renovarla.'}
    atrasados = -dias
    if atrasados <= settings.GRACIA_DIAS or not settings.SUSPENDER_POR_VENCIMIENTO:
        restan = max(settings.GRACIA_DIAS - atrasados, 0)
        return {'nivel': 'gracia' if settings.SUSPENDER_POR_VENCIMIENTO else 'vencida', 'dias': dias, 'suspendida': False,
                'mensaje': f'Tu suscripción venció el {hasta:%d/%m/%Y}. ' + (f'Tienes {restan} día(s) para renovarla antes de que se suspenda el acceso.' if settings.SUSPENDER_POR_VENCIMIENTO else 'Renuévala con ASLAN.')}
    return {'nivel': 'suspendida', 'dias': dias, 'suspendida': True,
            'mensaje': f'La suscripción venció el {hasta:%d/%m/%Y} y el período de gracia terminó.'}


def anuncios_para(empresa):
    """Anuncios vigentes para esta empresa (los de todas + los suyos), del más urgente al más suave."""
    from core.tenants.models import Anuncio

    if empresa is None or not hasattr(empresa, 'schema_name'):
        return []
    dia = hoy()
    filas = Anuncio.objects.filter(activo=True, desde__lte=dia, hasta__gte=dia, schema__in=['', empresa.schema_name])
    orden = {'urgente': 0, 'aviso': 1, 'info': 2}
    return sorted(filas, key=lambda a: (orden.get(a.nivel, 3), -a.pk))
