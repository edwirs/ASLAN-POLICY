from core.policies.services.bots.axa_colpatria import AxaColpatriaBot
from core.policies.services.bots.equidad import EquidadBot
from core.policies.services.bots.hdi import HdiBot
from core.policies.services.bots.mundial import MundialBot
from core.policies.services.bots.qualitas import QualitasBot
from core.policies.services.bots.seguros_del_estado import SegurosDelEstadoBot

# Nombre de Aseguradora (como se guarda en BD) -> clase de bot que la cotiza.
# Ambos bots comparten la misma interfaz: Bot(cotizacion, headless=True).run().
BOTS_DISPONIBLES = {
    'Seguros del Estado': SegurosDelEstadoBot,
    'Qualitas': QualitasBot,
    'HDI': HdiBot,
    'La Equidad Seguros': EquidadBot,
    'AXA Colpatria': AxaColpatriaBot,
    'Seguros Mundial': MundialBot,
}
