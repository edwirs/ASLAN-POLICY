"""Aslani en «modo básico»: respuestas guiadas, sin IA, para cuando el servicio de Claude no está disponible (falta la llave de la
API, la cuenta no tiene saldo o no hay conexión).

Entiende las preguntas más comunes por palabras clave y las contesta con los MISMOS datos y permisos que las herramientas del modo
con IA (siempre pasa por `ejecutar_herramienta`, que revisa el permiso del usuario). No inventa nada: si no entiende, ofrece opciones.
Es gratis (no consume el cupo diario) y sirve de red de seguridad.
"""
import json
import re
import unicodedata

from django.urls import reverse

from core.policies.models import Aseguradora
from core.policies.services.asistente import ejecutar_herramienta, etiqueta_herramienta

RE_PLACA = re.compile(r'\b([a-z]{3}\d{2}[a-z0-9])\b')
ALIAS_ASEGURADORAS = {
    'equidad': 'La Equidad Seguros', 'seguros del estado': 'Seguros del Estado', 'estado': 'Seguros del Estado', 'axa': 'AXA Colpatria',
    'colpatria': 'AXA Colpatria', 'mundial': 'Seguros Mundial', 'qualitas': 'Qualitas', 'hdi': 'HDI', 'mapfre': 'Mapfre',
    'allianz': 'Allianz', 'bolivar': 'Bolívar', 'sura': 'Sura',
}
MENU = ['¿Cómo van las cotizaciones este mes?', '¿Qué requiere mi atención hoy?', 'Muéstrame las últimas solicitudes',
        '¿Qué aseguradoras están activas?', '¿Cómo hago una nueva solicitud?']


def _norm(texto):
    sin = unicodedata.normalize('NFD', texto or '')
    return ''.join(c for c in sin if unicodedata.category(c) != 'Mn').lower()


def _tiene(t, *palabras):
    return any(p in t for p in palabras)


def _pesos(valor):
    try:
        return '$' + f'{int(round(float(valor))):,}'.replace(',', '.')
    except (TypeError, ValueError):
        return str(valor)


def _tabla(encabezados, filas):
    lineas = ['| ' + ' | '.join(encabezados) + ' |', '|' + '---|' * len(encabezados)]
    lineas += ['| ' + ' | '.join(str(c) for c in f) + ' |' for f in filas]
    return '\n'.join(lineas)


class _Respuesta:
    def __init__(self):
        self.texto, self.opciones, self.acciones, self.consultas = '', [], [], []


def _consultar(usuario, r, nombre, **args):
    """Corre una herramienta (con el permiso del usuario). Devuelve el dict, o None y deja el aviso en `r.texto`."""
    salida, es_error, accion = ejecutar_herramienta(usuario, nombre, args)
    datos = json.loads(salida)
    if nombre not in [c for c in r.consultas]:
        r.consultas.append(nombre)
    if accion:
        r.acciones.append(accion)
    if es_error or (isinstance(datos, dict) and datos.get('error')):
        r.texto = datos.get('error', 'No pude hacer esa consulta.')
        return None
    return datos


def _periodo(t):
    if _tiene(t, 'semana', ' 7 ', 'hoy', 'ultimos 7'):
        return 7
    if _tiene(t, 'trimestre', '90', '3 meses', 'tres meses'):
        return 90
    return 30


def _placa(t, mensajes_previos):
    m = RE_PLACA.search(t)
    if m:
        return m.group(1).upper()
    for previo in reversed(mensajes_previos or []):  # «¿y el comparativo?» → la placa de la que se venía hablando
        m = RE_PLACA.search(_norm(previo))
        if m:
            return m.group(1).upper()
    return None


def _aseguradora(t):
    for alias, nombre in sorted(ALIAS_ASEGURADORAS.items(), key=lambda kv: -len(kv[0])):
        if re.search(r'\b' + re.escape(alias) + r'\b', t):
            return nombre
    for nombre in Aseguradora.objects.values_list('name', flat=True):
        if _norm(nombre) in t:
            return nombre
    return None


# --- respuestas ---------------------------------------------------------------------------------------------------------------
def _resumen(usuario, r, dias):
    d = _consultar(usuario, r, 'resumen_cotizaciones', dias=dias)
    if d is None:
        return
    t = [f'**Resumen {d["periodo"]}**', '',
         f'- Solicitudes nuevas: **{d["solicitudes_nuevas"]}**', f'- Cotizaciones completadas: **{d["cotizaciones_completadas"]}**',
         f'- Con error: **{d["con_error"]}**', f'- Avisos del portal (ej. ya asegurado): **{d["avisos_del_portal"]}**']
    if d['tasa_exito_porcentaje'] is not None:
        t.append(f'- Tasa de éxito de los bots: **{d["tasa_exito_porcentaje"]}%**')
    if d['por_aseguradora']:
        t += ['', _tabla(['Aseguradora', 'Completadas', 'Avisos', 'Con error'],
                         [(a['aseguradora'], a['completadas'], a['avisos_del_portal'], a['con_error']) for a in d['por_aseguradora']])]
    t += ['', f'Más gráficas en el [panel]({d["enlace_panel"]}).']
    r.texto = '\n'.join(t)
    r.opciones = ['¿Qué requiere mi atención hoy?', 'Muéstrame las últimas solicitudes']


def _pendientes(usuario, r):
    d = _consultar(usuario, r, 'pendientes')
    if d is None:
        return
    t = ['**Esto es lo que requiere atención:**', '']
    hay = False
    for n in d.get('aseguradoras_que_piden_cambiar_contrasena', []):
        t.append(f'- 🔑 **{n}** pide cambiar la contraseña del portal.'); hay = True
    if d.get('cotizaciones_esperando_codigo_de_verificacion'):
        t.append(f'- 🛡️ **{d["cotizaciones_esperando_codigo_de_verificacion"]}** cotización(es) esperan un código de verificación.'); hay = True
    for i in d.get('aseguradoras_con_datos_de_acceso_incompletos', []):
        t.append(f'- ⚠️ **{i["nombre"]}**: faltan datos de acceso ({", ".join(i["faltan"])}).'); hay = True
    if not hay:
        t.append('- ✅ Nada pendiente: no hay contraseñas, códigos ni datos por completar.')
    if d.get('principales_causas_de_falla_30_dias'):
        t += ['', '**Principales causas de falla (30 días):**'] + [f'- {c["tipo"]}: {c["n"]}' for c in d['principales_causas_de_falla_30_dias']]
    if d.get('enlace_aseguradoras'):
        t += ['', f'Se arreglan en [Aseguradoras]({d["enlace_aseguradoras"]}).']
    r.texto = '\n'.join(t)
    r.opciones = ['¿Cómo van las cotizaciones este mes?', '¿Qué aseguradoras están activas?']


def _ultimas(usuario, r):
    d = _consultar(usuario, r, 'ultimas_solicitudes', cantidad=6)
    if d is None:
        return
    filas = [(s['placa'], s['tomador'], f'{s["aseguradoras_con_valor"]} de {s["aseguradoras_consultadas"]}', f'[comparativo]({s["enlace_comparativo"]})') for s in d['solicitudes']]
    r.texto = '**Últimas solicitudes:**\n\n' + (_tabla(['Placa', 'Tomador', 'Con valor', ''], filas) if filas else 'Aún no hay solicitudes.') + \
        f'\n\nTodas en [Solicitudes registradas]({d["enlace_listado"]}).'
    r.opciones = ['¿Qué requiere mi atención hoy?']


def _detalle(usuario, r, placa):
    d = _consultar(usuario, r, 'detalle_solicitud', placa=placa)
    if d is None:
        return
    v = d['vehiculo']
    cab = ' '.join(str(x) for x in (v.get('marca'), v.get('clase'), v.get('modelo')) if x)
    t = [f'**{d["placa"]}**' + (f' · {cab}' if cab else '') + f' · tomador: {d["tomador"]}' + (' · 0 km' if d['cero_km'] else ''), '']
    filas = []
    for c in d['cotizaciones_por_aseguradora']:
        if 'prima_destacada' in c:
            detalle = f'{_pesos(c["prima_destacada"])} ({c["que_prima_es"]})'
        else:
            detalle = c.get('que_paso') or c['estado']
            detalle = (detalle[:110] + '…') if len(detalle) > 110 else detalle
        filas.append((c['aseguradora'], c['estado'], detalle))
    t.append(_tabla(['Aseguradora', 'Estado', 'Valor o motivo'], filas) if filas else 'Todavía no se ha cotizado con ninguna aseguradora.')
    t += ['', f'[Ver comparativo de {d["placa"]}]({d["enlace_comparativo"]})']
    r.texto = '\n'.join(t)
    r.opciones = [f'¿Qué aseguradora quedó más barata en {d["placa"]}?']


def _comparativo(usuario, r, placa):
    d = _consultar(usuario, r, 'comparativo_de_placa', placa=placa)
    if d is None:
        return
    if not d['ranking_de_menor_a_mayor']:
        r.texto = f'Para **{d["placa"]}** todavía no hay valores para comparar.'
    else:
        filas = [(f['posicion'], f['aseguradora'], f['valor'], f['que_valor_es'], f['mas_que_el_mas_barato']) for f in d['ranking_de_menor_a_mayor']]
        mas_barata = d['ranking_de_menor_a_mayor'][0]
        r.texto = (f'La más barata para **{d["placa"]}** es **{mas_barata["aseguradora"]}** con **{mas_barata["valor"]}**.\n\n' +
                   _tabla(['#', 'Aseguradora', 'Valor', 'Qué valor es', 'Más que la más barata'], filas))
        if d['sin_valor']:
            r.texto += '\n\nSin valor: ' + '; '.join(f'{s["aseguradora"]} ({s["motivo"]})' for s in d['sin_valor']) + '.'
        r.texto += f'\n\n[Abrir el comparativo completo]({d["enlace_comparativo"]})'
    r.opciones = [f'Muéstrame el detalle de {d["placa"]}']


def _coberturas(usuario, r, aseguradora):
    d = _consultar(usuario, r, 'coberturas_de_aseguradora', aseguradora=aseguradora)
    if d is None:
        return
    t = []
    for ficha in d['fichas']:
        t.append(f'**{ficha["aseguradora"]} · {ficha["producto"]}**')
        t += [f'- {k}: {v}' for k, v in ficha['coberturas'].items()]
        t.append('')
    t.append(f'[Ver fichas de coberturas]({d["enlace"]})')
    r.texto = '\n'.join(t)


def _aseguradoras(usuario, r):
    d = _consultar(usuario, r, 'aseguradoras')
    if d is None:
        return
    filas = [(a['aseguradora'], 'Activa' if a['activa'] else 'Inactiva', 'Sí' if a['tiene_bot'] else 'No (valor manual)',
              '—' if a['datos_de_acceso_completos'] is None else ('Completos' if a['datos_de_acceso_completos'] else 'Faltan datos') + (' · pide cambiar contraseña' if a['pide_cambiar_contrasena'] else ''))
             for a in d['aseguradoras']]
    r.texto = '**Aseguradoras:**\n\n' + _tabla(['Aseguradora', 'Estado', 'Bot', 'Datos de acceso'], filas) + f'\n\nSe administran en [Aseguradoras]({d["enlace"]}).'
    r.opciones = ['¿Qué requiere mi atención hoy?']


def _asesores(usuario, r):
    d = _consultar(usuario, r, 'asesores')
    if d is None:
        return
    filas = [(a['nombre'], a['tipo'], a['empresa'] or '—', f'{a["comision_porcentaje"]:g} %', 'Activo' if a['activo'] else 'Inactivo') for a in d['asesores']]
    r.texto = '**Asesores:**\n\n' + (_tabla(['Nombre', 'Tipo', 'Empresa', 'Comisión', 'Estado'], filas) if filas else 'Aún no hay asesores registrados.') + f'\n\n[Ir a Asesores]({d["enlace"]})'


def _reenvio(usuario, r, placa, aseguradora):
    d = _consultar(usuario, r, 'proponer_reenvio', placa=placa, aseguradora=aseguradora)
    if d is None:
        return
    r.texto = f'Listo, preparé el reenvío de **{placa}** a **{aseguradora}**. **Confírmalo con el botón** de abajo; hasta entonces no se hace nada.'


def _guia(t):
    """Respuestas fijas a «¿cómo hago…?». Devuelve (texto, opciones) o None."""
    u = {k: reverse(v) for k, v in {'nueva': 'solicitud_cotizacion_create', 'lista': 'vehiculo_list', 'aseg': 'aseguradora_list', 'ases': 'asesor_list',
                                    'reg': 'vehiculo_registrado_list', 'panel': 'dashboard'}.items()}
    if _tiene(t, 'nueva solicitud', 'nueva cotizacion', 'cotizar un', 'hacer una cotizacion', 'crear una solicitud', 'como cotizo', 'como cotizar'):
        return (f'**Para cotizar un vehículo:**\n\n1. Ve a [Cotizador › Nueva solicitud]({u["nueva"]}).\n2. Escribe los datos del tomador y del vehículo (placa; si es 0 km, el código Fasecolda y el valor comercial).\n'
                '3. Elige las aseguradoras con las que quieres cotizar y pulsa **Cotizar**.\n4. Mira el avance en vivo; al terminar, abre el comparativo.', ['¿Cómo veo el comparativo?'])
    if _tiene(t, 'comparativo') and _tiene(t, 'como', 'donde'):
        return (f'**Para ver el comparativo:** entra a [Solicitudes registradas]({u["lista"]}) y pulsa el icono de la balanza en la fila de la placa. '
                'Ahí también puedes agregar los valores de las aseguradoras sin bot (Bolívar, Allianz, Sura) y descargar el PDF.', [])
    if _tiene(t, 'contrasena', 'clave', 'password') and _tiene(t, 'cambi', 'actualiz', 'vencid', 'expir', 'pide'):
        return (f'**Si una aseguradora pide cambiar la contraseña:**\n\n1. Entra al portal de esa aseguradora y cámbiala allí.\n2. Ve a [Aseguradoras]({u["aseg"]}), pulsa **editar** en esa aseguradora y escribe la contraseña nueva.\n'
                '3. Al guardar se desbloquea y puedes reenviar las cotizaciones.\n\nMientras tanto el sistema no intenta entrar a ese portal, para no arriesgar el bloqueo de la cuenta.', ['¿Qué requiere mi atención hoy?'])
    if _tiene(t, 'reenvi', 'reintent', 'volver a cotizar') :
        return (f'**Para reenviar una cotización que falló:** en [Solicitudes registradas]({u["lista"]}) pulsa **Ver proceso** y luego **Reenviar** en la aseguradora que falló. '
                'También puedes decirme algo como «reenvía BWF282 a HDI» y te preparo el botón para confirmar.', [])
    if _tiene(t, 'asesor') and _tiene(t, 'como', 'agreg', 'regist', 'crear'):
        return (f'**Para registrar un asesor:** ve a [Configuraciones › Asesores]({u["ases"]}) y pulsa **Nuevo Registro**. Elige si es interno o externo y fija su porcentaje de comisión.', [])
    if _tiene(t, 'vehiculos registrados', 'datos del vehiculo', 'motor', 'chasis', 'color'):
        return (f'Los datos de cada vehículo (motor, chasis, color, valor comercial…) están en [Vehículos registrados]({u["reg"]}); pulsa el **+** de la fila para ver todo.', [])
    if _tiene(t, 'mapfre') and _tiene(t, 'codigo', 'robot', 'captcha', 'sms'):
        return ('Mapfre pide marcar «No soy un robot» y un código de 6 dígitos que llega por SMS. Esa parte la hace una persona: el bot espera, y el código se escribe en la ventana '
                'que aparece en la plataforma. Todavía está en construcción.', [])
    return None


def responder(usuario, texto, mensajes_previos=None):
    """Devuelve un _Respuesta (texto en markdown, opciones, acciones propuestas y consultas usadas)."""
    r = _Respuesta()
    t = ' ' + re.sub(r'\s+', ' ', _norm(texto)).strip() + ' '
    placa, aseguradora = _placa(t, mensajes_previos), _aseguradora(t)
    sin_placa_explicita = RE_PLACA.search(t) is None

    if _tiene(t, 'reenvi', 'reintent', 'volver a cotizar', 'cotizar de nuevo') and not _tiene(t, 'como ', 'donde'):
        if placa and aseguradora:
            _reenvio(usuario, r, placa, aseguradora)
        else:
            r.texto = 'Para reenviar necesito la **placa** y la **aseguradora**. Por ejemplo: «reenvía BWF282 a HDI».'
        return r
    guia = _guia(t)
    if guia:
        r.texto, r.opciones = guia
        return r
    if _tiene(t, 'barata', 'barato', 'comparativ', 'ranking', 'mejor precio', 'mejor valor', 'menor valor', 'menor precio'):
        if placa:
            _comparativo(usuario, r, placa)
        else:
            r.texto = '¿De qué **placa** quieres el comparativo? Escríbela, por ejemplo «¿qué aseguradora quedó más barata en BWF282?».'
        return r
    if _tiene(t, 'cubre', 'cobertura', 'ampara', 'asistencia', 'grua', 'deducible') and aseguradora:
        _coberturas(usuario, r, aseguradora)
        return r
    if _tiene(t, 'cubre', 'cobertura') and not aseguradora:
        r.texto = '¿De qué aseguradora quieres conocer las coberturas? Por ejemplo: «¿qué cubre Qualitas?».'
        r.opciones = ['¿Qué cubre Qualitas?', '¿Qué cubre HDI?']
        return r
    if placa and (_tiene(t, 'fall', 'error', 'paso', 'por que', 'motivo') or not sin_placa_explicita or _tiene(t, 'estado', 'como va', 'detalle', 'busca', 'muestra')):
        _detalle(usuario, r, placa)
        return r
    if aseguradora and _tiene(t, 'fall', 'error', 'que paso', 'por que') and usuario.has_perm('policies.view_vehiculo'):
        from core.policies.models import Cotizacion  # import local: evita ciclo al cargar el módulo
        ultima = (Cotizacion.objects.select_related('vehiculo').filter(aseguradora__name=aseguradora, estado_bot='error').order_by('-id').first())
        if ultima:
            _detalle(usuario, r, ultima.vehiculo.placa)
            r.texto = f'La última falla de **{aseguradora}** fue con la placa **{ultima.vehiculo.placa}**:\n\n' + r.texto
            return r
    if _tiene(t, 'por que fall', 'que paso', 'fallo', 'fallaron', 'errores') :
        _pendientes(usuario, r)
        r.texto += '\n\nSi me dices la **placa**, te explico qué pasó con cada aseguradora.'
        return r
    if _tiene(t, 'atencion', 'pendiente', 'requiere', 'por hacer', 'urgente', 'contrasena', 'clave', 'alerta'):
        _pendientes(usuario, r)
        return r
    if _tiene(t, 'ultima', 'ultimo', 'reciente'):
        _ultimas(usuario, r)
        return r
    if _tiene(t, 'aseguradoras', 'activas', 'bots', 'bot '):
        _aseguradoras(usuario, r)
        return r
    if _tiene(t, 'asesor', 'comision'):
        _asesores(usuario, r)
        return r
    if _tiene(t, 'cotizacion', 'cuantas', 'resumen', 'como van', 'estadistic', 'exito', 'tasa', 'solicitudes', 'completad', 'mes', 'semana'):
        _resumen(usuario, r, _periodo(t))
        return r
    if _tiene(t, 'gracias', 'listo', 'perfecto', 'excelente', 'genial'):
        r.texto = '¡Con gusto! Aquí estoy para lo que necesites. 😊'
        return r
    if _tiene(t, 'adios', 'chao', 'hasta luego', 'nos vemos'):
        r.texto = '¡Hasta luego! Cuando quieras, aquí estoy.'
        return r
    if _tiene(t, ' hola', 'buenas', 'buenos dias', 'buenas tardes', 'buenas noches', ' hey', 'saludos', 'quien eres', 'que eres', 'tu nombre'):
        r.texto = ('¡Hola! Soy **Aslani**, el asistente de ASLAN. Ahora mismo estoy en **modo básico**: entiendo las preguntas más comunes y te respondo con los datos de la plataforma. '
                   '¿Qué quieres saber?')
        r.opciones = MENU
        return r
    if _tiene(t, 'ayuda', 'que puedes', 'que sabes', 'menu', 'opciones', 'que haces', 'como funcion'):
        r.texto = ('Puedo ayudarte con: **cifras de cotizaciones**, **qué requiere atención**, **últimas solicitudes**, **estado y comparativo de una placa**, '
                   '**coberturas de una aseguradora**, **aseguradoras y asesores**, y a **reenviar una cotización** que falló. También te explico cómo hacer algo en el sistema. ¿Por dónde empezamos?')
        r.opciones = MENU
        return r
    r.texto = 'No estoy segura de haber entendido 🤔. En este momento respondo preguntas puntuales; prueba con alguna de estas o escribe una **placa** para ver su estado:'
    r.opciones = MENU
    return r
