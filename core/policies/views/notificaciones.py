"""JSON de la campana de notificaciones (lo consulta static/js/notificaciones.js cada minuto)."""
import logging

from django.db import connection
from django.http import JsonResponse
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_GET

from core.policies.services.notificaciones import notificaciones_de

logger = logging.getLogger(__name__)


@never_cache
@require_GET
def notificaciones(request):
    if not request.user.is_authenticated:
        return JsonResponse({'error': 'Sesión vencida'}, status=401)
    try:
        lista = notificaciones_de(request.user, connection.schema_name)
    except Exception:
        logger.exception('No se pudieron calcular las notificaciones')
        lista = []
    return JsonResponse({'notificaciones': lista})
