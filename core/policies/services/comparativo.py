"""Comparativo de valores de las aseguradoras para un vehículo.

Por cada aseguradora cuenta UN solo valor:
  - con bot: la prima que siempre se resalta (`Cotizacion.prima_total`: Premium en HDI, Plan Full en La Equidad…)
    de su cotización completada más reciente. Mapfre cuenta el producto elegido en su credencial (Super Trebol) y AXA
    Colpatria sale en dos filas: Plus y VIP (PLANES_DEL_BOT);
  - sin bot (Bolívar, Allianz, Sura…): el valor final que entregó un tercero y se registró a mano
    (`ValorExterno`) más reciente;
  - con bot que no pudo cotizar (p. ej. Seguros del Estado rechaza al navegador del bot): el valor que el asesor
    cotizó a mano en el portal y registró. Si hay valor del bot y valor manual, cuenta el más reciente.
El resultado va ordenado de menor a mayor valor.
"""
from decimal import Decimal

from django.utils import timezone

from core.policies.models import Aseguradora, CoberturaAseguradora, Cotizacion, Poliza, ValorExterno
from core.policies.services.bots import BOTS_DISPONIBLES
from core.policies.services.bots.base import es_aseguradora_actual, normalizar_texto
from core.policies.services.coberturas import secciones_de
from core.policies.services.credenciales import parametro, parametros_de
from core.policies.services.proceso import PLAN_DESTACADO, PLANES_A_MANO, ultimas_por_aseguradora

ETIQUETA_MANUAL = 'Valor final'
SIN_CONDICIONES = 'No cuenta con condiciones para cotización'
ETIQUETA_A_MANO = 'Cotizado a mano'  # aseguradora con bot cuyo valor cotizó el asesor en el portal
SIN_CONDICIONES_CORTO = 'Sin condiciones'  # para el resumen al cliente, donde la columna es angosta
# Seguros del Estado guarda solo sus planes (no `prima_total`): el comparativo toma el Elite.
PLAN_COMPARATIVO = {'Seguros del Estado': 'Elite'}
# Planes de una misma cotización del bot que salen como filas aparte (AXA Colpatria: niveles Plus y VIP de la tarjeta
# PLUS). El primero es el de `prima_total`; los demás se leen de los planes que guardó el bot.
PLANES_DEL_BOT = {'AXA Colpatria': ('Plus', 'VIP')}
# Ficha de coberturas (producto) que corresponde al plan cuyo valor se compara. Sin entrada: «General».
PRODUCTO_COMPARATIVO = {'AXA Colpatria': 'Plus', 'Seguros del Estado': 'Elite'}


def dinero(valor):
    """$1.234.567 (formato colombiano, sin decimales)."""
    return '$' + f'{int(valor):,}'.replace(',', '.')


def soat(vehiculo, hoy=None):
    """Valor del SOAT y días que le quedan de vigencia (desde hoy hasta el vencimiento), listos para mostrar. None si
    no se registró ninguno de los dos."""
    if vehiculo.soat_valor is None and vehiculo.soat_vencimiento is None:
        return None
    hoy = hoy or timezone.localdate()
    datos = {'valor_fmt': dinero(vehiculo.soat_valor) if vehiculo.soat_valor else '', 'vence_fmt': '', 'dias': None,
             'dias_texto': '', 'vencido': False}
    if vehiculo.soat_vencimiento:
        dias = (vehiculo.soat_vencimiento - hoy).days
        datos['vence_fmt'] = vehiculo.soat_vencimiento.strftime('%d/%m/%Y')
        datos['dias'] = dias
        datos['vencido'] = dias < 0
        datos['dias_texto'] = ('Vencido' if dias < 0 else 'Vence hoy' if dias == 0 else '1 día' if dias == 1 else f'{dias} días')
    return datos


def aseguradoras_sin_bot():
    """Aseguradoras activas que no tienen bot: se les registra el valor a mano."""
    return [a for a in Aseguradora.objects.filter(is_active=True).order_by('name') if a.name not in BOTS_DISPONIBLES]


def aseguradoras_valor_manual(vehiculo, filas=None):
    """Aseguradoras a las que se les puede registrar (o reemplazar) un valor manual para este vehículo: las que no tienen
    bot y las que tienen bot pero el comparativo no tiene un valor del bot (falló, no cotizó o se cotizó a mano)."""
    filas = construir(vehiculo)['filas'] if filas is None else filas
    del_bot = {f['aseguradora_id'] for f in filas if f['origen'] == 'bot'}
    return [a for a in Aseguradora.objects.filter(is_active=True).order_by('name')
            if a.name not in BOTS_DISPONIBLES or a.pk not in del_bot]


def pendientes_de_valor(vehiculo, resultado=None):
    """Aseguradoras activas que no tienen NINGÚN valor en el comparativo (ni del bot ni registrado a mano): las sin bot
    que nadie ha informado y las con bot que fallaron o no se cotizaron (p. ej. un bot que no respondió y se olvidó
    cotizar a mano). No incluye las que tienen el bot trabajando todavía ni las marcadas «sin condiciones» a mano. [{'id', 'nombre'}] en orden alfabético."""
    from core.policies.services.proceso import EN_CURSO  # import local: evita ciclo al cargar el módulo
    resultado = construir(vehiculo) if resultado is None else resultado
    con_valor = {f['aseguradora_id'] for f in resultado['filas']} | resultado['sin_condiciones_ids']
    trabajando = {c.aseguradora_id for c in ultimas_por_aseguradora(vehiculo) if c.estado_bot in EN_CURSO}
    return [{'id': a.pk, 'nombre': a.name} for a in Aseguradora.objects.filter(is_active=True).order_by('name')
            if a.pk not in con_valor and a.pk not in trabajando]


def _plan_comparado(aseguradora):
    """Plan del bot cuyo valor cuenta, si no es el de `prima_total`: el «Producto que cuenta en el comparativo» de la
    credencial (Mapfre) o el fijo de PLAN_COMPARATIVO (Seguros del Estado). None = `prima_total`."""
    nombre = aseguradora.name
    if any(p['clave'] == 'producto_destacado' for p in parametros_de(nombre)):
        credencial = aseguradora.credenciales.filter(is_active=True).order_by('-id').first()
        return parametro(credencial, nombre, 'producto_destacado') or None
    return PLAN_COMPARATIVO.get(nombre)


def construir(vehiculo):
    """{'filas': [...], 'sin_valor': [...], 'actual': nombre|None} del vehículo. `actual` es la aseguradora con la que el
    vehículo está asegurado hoy según el aviso de su portal (la que no cotiza porque ya tiene la póliza). Cada fila es un dict con aseguradora, etiqueta
    (qué valor es), valor, origen ('bot' o 'manual'), fecha y la diferencia con el más bajo."""
    activas = {a.pk: a for a in Aseguradora.objects.filter(is_active=True)}
    candidatas = {}
    comparados = {}  # aseguradora_id -> plan que cuenta (None = prima_total)

    completadas = (Cotizacion.objects.filter(vehiculo=vehiculo, estado_bot='completado',
                                             aseguradora__name__in=list(BOTS_DISPONIBLES))
                   .select_related('aseguradora').prefetch_related('planes').order_by('id'))
    for c in completadas:  # orden ascendente: la más reciente de cada aseguradora queda al final
        nombre = c.aseguradora.name
        if c.aseguradora_id not in comparados:
            comparados[c.aseguradora_id] = _plan_comparado(c.aseguradora)
        comparado = comparados[c.aseguradora_id]
        etiqueta = comparado or PLAN_DESTACADO.get(nombre, 'Premium')
        planes = {normalizar_texto(p.nombre_plan): p.prima_total for p in c.planes.all() if p.prima_total and p.prima_total > 0}
        valor = planes.get(normalizar_texto(comparado)) if comparado else None
        if not valor:  # el plan que cuenta no está entre los guardados: el de prima_total (o el destacado)
            valor = c.prima_total or planes.get(normalizar_texto(etiqueta), 0)
        if c.aseguradora_id in activas and valor and valor > 0:
            candidatas[c.aseguradora_id] = {
                'aseguradora': nombre,
                'aseguradora_nombre': nombre,
                'aseguradora_id': c.aseguradora_id,
                'cotizacion_id': c.pk,
                'etiqueta': etiqueta,
                'valor': valor,
                'origen': 'bot',
                'fecha': c.ejecutado_en or c.created_at,
                'planes_bot': planes,
            }

    for v in ValorExterno.objects.filter(vehiculo=vehiculo).select_related('aseguradora').order_by('id'):
        previa = candidatas.get(v.aseguradora_id)
        if v.aseguradora_id in activas and (previa is None or previa['origen'] == 'manual' or v.created_at > previa['fecha']):
            candidatas[v.aseguradora_id] = {
                'aseguradora': v.aseguradora.name,
                'aseguradora_nombre': v.aseguradora.name,
                'aseguradora_id': v.aseguradora_id,
                'cotizacion_id': None,
                'valor_externo_id': v.pk,  # el que se muestra (el más reciente): es el que se corrige o elimina
                'etiqueta': ETIQUETA_MANUAL if v.aseguradora.name not in BOTS_DISPONIBLES else ETIQUETA_A_MANO,
                'valor': v.valor,
                'valor_2': v.valor_2,
                'origen': 'manual',
                'fecha': v.created_at,
                'sin_condiciones': v.sin_condiciones,
            }

    # «Sin condiciones» registrado a mano (el asesor entró al portal y no le dieron cotización): no compite por valor,
    # se lista abajo con ese motivo y se puede quitar.
    marcadas = sorted((f for f in candidatas.values() if f.get('sin_condiciones')), key=lambda f: f['aseguradora'])
    filas = sorted(_separar_planes(f for f in candidatas.values() if not f.get('sin_condiciones')),
                   key=lambda f: (f['valor'], f['aseguradora']))
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
    con_valor = {f['aseguradora_nombre'] for f in filas}
    # Una póliza vigente registrada DESPUÉS del aviso de un portal manda: el aviso («ya tiene póliza vigente») era de
    # antes de que el cliente se cambiara con nosotros.
    poliza = (Poliza.objects.filter(vehiculo=vehiculo, estado='generada', fecha_renovacion__gte=timezone.localdate())
              .select_related('aseguradora').order_by('-created_at').first())
    sin_valor = [{'aseguradora': f['aseguradora'], 'motivo': SIN_CONDICIONES, 'actual': False, 'manual': True,
                  'valor_externo_id': f['valor_externo_id'], 'aseguradora_id': f['aseguradora_id']} for f in marcadas]
    con_valor |= {f['aseguradora'] for f in marcadas}
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
        elif (c.estado_bot == 'error' and c.error_tipo == 'no_cotizable' and es_aseguradora_actual(c.mensaje_bot)
              and not (poliza and poliza.created_at > c.created_at)):
            motivo = 'Aseguradora actual del vehículo'
        elif c.estado_bot == 'error' and c.error_tipo == 'no_cotizable':
            motivo = SIN_CONDICIONES
        elif c.estado_bot == 'error' and c.error_tipo == 'saturado':
            motivo = 'Portal saturado (reenviar más tarde)'
        elif c.estado_bot == 'error' and c.error_tipo == 'clave_vencida':
            motivo = 'Debe cambiar la contraseña del portal'
        else:
            motivo = SIN_CONDICIONES
        sin_valor.append({'aseguradora': nombre, 'motivo': motivo, 'actual': motivo == 'Aseguradora actual del vehículo'})
    sin_valor.sort(key=lambda s: not s['actual'])  # la aseguradora actual, primero
    sin_condiciones = sorted((s for s in sin_valor if s['motivo'] == SIN_CONDICIONES), key=lambda s: s['aseguradora'])
    actual = next((s['aseguradora'] for s in sin_valor if s['actual']), None) or (poliza.aseguradora.name if poliza else None)
    return {'filas': filas, 'sin_valor': sin_valor, 'actual': actual, 'sin_condiciones': sin_condiciones,
            'sin_condiciones_ids': {f['aseguradora_id'] for f in marcadas}}


def _separar_planes(filas):
    """Aseguradoras con dos planes en el comparativo: salen como una fila por plan, con el plan en el nombre.

    - Valores a mano de PLANES_A_MANO (Seguros del Estado Elite/Integral, AXA Colpatria Plus/VIP): el primer plan con
      `valor` y el segundo con `valor_2` (si se registró). Las dos filas comparten el mismo ValorExterno; `campo` dice
      cuál de sus valores muestra cada una (para corregirlo).
    - Cotizaciones del bot de PLANES_DEL_BOT (AXA Colpatria): el primer plan con `prima_total` y los demás con el valor
      de ese plan entre los que guardó el bot. Todas comparten la cotización (y su PDF).
    `aseguradora` es el nombre que se muestra y `aseguradora_nombre` el de la aseguradora."""
    for fila in filas:
        fila.setdefault('plan', '')
        fila.setdefault('campo', 'valor')
        nombre = fila['aseguradora_nombre']
        if fila['origen'] == 'bot':
            planes = PLANES_DEL_BOT.get(nombre)
            if not planes:
                yield fila
                continue
            yield {**fila, 'aseguradora': f'{nombre} {planes[0]}', 'plan': planes[0], 'etiqueta': planes[0]}
            for plan in planes[1:]:
                valor = fila.get('planes_bot', {}).get(normalizar_texto(plan))
                if valor:
                    yield {**fila, 'aseguradora': f'{nombre} {plan}', 'plan': plan, 'etiqueta': plan, 'valor': valor}
            continue
        planes = PLANES_A_MANO.get(nombre)
        if not planes:
            yield fila
            continue
        yield {**fila, 'aseguradora': f'{nombre} {planes[0]}', 'plan': planes[0], 'plan_2': planes[1]}
        if fila.get('valor_2'):
            yield {**fila, 'aseguradora': f'{nombre} {planes[1]}', 'plan': planes[1], 'valor': fila['valor_2'], 'campo': 'valor_2'}


def primeras_aseguradoras(filas, cantidad):
    """Las filas de las `cantidad` aseguradoras más baratas, una por aseguradora (de Seguros del Estado cuenta su plan
    más barato: Elite e Integral son la misma cotización y el mismo PDF; igual Plus y VIP en AXA Colpatria)."""
    elegidas, vistas = [], set()
    for fila in filas:
        if fila['aseguradora_id'] not in vistas:
            vistas.add(fila['aseguradora_id'])
            elegidas.append(fila)
            if len(elegidas) == cantidad:
                break
    return elegidas


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


def _ficha_de(aseguradora_id, nombre, fichas, plan=''):
    """Ficha del producto que corresponde al valor comparado (o la primera de la aseguradora)."""
    propias = fichas.get(aseguradora_id, [])
    producto = plan or PRODUCTO_COMPARATIVO.get(nombre, 'General')
    return next((f for f in propias if f.producto == producto), propias[0] if propias else None)


def _clase_columna(columna):
    if columna.get('sin_condiciones'):
        return 'cmp-col-sincond'
    return 'cmp-col-mejor' if columna['es_mejor'] else 'cmp-col-segunda' if columna['es_segunda'] else ''


def resumen_cliente(filas, sin_condiciones=()):
    """Cuadro para enviar al cliente: una columna por aseguradora que aplica (las que tienen valor), en el orden
    del comparativo (de menor a mayor), con el valor y las coberturas/asistencias de su ficha. Al final, una columna
    por aseguradora sin condiciones (`construir()['sin_condiciones']`), sin valor ni coberturas.

    {'columnas': [{aseguradora, producto, etiqueta, valor_fmt, es_mejor, es_segunda, sin_condiciones, tiene_ficha, clase}],
     'secciones': [{'titulo', 'filas': [{'etiqueta', 'celdas': [{'texto', 'tono', 'clase'}], 'igual'}]}]}
    'igual' marca la fila cuyo texto es idéntico en todas las aseguradoras con valor (para poder ocultarla)."""
    if not filas:
        return {'columnas': [], 'secciones': []}
    fichas = {}
    for ficha in CoberturaAseguradora.objects.filter(aseguradora_id__in={f['aseguradora_id'] for f in filas}).order_by('id'):
        fichas.setdefault(ficha.aseguradora_id, []).append(ficha)

    columnas, contenido = [], []
    for fila in filas:
        ficha = _ficha_de(fila['aseguradora_id'], fila['aseguradora_nombre'], fichas, fila.get('plan', ''))
        columnas.append({
            'aseguradora': fila['aseguradora'],
            'producto': ficha.producto if ficha and ficha.producto != 'General' else '',
            'etiqueta': fila['etiqueta'],
            'valor_fmt': fila['valor_fmt'],
            'es_mejor': fila['posicion'] == 1,
            'es_segunda': fila['posicion'] == 2,
            'sin_condiciones': False,
            'tiene_ficha': ficha is not None,
        })
        contenido.append(secciones_de(ficha) if ficha else None)
    extra = [{'aseguradora': s['aseguradora'], 'producto': '', 'etiqueta': '', 'valor_fmt': SIN_CONDICIONES_CORTO,
              'es_mejor': False, 'es_segunda': False, 'sin_condiciones': True, 'tiene_ficha': True} for s in sin_condiciones]
    for columna in columnas + extra:
        columna['clase'] = _clase_columna(columna)

    modelo = next((c for c in contenido if c), None)
    secciones = []
    if modelo:
        for i, (titulo, campos) in enumerate(modelo):
            filas_seccion = []
            for j, (etiqueta, _) in enumerate(campos):
                celdas = []
                for columna, c in zip(columnas, contenido):
                    texto = c[i][1][j][1] if c else ''
                    celdas.append({'texto': texto, 'tono': _tono(texto), 'clase': columna['clase']})
                textos = {c['texto'] for c in celdas}
                igual = len(textos) == 1 and len(celdas) > 1
                celdas += [{'texto': '', 'tono': 'sincond', 'clase': columna['clase']} for columna in extra]
                filas_seccion.append({'etiqueta': etiqueta, 'celdas': celdas, 'igual': igual})
            secciones.append({'titulo': titulo, 'filas': filas_seccion})
    return {'columnas': columnas + extra, 'secciones': secciones}


def indicadores(filas):
    """Cifras de cabecera del comparativo: la más económica, la segunda más económica y cuánto más cuesta la segunda
    (las dos opciones que se le resaltan al cliente)."""
    if not filas:
        return None
    mejor = filas[0]
    segunda = filas[1] if len(filas) > 1 else None
    brecha = (segunda['valor'] - mejor['valor']) if segunda else Decimal('0')
    return {
        'cantidad': len(filas),
        'mejor': mejor,
        'segunda': segunda,
        'brecha_fmt': dinero(brecha),
        'brecha_pct': (brecha * 100 / mejor['valor']) if segunda and mejor['valor'] else Decimal('0'),
    }
