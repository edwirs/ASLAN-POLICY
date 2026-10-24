"""Comparativo de valores de las aseguradoras para un vehículo.

Por cada aseguradora cuenta UN solo valor:
  - con bot: la prima que siempre se resalta (`Cotizacion.prima_total`: Premium en HDI, Plan Full en La Equidad,
    Plus en AXA…) de su cotización completada más reciente;
  - sin bot (Bolívar, Allianz, Sura…): el valor final que entregó un tercero y se registró a mano
    (`ValorExterno`) más reciente.
El resultado va ordenado de menor a mayor valor.
"""
from decimal import Decimal

from core.policies.models import Aseguradora, CoberturaAseguradora, Cotizacion, ValorExterno
from core.policies.services.bots import BOTS_DISPONIBLES
from core.policies.services.coberturas import secciones_de
from core.policies.services.proceso import PLAN_DESTACADO, ultimas_por_aseguradora

ETIQUETA_MANUAL = 'Valor final'
# Seguros del Estado guarda solo sus planes (no `prima_total`): el comparativo toma el Elite.
PLAN_COMPARATIVO = {'Seguros del Estado': 'Elite'}
# Ficha de coberturas (producto) que corresponde al plan cuyo valor se compara. Sin entrada: «General».
PRODUCTO_COMPARATIVO = {'AXA Colpatria': 'Plus', 'Seguros del Estado': 'Elite'}


def dinero(valor):
    """$1.234.567 (formato colombiano, sin decimales)."""
    return '$' + f'{int(valor):,}'.replace(',', '.')


def aseguradoras_sin_bot():
    """Aseguradoras activas que no tienen bot: se les registra el valor a mano."""
    return [a for a in Aseguradora.objects.filter(is_active=True).order_by('name') if a.name not in BOTS_DISPONIBLES]


def construir(vehiculo):
    """{'filas': [...], 'sin_valor': [...]} del vehículo. Cada fila es un dict con aseguradora, etiqueta
    (qué valor es), valor, origen ('bot' o 'manual'), fecha y la diferencia con el más bajo."""
    activas = {a.pk: a for a in Aseguradora.objects.filter(is_active=True)}
    candidatas = {}

    completadas = (Cotizacion.objects.filter(vehiculo=vehiculo, estado_bot='completado',
                                             aseguradora__name__in=list(BOTS_DISPONIBLES))
                   .select_related('aseguradora').prefetch_related('planes').order_by('id'))
    for c in completadas:  # orden ascendente: la más reciente de cada aseguradora queda al final
        nombre = c.aseguradora.name
        etiqueta = PLAN_COMPARATIVO.get(nombre) or PLAN_DESTACADO.get(nombre, 'Premium')
        valor = c.prima_total
        if not valor:  # el bot no llenó prima_total: se busca el plan destacado entre sus planes
            valor = next((p.prima_total for p in c.planes.all() if p.nombre_plan == etiqueta), 0)
        if c.aseguradora_id in activas and valor and valor > 0:
            candidatas[c.aseguradora_id] = {
                'aseguradora': nombre,
                'etiqueta': etiqueta,
                'valor': valor,
                'origen': 'bot',
                'fecha': c.ejecutado_en or c.created_at,
            }

    for v in ValorExterno.objects.filter(vehiculo=vehiculo).select_related('aseguradora').order_by('id'):
        if v.aseguradora_id in activas and v.aseguradora.name not in BOTS_DISPONIBLES:
            candidatas[v.aseguradora_id] = {
                'aseguradora': v.aseguradora.name,
                'etiqueta': ETIQUETA_MANUAL,
                'valor': v.valor,
                'origen': 'manual',
                'fecha': v.created_at,
            }

    filas = sorted(candidatas.values(), key=lambda f: (f['valor'], f['aseguradora']))
    minimo = filas[0]['valor'] if filas else Decimal('0')
    maximo = filas[-1]['valor'] if filas else Decimal('0')
    for posicion, fila in enumerate(filas, start=1):
        fila['posicion'] = posicion
        fila['diferencia'] = fila['valor'] - minimo
        fila['diferencia_pct'] = (fila['diferencia'] * 100 / minimo) if minimo else Decimal('0')
        fila['valor_fmt'] = dinero(fila['valor'])
        fila['diferencia_fmt'] = dinero(fila['diferencia'])
        fila['barra'] = int(fila['valor'] * 100 / maximo) if maximo else 0  # ancho relativo para la barra del ranking

    # Aseguradoras con bot que no aportan valor: se explica por qué (su última cotización).
    con_valor = {f['aseguradora'] for f in filas}
    sin_valor = []
    ultimas = {c.aseguradora.name: c for c in ultimas_por_aseguradora(vehiculo)}
    nombres_activos = {a.name for a in activas.values()}
    for nombre in BOTS_DISPONIBLES:
        if nombre in con_valor or nombre not in nombres_activos:
            continue
        c = ultimas.get(nombre)
        if c is None:
            motivo = 'Sin cotizar'
        elif c.estado_bot in ('pendiente', 'en_proceso'):
            motivo = 'Cotizando…'
        elif c.estado_bot == 'error' and c.error_tipo == 'no_cotizable':
            motivo = 'No cotiza este vehículo'
        elif c.estado_bot == 'error' and c.error_tipo == 'saturado':
            motivo = 'Portal saturado (reenviar más tarde)'
        elif c.estado_bot == 'error' and c.error_tipo == 'clave_vencida':
            motivo = 'Debe cambiar la contraseña del portal'
        else:
            motivo = 'Sin resultado (falló la cotización)'
        sin_valor.append({'aseguradora': nombre, 'motivo': motivo})
    return {'filas': filas, 'sin_valor': sin_valor}


def _tono(texto):
    """Clasifica el texto de una celda para colorearlo: 'si' (ampara), 'no' (no ampara) o '' (otro)."""
    t = (texto or '').strip().lower()
    if not t:
        return 'vacio'
    if t.startswith('no ampara') or t.startswith('no aplica'):
        return 'no'
    if t.startswith('sí') or t.startswith('si ') or t.startswith('sin deducible') or t == 'ilimitado' or t == 'ilimitada':
        return 'si'
    return ''


def _ficha_de(aseguradora_id, nombre, fichas):
    """Ficha del producto que corresponde al valor comparado (o la primera de la aseguradora)."""
    propias = fichas.get(aseguradora_id, [])
    producto = PRODUCTO_COMPARATIVO.get(nombre, 'General')
    return next((f for f in propias if f.producto == producto), propias[0] if propias else None)


def resumen_cliente(filas):
    """Cuadro para enviar al cliente: una columna por aseguradora que aplica (las que tienen valor), en el orden
    del comparativo (de menor a mayor), con el valor y las coberturas/asistencias de su ficha.

    {'columnas': [{aseguradora, producto, etiqueta, valor_fmt, es_mejor, tiene_ficha}],
     'secciones': [{'titulo', 'filas': [{'etiqueta', 'celdas': [{'texto', 'tono'}], 'igual'}]}]}
    'igual' marca la fila cuyo texto es idéntico en todas las aseguradoras (para poder ocultarla)."""
    if not filas:
        return {'columnas': [], 'secciones': []}
    ids = {a.name: a.pk for a in Aseguradora.objects.filter(name__in=[f['aseguradora'] for f in filas])}
    fichas = {}
    for ficha in CoberturaAseguradora.objects.filter(aseguradora_id__in=ids.values()).order_by('id'):
        fichas.setdefault(ficha.aseguradora_id, []).append(ficha)

    columnas, contenido = [], []
    for fila in filas:
        ficha = _ficha_de(ids.get(fila['aseguradora']), fila['aseguradora'], fichas)
        columnas.append({
            'aseguradora': fila['aseguradora'],
            'producto': ficha.producto if ficha and ficha.producto != 'General' else '',
            'etiqueta': fila['etiqueta'],
            'valor_fmt': fila['valor_fmt'],
            'es_mejor': fila['posicion'] == 1,
            'tiene_ficha': ficha is not None,
        })
        contenido.append(secciones_de(ficha) if ficha else None)

    modelo = next((c for c in contenido if c), None)
    secciones = []
    if modelo:
        for i, (titulo, campos) in enumerate(modelo):
            filas_seccion = []
            for j, (etiqueta, _) in enumerate(campos):
                celdas = []
                for c in contenido:
                    texto = c[i][1][j][1] if c else ''
                    celdas.append({'texto': texto, 'tono': _tono(texto)})
                textos = {c['texto'] for c in celdas}
                filas_seccion.append({'etiqueta': etiqueta, 'celdas': celdas, 'igual': len(textos) == 1 and len(celdas) > 1})
            secciones.append({'titulo': titulo, 'filas': filas_seccion})
    return {'columnas': columnas, 'secciones': secciones}


def indicadores(filas):
    """Cifras de cabecera del comparativo: la más económica, la más alta y la brecha entre ambas."""
    if not filas:
        return None
    mejor, alta = filas[0], filas[-1]
    brecha = alta['valor'] - mejor['valor']
    return {
        'cantidad': len(filas),
        'mejor': mejor,
        'alta': alta,
        'brecha_fmt': dinero(brecha),
        'brecha_pct': (brecha * 100 / mejor['valor']) if mejor['valor'] else Decimal('0'),
    }
