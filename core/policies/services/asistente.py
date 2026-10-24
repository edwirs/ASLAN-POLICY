"""Aslani, el asistente de consultas: el usuario conversa en lenguaje natural sobre lo registrado en la plataforma y
Claude responde usando SOLO las herramientas de este módulo.

Seguridad (por qué es así):
  - Las herramientas de consulta son de SOLO LECTURA y las escribimos nosotros: el modelo nunca ve la base de datos
    ni escribe SQL.
  - Cada herramienta exige el permiso del módulo que consulta (`view_vehiculo`, `view_comparativo`...): Aslani solo sabe
    lo que el rol del usuario ya puede ver. Las herramientas sin permiso ni se le ofrecen al modelo.
  - Se trabaja dentro del esquema (empresa) de la petición, así que nunca se mezclan datos de dos agencias.
  - No se entregan documentos, correos, teléfonos, motor/chasis/serie ni credenciales.
  - Aslani NUNCA ejecuta una acción por su cuenta: solo la PROPONE. Lo que cambia datos (hoy, reenviar una cotización
    a una aseguradora) sale como un botón firmado que el usuario debe confirmar; al confirmar se vuelven a validar el
    permiso y las reglas de siempre (ver `services/reenvio.py`).
  - El historial de cada conversación solo lo ve su dueño.
"""
import json
import logging

import anthropic
from django.conf import settings
from django.core import signing
from django.core.cache import cache
from django.db import transaction
from django.db.models import F, Sum
from django.db.models import Q
from django.urls import reverse
from django.utils import timezone

from core.policies.models import (Aseguradora, Asesor, AsistenteConsumo, AsistenteConversacion, AsistenteMensaje, AsistenteUso,
                                  CoberturaAseguradora, Cotizacion, Vehiculo)
from core.policies.services import comparativo, panel
from core.policies.services.bots import BOTS_DISPONIBLES
from core.policies.services.coberturas import secciones_de
from core.policies.services.credenciales import credencial_vigente, faltantes
from core.policies.services.proceso import resumen_por_vehiculo, serializar_cotizacion, ultimas_por_aseguradora
from core.policies.services.reenvio import motivo_para_no_reenviar, reenviar

logger = logging.getLogger(__name__)

MAX_VUELTAS = 6            # herramientas encadenadas por pregunta
MAX_HISTORIAL = 14         # mensajes previos que se reenvían al modelo
MAX_CARACTERES = 2000      # por mensaje del usuario
MAX_CONVERSACIONES = 60    # las que se listan en el historial
SAL_ACCION = 'aslani-accion'
VIGENCIA_ACCION = 15 * 60  # segundos que dura el botón de confirmar


class AsistenteNoDisponible(Exception):
    """Falta configuración (llave de la API) o se alcanzó el límite diario."""


# ----------------------------------------------------------------------------------------------
# Herramientas (solo lectura, salvo «proponer_reenvio» que únicamente prepara un botón)
# ----------------------------------------------------------------------------------------------
def _url(nombre, *args):
    return reverse(nombre, args=args)


def _resumen_cotizaciones(usuario, dias=30):
    d = panel.datos_panel(dias)
    k, g = d['kpi'], d['graficas']['aseguradoras']
    por_aseg = [{'aseguradora': n, 'completadas': g['ok'][i], 'avisos_del_portal': g['aviso'][i], 'con_error': g['error'][i]}
                for i, n in enumerate(g['categorias'])]
    primas = dict(zip(d['graficas']['primas']['categorias'], d['graficas']['primas']['valores']))
    meses = d['graficas']['meses']
    return {
        'periodo': f'{d["desde"]:%d/%m/%Y} a {d["hasta"]:%d/%m/%Y} ({d["dias"]} días)',
        'solicitudes_nuevas': k['solicitudes'], 'cotizaciones_completadas': k['completadas'],
        'con_error': k['errores'], 'avisos_del_portal': k['avisos'], 'en_curso': k['en_curso'],
        'tasa_exito_porcentaje': k['tasa'],
        'nota_tasa': 'tasa = completadas / (completadas + con error); los avisos del portal no cuentan como falla',
        'por_aseguradora': por_aseg, 'prima_promedio_por_aseguradora_pesos': primas,
        'ultimos_6_meses': dict(zip(meses['categorias'], [{'solicitudes': s, 'completadas': c}
                                                         for s, c in zip(meses['solicitudes'], meses['completadas'])])),
        'enlace_panel': _url('dashboard'),
    }


def _filas_vehiculos(vehiculos):
    avance = resumen_por_vehiculo(vehiculos) if vehiculos else {}
    salida = []
    for v in vehiculos:
        a = avance.get(v.pk, {})
        salida.append({
            'placa': v.placa, 'tomador': v.tomador.names, 'cero_km': v.es_cero_km,
            'registrada': timezone.localtime(v.created_at).strftime('%d/%m/%Y %H:%M'),
            'aseguradoras_con_valor': a.get('ok', 0), 'aseguradoras_consultadas': a.get('total', 0),
            'estado_general': a.get('estado', 'sin_cotizar'),
            'detalle': [{'aseguradora': x['aseguradora'], 'estado': x['estado_bot'], 'tipo_de_error': x['error_tipo']}
                        for x in a.get('detalle', [])],
            'enlace_comparativo': _url('vehiculo_comparativo', v.pk),
        })
    return salida


def _buscar_solicitud(usuario, texto):
    texto = (texto or '').strip()
    if len(texto) < 3:
        return {'error': 'Escribe al menos 3 caracteres (placa, nombre o documento del tomador).'}
    filtro = Q(placa__icontains=texto) | Q(tomador__names__icontains=texto) | Q(tomador__dni=texto)
    vehiculos = list(Vehiculo.objects.select_related('tomador').filter(filtro).order_by('-created_at')[:5])
    if not vehiculos:
        return {'encontradas': 0, 'mensaje': f'No hay solicitudes que coincidan con «{texto}».'}
    return {'encontradas': len(vehiculos), 'solicitudes': _filas_vehiculos(vehiculos), 'enlace_listado': _url('vehiculo_list')}


def _ultimas_solicitudes(usuario, cantidad=5):
    cantidad = max(1, min(int(cantidad or 5), 10))
    vehiculos = list(Vehiculo.objects.select_related('tomador').order_by('-created_at')[:cantidad])
    return {'solicitudes': _filas_vehiculos(vehiculos), 'enlace_listado': _url('vehiculo_list')}


def _detalle_solicitud(usuario, placa):
    v = Vehiculo.objects.select_related('tomador', 'zona_circulacion__departamento').filter(placa__iexact=(placa or '').strip()).first()
    if not v:
        return {'error': f'No existe una solicitud con la placa {placa}.'}
    cotizaciones = []
    for c in ultimas_por_aseguradora(v):
        s = serializar_cotizacion(c)
        fila = {'aseguradora': s['aseguradora'], 'estado': s['estado_bot_display'], 'intento_numero': s['intento'],
                'iniciada': s['iniciada']}
        if s['estado_bot'] == 'completado':
            fila.update({'prima_destacada': s['prima_total'], 'que_prima_es': s['plan_destacado'],
                         'planes': [{'plan': p['nombre'], 'prima': p['prima']} for p in s['planes']],
                         'nota': s['nota']})
        elif s['error_tipo']:
            fila.update({'tipo_de_error': s['error_tipo_display'], 'que_paso': s['mensaje'], 'que_hacer': s['accion'],
                         'se_puede_reenviar': s['puede_reintentar']})
        cotizaciones.append(fila)
    return {
        'placa': v.placa, 'tomador': v.tomador.names, 'cero_km': v.es_cero_km,
        'vehiculo': {k: val for k, val in {
            'marca': v.marca, 'clase': v.clase, 'version': v.referencia, 'modelo': v.modelo, 'servicio': v.servicio,
            'tipo': v.tipo_vehiculo, 'color': v.color, 'combustible': v.combustible,
            'valor_comercial': float(v.valor_comercial) if v.valor_comercial else None,
            'codigo_fasecolda': v.codigo_fasecolda,
            'ciudad_de_circulacion': str(v.zona_circulacion) if v.zona_circulacion_id else None}.items() if val not in (None, '')},
        'cotizaciones_por_aseguradora': cotizaciones,
        'enlace_comparativo': _url('vehiculo_comparativo', v.pk), 'enlace_solicitudes': _url('vehiculo_list'),
    }


def _comparativo_de_placa(usuario, placa):
    v = Vehiculo.objects.filter(placa__iexact=(placa or '').strip()).first()
    if not v:
        return {'error': f'No existe una solicitud con la placa {placa}.'}
    c = comparativo.construir(v)
    return {
        'placa': v.placa,
        'ranking_de_menor_a_mayor': [{
            'posicion': f['posicion'], 'aseguradora': f['aseguradora'], 'valor': f['valor_fmt'],
            'que_valor_es': f['etiqueta'], 'origen': 'bot' if f['origen'] == 'bot' else 'registrado a mano',
            'mas_que_el_mas_barato': f['diferencia_fmt'],
        } for f in c['filas']],
        'sin_valor': [{'aseguradora': s['aseguradora'], 'motivo': s['motivo']} for s in c['sin_valor']],
        'enlace_comparativo': _url('vehiculo_comparativo', v.pk),
    }


def _coberturas(usuario, aseguradora):
    fichas = list(CoberturaAseguradora.objects.select_related('aseguradora').filter(aseguradora__name__icontains=(aseguradora or '').strip())[:4])
    if not fichas:
        return {'error': f'No hay ficha de coberturas cargada para «{aseguradora}».'}
    return {'fichas': [{
        'aseguradora': f.aseguradora.name, 'producto': f.producto,
        'coberturas': {etiqueta: valor for _, filas in secciones_de(f) for etiqueta, valor in filas if valor},
    } for f in fichas], 'enlace': _url('aseguradora_coberturas', fichas[0].aseguradora_id)}


def _pendientes(usuario):
    a = panel.datos_panel(30)['atencion']
    salida = {
        'aseguradoras_que_piden_cambiar_contrasena': a['claves'],
        'cotizaciones_esperando_codigo_de_verificacion': a['esperando'],
        'principales_causas_de_falla_30_dias': a['causas'],
    }
    if usuario.has_perm('policies.view_aseguradora'):
        salida['aseguradoras_con_datos_de_acceso_incompletos'] = a['incompletas']
        salida['enlace_aseguradoras'] = _url('aseguradora_list')
    return salida


def _aseguradoras(usuario):
    filas = []
    for a in Aseguradora.objects.order_by('name'):
        cred = credencial_vigente(a)
        filas.append({
            'aseguradora': a.name, 'activa': a.is_active, 'tiene_bot': a.name in BOTS_DISPONIBLES,
            'datos_de_acceso_completos': (not faltantes(a, cred)) if a.name in BOTS_DISPONIBLES else None,
            'pide_cambiar_contrasena': bool(cred and cred.requiere_cambio_clave),
        })
    return {'aseguradoras': filas, 'enlace': _url('aseguradora_list')}


def _asesores(usuario):
    return {'asesores': [{'nombre': a.nombres, 'tipo': a.get_tipo_display(), 'empresa': a.empresa, 'activo': a.is_active,
                          'comision_porcentaje': float(a.porcentaje_comision)} for a in Asesor.objects.order_by('nombres')],
            'enlace': _url('asesor_list')}


def _proponer_reenvio(usuario, placa, aseguradora):
    """NO reenvía: valida y prepara un botón firmado para que el usuario lo confirme en pantalla."""
    v = Vehiculo.objects.filter(placa__iexact=(placa or '').strip()).first()
    if not v:
        return {'error': f'No existe una solicitud con la placa {placa}.'}
    a = Aseguradora.objects.filter(name__iexact=(aseguradora or '').strip()).first()
    if not a:
        return {'error': f'No existe la aseguradora «{aseguradora}».'}
    original = Cotizacion.objects.select_related('aseguradora', 'vehiculo', 'tomador').filter(vehiculo=v, aseguradora=a).order_by('-id').first()
    if original is None:
        return {'error': f'La placa {v.placa} nunca se cotizó con {a.name}.'}
    motivo = motivo_para_no_reenviar(original)
    if motivo:
        return {'error': motivo}
    token = signing.dumps({'a': 'reenviar', 'c': original.pk, 'u': usuario.pk}, salt=SAL_ACCION)
    return {
        'resultado': 'Se le mostró al usuario un botón para confirmar el reenvío; AÚN NO se hizo nada. Dile que lo confirme con el botón.',
        '_accion': {'token': token, 'titulo': f'Reenviar {v.placa} a {a.name}',
                    'detalle': f'Se enviará de nuevo la solicitud de {v.placa} a {a.name}. El bot volverá a cotizar y verás el resultado en «Ver proceso».',
                    'boton': 'Confirmar y reenviar'},
    }


def ejecutar_accion(usuario, token):
    """Ejecuta una acción que el usuario confirmó con el botón. Devuelve (ok, mensaje)."""
    try:
        datos = signing.loads(token, salt=SAL_ACCION, max_age=VIGENCIA_ACCION)
    except signing.SignatureExpired:
        return False, 'La confirmación venció (pasaron más de 15 minutos). Pídele de nuevo a Aslani que la prepare.'
    except signing.BadSignature:
        return False, 'La confirmación no es válida.'
    if datos.get('u') != usuario.pk:
        return False, 'Esta confirmación no es tuya.'
    if datos.get('a') == 'reenviar':
        if not usuario.has_perm('policies.add_vehiculo'):
            return False, 'Tu perfil no puede reenviar cotizaciones.'
        original = Cotizacion.objects.select_related('aseguradora', 'vehiculo', 'tomador').filter(pk=datos.get('c')).first()
        if original is None:
            return False, 'No se encontró la cotización original.'
        nueva, motivo = reenviar(original, usuario)
        if motivo:
            return False, motivo
        return True, f'Listo: se reenvió {original.vehiculo.placa} a {original.aseguradora.name}. El bot ya está cotizando; mira el avance en «Ver proceso».'
    return False, 'Acción desconocida.'


def _esquema(propiedades=None, requeridas=()):
    return {'type': 'object', 'properties': propiedades or {}, 'required': list(requeridas), 'additionalProperties': False}


_PLACA = {'type': 'string', 'description': 'Placa del vehículo, ej. BWF282.'}

# nombre -> (permiso, descripción para el modelo, esquema, función, etiqueta corta para el usuario)
HERRAMIENTAS = {
    'resumen_cotizaciones': ('policies.view_vehiculo',
        'Cifras de cotizaciones de un período: solicitudes nuevas, cotizaciones completadas, errores, avisos del portal, tasa de '
        'éxito, resultado por aseguradora, prima promedio por aseguradora y evolución de los últimos 6 meses.',
        _esquema({'dias': {'type': 'integer', 'enum': [7, 30, 90], 'description': 'Días hacia atrás (por defecto 30).'}}),
        _resumen_cotizaciones, 'resumen de cotizaciones'),
    'buscar_solicitud': ('policies.view_vehiculo',
        'Busca solicitudes por placa, nombre del tomador o su número de documento y devuelve el estado de la cotización '
        'con cada aseguradora. Máximo 5 resultados.',
        _esquema({'texto': {'type': 'string', 'description': 'Placa, parte del nombre o documento del tomador.'}}, ['texto']),
        _buscar_solicitud, 'búsqueda de solicitudes'),
    'ultimas_solicitudes': ('policies.view_vehiculo',
        'Las solicitudes más recientes con el estado de su cotización por aseguradora.',
        _esquema({'cantidad': {'type': 'integer', 'description': 'Entre 1 y 10 (por defecto 5).'}}),
        _ultimas_solicitudes, 'últimas solicitudes'),
    'detalle_solicitud': ('policies.view_vehiculo',
        'Todo sobre una placa: datos del vehículo (marca, modelo, valor comercial...), y por cada aseguradora el resultado de su '
        'última cotización: prima y planes si salió, o qué pasó y qué hacer si falló (úsala para «¿por qué falló…?»).',
        _esquema({'placa': _PLACA}, ['placa']),
        _detalle_solicitud, 'detalle de la solicitud'),
    'comparativo_de_placa': ('policies.view_comparativo',
        'Ranking de valores cotizados para una placa, de la aseguradora más barata a la más cara, y las que no tienen valor '
        'con el motivo.',
        _esquema({'placa': _PLACA}, ['placa']),
        _comparativo_de_placa, 'comparativo'),
    'coberturas_de_aseguradora': ('policies.view_aseguradora',
        'Ficha de coberturas y asistencias de una aseguradora (responsabilidad civil, pérdida total, grúa, vehículo de reemplazo, '
        'etc.). Úsala para «¿qué cubre X?» o comparar coberturas.',
        _esquema({'aseguradora': {'type': 'string', 'description': 'Nombre de la aseguradora, ej. Qualitas.'}}, ['aseguradora']),
        _coberturas, 'coberturas'),
    'pendientes': ('policies.view_vehiculo',
        'Qué requiere atención: aseguradoras que piden cambiar la contraseña, cotizaciones esperando un código, datos de '
        'acceso incompletos y las principales causas de falla.',
        _esquema(),
        _pendientes, 'pendientes'),
    'aseguradoras': ('policies.view_aseguradora',
        'Lista de aseguradoras: si están activas, si tienen bot, si sus datos de acceso están completos y si piden cambiar la '
        'contraseña. No incluye contraseñas ni usuarios.',
        _esquema(),
        _aseguradoras, 'aseguradoras'),
    'asesores': ('policies.view_asesor',
        'Asesores internos y externos con su comisión pactada.',
        _esquema(),
        _asesores, 'asesores'),
    'proponer_reenvio': ('policies.add_vehiculo',
        'Prepara el reenvío de una cotización que falló a UNA aseguradora. NO lo ejecuta: muestra al usuario un botón de '
        'confirmación. Úsala solo si el usuario pidió reenviar/reintentar y primero mira el detalle para saber si procede.',
        _esquema({'placa': _PLACA, 'aseguradora': {'type': 'string', 'description': 'Nombre de la aseguradora.'}}, ['placa', 'aseguradora']),
        _proponer_reenvio, 'reenvío propuesto'),
}


def herramientas_para(usuario):
    """Definiciones que se le ofrecen al modelo: solo las que el rol del usuario puede usar."""
    return [{'name': n, 'description': d, 'input_schema': e}
            for n, (permiso, d, e, _, _) in HERRAMIENTAS.items() if usuario.has_perm(permiso)]


def etiqueta_herramienta(nombre):
    return HERRAMIENTAS[nombre][4] if nombre in HERRAMIENTAS else nombre


def ejecutar_herramienta(usuario, nombre, argumentos):
    """Corre una herramienta. Devuelve (texto_json_para_el_modelo, es_error, accion_o_None). Nunca lanza."""
    herramienta = HERRAMIENTAS.get(nombre)
    if herramienta is None or not usuario.has_perm(herramienta[0]):
        return json.dumps({'error': 'Esa consulta no está disponible para tu perfil.'}, ensure_ascii=False), True, None
    try:
        resultado = herramienta[3](usuario, **(argumentos or {}))
    except TypeError:
        return json.dumps({'error': 'Argumentos inválidos para esta consulta.'}, ensure_ascii=False), True, None
    except Exception:
        logger.exception('Falló la herramienta de Aslani "%s"', nombre)
        return json.dumps({'error': 'No se pudo hacer la consulta.'}, ensure_ascii=False), True, None
    accion = resultado.pop('_accion', None) if isinstance(resultado, dict) else None  # el token firmado no pasa por el modelo
    return json.dumps(resultado, ensure_ascii=False, default=str), bool(isinstance(resultado, dict) and resultado.get('error')), accion


# ----------------------------------------------------------------------------------------------
# Conversación
# ----------------------------------------------------------------------------------------------
def _instrucciones():
    hoy = timezone.localtime(timezone.now(), panel.TZ_NEGOCIO).date()
    return (
        'Eres Aslani, el asistente de ASLAN MultiAgente de Seguros, una plataforma que cotiza seguros de autos todo riesgo en '
        'varias aseguradoras con bots, compara los valores y gestiona asesores. Hablas con el equipo de una agencia de seguros '
        'y respondes sobre lo registrado en la plataforma.\n\n'
        'Reglas:\n'
        '- Usa SOLO las herramientas para obtener datos; no inventes cifras, placas ni nombres. Si una herramienta no existe o '
        'no está disponible para el usuario, dilo con claridad.\n'
        '- Solo puedes consultar. Lo único que puedes preparar es el reenvío de una cotización fallida (herramienta '
        '«proponer_reenvio»), que el usuario confirma con un botón: nunca digas que ya se hizo antes de que confirme. Para '
        'cualquier otro cambio, explica en qué pantalla se hace.\n'
        '- Nunca reveles contraseñas, credenciales, documentos, correos ni teléfonos.\n'
        '- Responde en español de Colombia, breve, claro y amable; usa listas o tablas cortas cuando ayuden. Montos con puntos '
        'de miles y signo $ (ej. $1.234.567). Si el período no se indica, usa 30 días y dilo.\n'
        '- Cuando ayude, enlaza la pantalla con un enlace en markdown, por ejemplo [Ver comparativo](/policies/vehiculos/3/comparativo/). '
        'Usa SOLO rutas que te hayan dado las herramientas o esta guía (empiezan por /); nunca inventes rutas.\n'
        '- Un «aviso del portal» (ej. el vehículo ya está asegurado) no es una falla del bot.\n'
        '- Si el usuario saluda o pregunta cómo usar el sistema, responde con la guía; no consultes datos sin necesidad.\n\n'
        'Guía rápida del sistema:\n'
        f'- Nueva solicitud: Cotizador › Nueva solicitud ({_url("solicitud_cotizacion_create")}). Se eligen las aseguradoras con las que cotizar.\n'
        f'- Estado, reenvío y comparativo: Cotizador › Solicitudes registradas ({_url("vehiculo_list")}); en cada fila hay «Ver proceso» y el comparativo (balanza).\n'
        f'- Vehículos con todos sus datos: Vehículos › Vehículos registrados ({_url("vehiculo_registrado_list")}).\n'
        f'- Aseguradoras, contraseñas y estado activo: Configuraciones › Aseguradoras ({_url("aseguradora_list")}). Si una aseguradora pide '
        'cambiar la contraseña, se cambia en su portal y se actualiza ahí; mientras tanto no se cotiza con ella.\n'
        f'- Asesores internos y externos con su comisión: Configuraciones › Asesores ({_url("asesor_list")}).\n'
        f'- Panel con las cifras: {_url("dashboard")}.\n'
        '- Aseguradoras sin bot (Bolívar, Allianz, Sura): su valor lo entrega un tercero y se registra a mano al hacer el comparativo.\n'
        f'- Hoy es {hoy:%d/%m/%Y}.'
    )


MESES_ES = ['enero', 'febrero', 'marzo', 'abril', 'mayo', 'junio', 'julio', 'agosto', 'septiembre', 'octubre', 'noviembre', 'diciembre']
LIMITE_USUARIO_DIARIO = 60   # freno por persona para que una sola no se gaste la bolsa de toda la empresa (ajustable en settings)


def _limite_usuario():
    return getattr(settings, 'ASISTENTE_LIMITE_DIARIO', LIMITE_USUARIO_DIARIO)


def _hoy():
    return timezone.localtime(timezone.now(), panel.TZ_NEGOCIO).date()


def _empresa():
    """La empresa (Client) de esta petición, con su plan de Aslani. None si no se encuentra (se asume el plan por defecto)."""
    from django.db import connection
    from django_tenants.utils import get_tenant_model  # import local: evita ciclos al cargar el módulo

    return get_tenant_model().objects.filter(schema_name=connection.schema_name).first()


def _plan():
    """(ia_activa, preguntas_por_mes). Lo fija ASLAN en el panel de la plataforma; la empresa no lo cambia."""
    empresa = _empresa()
    return (empresa.aslani_ia_activa, empresa.aslani_preguntas_mes) if empresa else (True, 900)


def _mes():
    """(primer día de este mes, primer día del mes siguiente)."""
    hoy = _hoy()
    inicio = hoy.replace(day=1)
    siguiente = inicio.replace(year=inicio.year + (inicio.month == 12), month=inicio.month % 12 + 1)
    return inicio, siguiente


def cupo(usuario):
    """La bolsa del MES de la empresa (todas las personas gastan de la misma) y cuánto queda; se renueva el día 1 y no se acumula."""
    _, por_mes = _plan()
    inicio, siguiente = _mes()
    usadas = AsistenteUso.objects.filter(fecha__gte=inicio, fecha__lt=siguiente).aggregate(t=Sum('preguntas'))['t'] or 0
    return {'usadas': usadas, 'limite': por_mes, 'restantes': max(por_mes - usadas, 0),
            'renueva': f'{siguiente.day} de {MESES_ES[siguiente.month - 1]}'}


def _estado_plan(usuario):
    """(ok, motivo): si la empresa puede usar la IA ahora (plan activo y bolsa del mes con preguntas)."""
    empresa = _empresa()
    if empresa is not None:
        if not empresa.aslani_ia_activa:
            return False, 'La inteligencia artificial de Aslani no está activada en el plan de tu empresa.'
        if empresa.aslani_hasta and _hoy() > empresa.aslani_hasta:
            return False, f'El plan de Aslani IA de tu empresa venció el {empresa.aslani_hasta:%d/%m/%Y}; renuévalo con ASLAN para volver a usar la IA.'
    c = cupo(usuario)
    if c['restantes'] <= 0:
        return False, f'Se agotó la bolsa de {c["limite"]} preguntas del mes; Aslani sigue en modo básico y se renueva el {c["renueva"]}.'
    return True, None


def costo_usd(modelo, entrada, salida, cache_lectura, cache_escritura):
    """Costo en dólares de una llamada, con la tabla de precios de settings (por millón de tokens)."""
    p_in, p_out, p_leer, p_escribir = settings.ASISTENTE_PRECIOS_USD.get(modelo) or settings.ASISTENTE_PRECIOS_USD['claude-sonnet-5-5']
    return (entrada * p_in + salida * p_out + cache_lectura * p_leer + cache_escritura * p_escribir) / 1_000_000


def _consumir(usuario):
    """Cuenta una pregunta de la bolsa del mes o lanza AsistenteNoDisponible (bolsa agotada o tope diario personal)."""
    with transaction.atomic():
        uso, _ = AsistenteUso.objects.select_for_update().get_or_create(usuario=usuario, fecha=_hoy())
        if uso.preguntas >= _limite_usuario():
            raise AsistenteNoDisponible(f'Llegaste a tu tope personal de {_limite_usuario()} preguntas por hoy; vuelve mañana (Aslani sigue en modo básico).')
        ok, motivo = _estado_plan(usuario)
        if not ok:
            raise AsistenteNoDisponible(motivo)
        AsistenteUso.objects.filter(pk=uso.pk).update(preguntas=F('preguntas') + 1)


def _devolver(usuario):
    """Si la pregunta falló por un problema del servicio, no se le cobra al usuario del cupo."""
    AsistenteUso.objects.filter(usuario=usuario, fecha=_hoy(), preguntas__gt=0).update(preguntas=F('preguntas') - 1)


CLAVE_IA_CAIDA = 'aslani:ia_caida'
MINUTOS_IA_CAIDA = 3


def _cliente():
    """Cliente de la API, o None si no hay llave (entonces Aslani responde en modo básico)."""
    if not getattr(settings, 'ANTHROPIC_API_KEY', ''):
        return None
    return anthropic.Anthropic(api_key=settings.ANTHROPIC_API_KEY, timeout=90.0, max_retries=1)


def _motivo_de(error):
    """Por qué no se pudo usar la IA, en palabras para un administrador."""
    if isinstance(error, anthropic.AuthenticationError):
        return 'La llave de la API de Anthropic no es válida o fue revocada.'
    if isinstance(error, anthropic.PermissionDeniedError):
        return 'La llave de la API no tiene permiso para usar este modelo.'
    if isinstance(error, anthropic.BadRequestError) and 'credit' in str(error).lower():
        return 'La cuenta de Anthropic no tiene saldo: hay que recargar créditos.'
    if isinstance(error, anthropic.RateLimitError):
        return 'La API de Anthropic está limitando las consultas (demasiadas por minuto).'
    if isinstance(error, anthropic.APIConnectionError):
        return 'No hay conexión con la API de Anthropic.'
    return 'La API de Anthropic respondió con un error.'


def modo_actual(usuario=None, con_llave=True):
    """('ia'|'basico', motivo|None, motivo_es_publico): cómo está respondiendo Aslani. Los motivos técnicos (llave, saldo de la API)
    solo los ven los administradores; los de plan (IA no contratada, bolsa agotada) los ve todo el mundo."""
    if con_llave and not getattr(settings, 'ANTHROPIC_API_KEY', ''):
        return 'basico', 'Falta configurar la llave de la API de Anthropic (ANTHROPIC_API_KEY).', False
    ok, motivo = _estado_plan(usuario)
    if not ok:
        return 'basico', motivo, True
    caida = cache.get(CLAVE_IA_CAIDA)
    return ('basico', caida, False) if caida else ('ia', None, False)


def _datos_modo(usuario):
    modo, motivo, publico = modo_actual(usuario)
    return {'modo': modo, 'motivo': motivo if (modo == 'basico' and (publico or usuario.is_superuser)) else None}


def _titulo_de(texto):
    texto = ' '.join(texto.split())
    return (texto[:57] + '…') if len(texto) > 58 else texto


def _abrir_conversacion(usuario, conversacion_id, texto):
    """(conversacion, mensajes_previos). Una conversación nueva no se guarda hasta que la respuesta termine bien."""
    if conversacion_id in (None, '', 0):
        return AsistenteConversacion(usuario=usuario, titulo=_titulo_de(texto)), []
    conversacion = AsistenteConversacion.objects.filter(pk=conversacion_id, usuario=usuario).first()
    if conversacion is None:
        raise ValueError('No se encontró esa conversación.')
    previos = list(conversacion.mensajes.order_by('-id')[:MAX_HISTORIAL])
    return conversacion, [{'role': m.rol, 'content': m.contenido} for m in reversed(previos)]


def _guardar(conversacion, texto, respuesta, consultas):
    if conversacion.pk is None:
        conversacion.save()
    else:
        conversacion.save(update_fields=['updated_at'])
    AsistenteMensaje.objects.create(conversacion=conversacion, rol='user', contenido=texto)
    AsistenteMensaje.objects.create(conversacion=conversacion, rol='assistant', contenido=respuesta, consultas=consultas)


def conversar(usuario, conversacion_id, texto, cliente=None):
    """Generador de eventos para el chat en vivo. Responde a `texto` dentro de la conversación (o crea una nueva).

    Eventos (dicts): inicio · modo · texto (delta) · herramienta · accion · opciones · fin · (el llamador convierte las
    excepciones en «error»). Guarda el intercambio solo si terminó bien: una pregunta que falló no ensucia el historial.

    Si la IA no está disponible (sin llave, sin saldo, sin conexión…) responde en MODO BÁSICO (`asistente_basico`) en vez de fallar."""
    texto = (texto or '').strip()[:MAX_CARACTERES]
    if not texto:
        raise ValueError('Escribe una pregunta.')
    if cliente is None:
        if modo_actual(usuario)[0] == 'ia':
            cliente = _cliente()
    elif not _estado_plan(usuario)[0]:
        cliente = None  # con cliente inyectado (pruebas) también se respeta el plan de la empresa
    if cliente is None:
        yield from _conversar_basico(usuario, conversacion_id, texto, inicio=True)
        return

    try:
        _consumir(usuario)
    except AsistenteNoDisponible as e:
        yield from _conversar_basico(usuario, conversacion_id, texto, inicio=True, motivo=str(e))  # sin bolsa o sin tope: sigue, pero en modo básico
        return
    emitio_texto = False
    try:
        for evento in _conversar(usuario, conversacion_id, texto, cliente):
            emitio_texto = emitio_texto or evento['t'] == 'texto'
            yield evento
    except anthropic.APIError as error:
        _devolver(usuario)  # falló el servicio: esa pregunta no cuenta
        if emitio_texto:
            raise  # ya se mostró media respuesta: se avisa del error
        motivo = _motivo_de(error)
        logger.warning('Aslani pasa a modo básico: %s (%s)', motivo, type(error).__name__)
        cache.set(CLAVE_IA_CAIDA, motivo, MINUTOS_IA_CAIDA * 60)  # no se insiste con la API durante unos minutos
        yield from _conversar_basico(usuario, conversacion_id, texto, inicio=False)
    except Exception:
        _devolver(usuario)
        raise


def _conversar_basico(usuario, conversacion_id, texto, inicio, motivo=None):
    from core.policies.services import asistente_basico  # import local: asistente_basico usa este módulo

    conversacion, previos = _abrir_conversacion(usuario, conversacion_id, texto)
    datos_modo = {'modo': 'basico', 'motivo': motivo} if motivo else _datos_modo(usuario)  # `motivo`: razón de plan o de tope, pública
    if inicio:
        yield {'t': 'inicio', 'conversacion': conversacion.pk, 'titulo': conversacion.titulo, 'cupo': cupo(usuario), **datos_modo}
    else:
        yield {'t': 'modo', **datos_modo}
    logger.info('Aslani (básico): %s preguntó «%s»', usuario.username, texto[:200])
    resp = asistente_basico.responder(usuario, texto, [m['content'] for m in previos[-6:]])
    yield {'t': 'texto', 'd': resp.texto}
    for accion in resp.acciones:
        yield {'t': 'accion', **accion}
    if resp.opciones:
        yield {'t': 'opciones', 'items': resp.opciones}
    consultas = [etiqueta_herramienta(n) for n in dict.fromkeys(resp.consultas)]
    _guardar(conversacion, texto, resp.texto, consultas)
    yield {'t': 'fin', 'conversacion': conversacion.pk, 'titulo': conversacion.titulo, 'consultas': consultas, 'cupo': cupo(usuario), **datos_modo}


def _conversar(usuario, conversacion_id, texto, cliente):
    conversacion, previos = _abrir_conversacion(usuario, conversacion_id, texto)
    logger.info('Aslani: %s preguntó «%s»', usuario.username, texto[:200])
    mensajes = list(previos)
    while mensajes and mensajes[0]['role'] != 'user':
        mensajes.pop(0)
    mensajes.append({'role': 'user', 'content': texto})

    yield {'t': 'inicio', 'conversacion': conversacion.pk, 'titulo': conversacion.titulo, 'cupo': cupo(usuario), 'modo': 'ia', 'motivo': None}

    herramientas = herramientas_para(usuario)
    usadas, trozos = [], []
    tokens = {'entrada': 0, 'salida': 0, 'leer': 0, 'escribir': 0, 'llamadas': 0}
    for vuelta in range(MAX_VUELTAS):
        if trozos and vuelta:
            yield {'t': 'texto', 'd': '\n\n'}
            trozos.append('\n\n')
        with cliente.beta.messages.stream(
            model=getattr(settings, 'ASISTENTE_MODELO', 'claude-sonnet-5-5'),
            max_tokens=4000,
            system=_instrucciones(),
            tools=herramientas,
            messages=mensajes,
            output_config={'effort': 'low'},  # consultas simples: poco razonamiento, respuesta rápida y barata
            betas=['server-side-fallback-2026-07-01'],
            fallbacks='default',
        ) as flujo:
            for delta in flujo.text_stream:
                trozos.append(delta)
                yield {'t': 'texto', 'd': delta}
            final = flujo.get_final_message()
        uso = getattr(final, 'usage', None)  # tokens REALES que cobró la API en esta llamada
        tokens['llamadas'] += 1
        for clave, atributo in (('entrada', 'input_tokens'), ('salida', 'output_tokens'), ('leer', 'cache_read_input_tokens'), ('escribir', 'cache_creation_input_tokens')):
            tokens[clave] += int(getattr(uso, atributo, 0) or 0)
        if final.stop_reason == 'refusal':
            trozos.append('No puedo responder esa consulta.')
            yield {'t': 'texto', 'd': 'No puedo responder esa consulta.'}
            break
        if final.stop_reason != 'tool_use':
            break
        mensajes.append({'role': 'assistant', 'content': final.content})  # incluye los bloques de razonamiento
        resultados = []
        for bloque in final.content:
            if bloque.type != 'tool_use':
                continue
            usadas.append(bloque.name)
            yield {'t': 'herramienta', 'n': bloque.name, 'etiqueta': etiqueta_herramienta(bloque.name)}
            salida, es_error, accion = ejecutar_herramienta(usuario, bloque.name, bloque.input)
            if accion:
                yield {'t': 'accion', **accion}
            resultados.append({'type': 'tool_result', 'tool_use_id': bloque.id, 'content': salida, 'is_error': es_error})
        mensajes.append({'role': 'user', 'content': resultados})
    else:
        mensaje = '\n\nLa consulta necesitó demasiados pasos. Intenta preguntar algo más puntual.'
        trozos.append(mensaje)
        yield {'t': 'texto', 'd': mensaje}

    respuesta = ''.join(trozos).strip() or 'No pude armar una respuesta; intenta de nuevo.'
    if not trozos:
        yield {'t': 'texto', 'd': respuesta}
    consultas = [etiqueta_herramienta(n) for n in dict.fromkeys(usadas)]
    _guardar(conversacion, texto, respuesta, consultas)
    modelo = getattr(settings, 'ASISTENTE_MODELO', 'claude-sonnet-5-5')
    AsistenteConsumo.objects.create(
        usuario=usuario, modelo=modelo, tokens_entrada=tokens['entrada'], tokens_salida=tokens['salida'], tokens_cache_lectura=tokens['leer'],
        tokens_cache_escritura=tokens['escribir'], llamadas=max(tokens['llamadas'], 1),
        costo_usd=round(costo_usd(modelo, tokens['entrada'], tokens['salida'], tokens['leer'], tokens['escribir']), 6))
    yield {'t': 'fin', 'conversacion': conversacion.pk, 'titulo': conversacion.titulo, 'consultas': consultas, 'cupo': cupo(usuario), 'modo': 'ia', 'motivo': None}  # esta respuesta SÍ fue con IA
