import logging
import threading

from django_tenants.utils import schema_context

from core.policies.services.bots.base import registrar_error

logger = logging.getLogger(__name__)


def lanzar_bot_en_segundo_plano(cotizacion_id, bot_class, schema_name):
    """Corre bot_class(cotizacion).run() en un hilo aparte.

    Un hilo nuevo no hereda el schema de tenant activo en la conexión del
    hilo de la petición HTTP (django-tenants lo fija por conexión, no de
    forma global), así que hay que reentrar explícitamente al schema
    correcto dentro del hilo.

    Si algo falla ANTES de que el bot maneje sus propios errores (ej. al
    construirlo porque no hay credencial), la cotización se marca con error
    en vez de quedarse "pendiente" para siempre.
    """
    from core.policies.models import Cotizacion

    def _tarea():
        with schema_context(schema_name):
            cotizacion = None
            try:
                cotizacion = Cotizacion.objects.get(pk=cotizacion_id)
                # Algunos portales (ej. Mapfre) piden un reCAPTCHA que solo una persona puede marcar: necesitan ventana visible.
                bot_class(cotizacion, headless=not getattr(bot_class, 'REQUIERE_NAVEGADOR_VISIBLE', False)).run()
            except Exception as exc:
                logger.exception('Error corriendo el bot para la cotización #%s', cotizacion_id)
                if cotizacion is not None:
                    try:
                        registrar_error(cotizacion, exc, 'Preparación del bot', schema_name)
                    except Exception:
                        logger.exception('No se pudo registrar el error de la cotización #%s', cotizacion_id)

    threading.Thread(target=_tarea, daemon=True).start()
