import json
import logging
from functools import wraps

import anthropic
from django.contrib.auth.decorators import login_required
from django.http import JsonResponse, StreamingHttpResponse
from django.utils import timezone
from django.views.decorators.http import require_GET, require_POST

from core.policies.models import AsistenteConversacion
from core.policies.services.asistente import AsistenteNoDisponible, MAX_CONVERSACIONES, _datos_modo, conversar, cupo, ejecutar_accion

logger = logging.getLogger(__name__)


def _con_permiso(vista):
    """Login + permiso `use_asistente` en TODAS las rutas del chat."""
    @wraps(vista)
    @login_required
    def envoltura(request, *args, **kwargs):
        if not request.user.has_perm('policies.use_asistente'):
            return JsonResponse({'error': 'Tu perfil no tiene acceso a Aslani. Pídele a un administrador que active el permiso.'}, status=403)
        return vista(request, *args, **kwargs)
    return envoltura


def _linea(evento):
    return json.dumps(evento, ensure_ascii=False) + '\n'


def _transmitir(usuario, conversacion_id, texto):
    """Convierte el generador de `conversar` en líneas NDJSON; los errores viajan como un evento «error» (la respuesta ya
    empezó, así que no se puede cambiar el código HTTP)."""
    try:
        for evento in conversar(usuario, conversacion_id, texto):
            yield _linea(evento)
    except ValueError as e:
        yield _linea({'t': 'error', 'm': str(e)})
    except AsistenteNoDisponible as e:
        yield _linea({'t': 'error', 'm': str(e), 'cupo': cupo(usuario)})
    except anthropic.RateLimitError:
        yield _linea({'t': 'error', 'm': 'Aslani está muy ocupado. Intenta de nuevo en un minuto.'})
    except anthropic.APIConnectionError:
        yield _linea({'t': 'error', 'm': 'No se pudo conectar con el servicio de Aslani. Revisa la conexión e intenta de nuevo.'})
    except anthropic.APIStatusError:
        logger.exception('Error de la API de Aslani')
        yield _linea({'t': 'error', 'm': 'El servicio de Aslani respondió con un error. Intenta de nuevo más tarde.'})
    except Exception:
        logger.exception('Error inesperado de Aslani')
        yield _linea({'t': 'error', 'm': 'Ocurrió un error inesperado con Aslani.'})


@_con_permiso
@require_POST
def asistente_chat(request):
    """Una pregunta del chat: {conversacion: id|null, mensaje: str}. Responde en vivo (NDJSON, un evento por línea)."""
    try:
        cuerpo = json.loads(request.body or '{}')
    except json.JSONDecodeError:
        return JsonResponse({'error': 'Solicitud inválida.'}, status=400)
    respuesta = StreamingHttpResponse(_transmitir(request.user, cuerpo.get('conversacion'), cuerpo.get('mensaje')),
                                      content_type='application/x-ndjson; charset=utf-8')
    respuesta['Cache-Control'] = 'no-cache'
    respuesta['X-Accel-Buffering'] = 'no'  # que un proxy (nginx) no retenga el flujo
    return respuesta


@_con_permiso
@require_GET
def asistente_conversaciones(request):
    """Historial del usuario (solo el suyo), lo más reciente primero."""
    hoy = timezone.localdate()
    filas = []
    for c in AsistenteConversacion.objects.filter(usuario=request.user)[:MAX_CONVERSACIONES]:
        dias = (hoy - timezone.localtime(c.updated_at).date()).days
        filas.append({'id': c.pk, 'titulo': c.titulo, 'grupo': 'Hoy' if dias == 0 else 'Ayer' if dias == 1 else 'Esta semana' if dias < 7 else 'Anteriores'})
    return JsonResponse({'conversaciones': filas, 'cupo': cupo(request.user), **_datos_modo(request.user)})


@_con_permiso
@require_GET
def asistente_conversacion(request, pk):
    c = AsistenteConversacion.objects.filter(pk=pk, usuario=request.user).first()
    if c is None:
        return JsonResponse({'error': 'No se encontró la conversación.'}, status=404)
    return JsonResponse({'id': c.pk, 'titulo': c.titulo, 'mensajes': [
        {'role': m.rol, 'content': m.contenido, 'consultas': m.consultas} for m in c.mensajes.all()]})


@_con_permiso
@require_POST
def asistente_eliminar(request, pk):
    borradas, _ = AsistenteConversacion.objects.filter(pk=pk, usuario=request.user).delete()
    return JsonResponse({}) if borradas else JsonResponse({'error': 'No se encontró la conversación.'}, status=404)


@_con_permiso
@require_POST
def asistente_accion(request):
    """El usuario confirmó una acción que Aslani propuso: {token}. Se revalidan firma, dueño, permiso y reglas."""
    try:
        token = json.loads(request.body or '{}').get('token', '')
    except json.JSONDecodeError:
        return JsonResponse({'error': 'Solicitud inválida.'}, status=400)
    ok, mensaje = ejecutar_accion(request.user, token)
    return JsonResponse({'ok': ok, 'mensaje': mensaje}, status=200 if ok else 409)
