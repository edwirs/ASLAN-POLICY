"""Reenviar una cotización fallida a UNA aseguradora (crea una cotización nueva y lanza solo ese bot).

Lo usan el botón «Reenviar» de «Ver proceso» y las acciones que confirma el usuario en el chat de Aslani, para que las
reglas (qué se puede reenviar y cuándo) sean exactamente las mismas en los dos sitios.
"""
from django.db import connection

from core.policies.models import Cotizacion
from core.policies.services.bots import BOTS_DISPONIBLES
from core.policies.services.bots.runner import lanzar_bot_en_segundo_plano
from core.policies.services.proceso import EN_CURSO, FINALES_CON_ERROR, marcar_interrumpidas


def motivo_para_no_reenviar(original):
    """Texto que explica por qué NO se puede reenviar esta cotización, o None si sí se puede."""
    aseguradora = original.aseguradora
    if BOTS_DISPONIBLES.get(aseguradora.name) is None or not aseguradora.is_active:
        return f'{aseguradora.name} no está activa para cotizar.'
    if original.estado_bot not in FINALES_CON_ERROR:
        return f'La cotización con {aseguradora.name} no está en error; no hace falta reenviarla.'
    vigentes = list(Cotizacion.objects.filter(vehiculo=original.vehiculo, aseguradora=aseguradora, estado_bot__in=EN_CURSO))
    marcar_interrumpidas(vigentes)
    if any(c.estado_bot in EN_CURSO for c in vigentes):
        return f'Ya hay una cotización en proceso con {aseguradora.name} para esta placa. Espere a que termine.'
    if Cotizacion.objects.filter(vehiculo=original.vehiculo, aseguradora=aseguradora, pk__gt=original.pk).exists():
        return f'Esta solicitud ya fue reenviada a {aseguradora.name}; revise el intento más reciente.'
    return None


def reenviar(original, usuario):
    """Crea la cotización nueva y lanza su bot. Devuelve (cotizacion_nueva, None) o (None, motivo)."""
    motivo = motivo_para_no_reenviar(original)
    if motivo:
        return None, motivo
    nueva = Cotizacion.objects.create(
        vehiculo=original.vehiculo, tomador=original.tomador, asesor=usuario,
        aseguradora=original.aseguradora, tipo_poliza=original.tipo_poliza,
    )
    lanzar_bot_en_segundo_plano(nueva.id, BOTS_DISPONIBLES[original.aseguradora.name], connection.schema_name)
    return nueva, None
