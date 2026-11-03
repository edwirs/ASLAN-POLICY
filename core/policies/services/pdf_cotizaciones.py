"""PDF de las cotizaciones que descargan los bots.

Cada bot descarga el PDF de su cotización siempre (no crea nada nuevo en el portal: la cotización ya existe cuando el bot
lee el precio). Al cliente solo se le adjuntan los de las 2 más baratas; los demás se borran pasados DIAS_CONSERVAR días.
Se conservan siempre los que ya se enviaron en un correo.
"""
import logging
from datetime import timedelta

from django.utils import timezone

from core.policies.models import Cotizacion
from core.policies.services.comparativo import construir

logger = logging.getLogger(__name__)

DIAS_CONSERVAR = 10
MAS_BARATAS = 2


def limpiar_vencidos():
    """Borra los PDF de más de DIAS_CONSERVAR días que no están entre las 2 más baratas de su vehículo ni se enviaron.
    Usar dentro del schema del tenant. Devuelve cuántos borró."""
    limite = timezone.now() - timedelta(days=DIAS_CONSERVAR)
    candidatas = (Cotizacion.objects.filter(pdf_descargado_en__lt=limite, pdf_enviado_en__isnull=True)
                  .exclude(pdf='').exclude(pdf__isnull=True).select_related('vehiculo'))
    borrados = 0
    conservar = {}
    for cotizacion in candidatas:
        vehiculo_id = cotizacion.vehiculo_id
        if vehiculo_id not in conservar:
            filas = construir(cotizacion.vehiculo)['filas'][:MAS_BARATAS]
            conservar[vehiculo_id] = {f['cotizacion_id'] for f in filas if f.get('cotizacion_id')}
        if cotizacion.pk in conservar[vehiculo_id]:
            continue
        cotizacion.pdf.delete(save=False)
        cotizacion.pdf = None
        cotizacion.save(update_fields=['pdf'])
        borrados += 1
    if borrados:
        logger.info('PDF de cotizaciones: %s borrados (más de %s días y fuera de las %s más baratas).', borrados, DIAS_CONSERVAR, MAS_BARATAS)
    return borrados
