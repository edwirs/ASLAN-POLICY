"""Correo de cotización al cliente.

Arma el correo a partir de una plantilla (Configuraciones › Plantillas de correo): reemplaza las variables
({cliente}, {placa}…) y los bloques ({datos_vehiculo}, {comparativo}, {promocion}, {firma}) por HTML apto para
correo (tablas con estilos en línea: Gmail y Outlook ignoran las hojas de estilo), genera el PDF del comparativo con
el mismo diseño de «Imprimir» y lo envía por la cuenta SMTP de la plantilla, dejando el registro y el evento en el
historial del vehículo.
"""
import io
import os
import re
import smtplib
import socket
from datetime import date
from email.mime.image import MIMEImage
from html import escape
from html.parser import HTMLParser
from urllib.parse import unquote, urlsplit

from django.conf import settings
from django.contrib.staticfiles import finders
from django.core.exceptions import ValidationError
from django.core.files.base import ContentFile
from django.core.mail import EmailMultiAlternatives, get_connection
from django.core.mail.message import SafeMIMEMultipart
from django.core.validators import validate_email
from django.template.loader import render_to_string
from django.utils import timezone
from django.utils.html import strip_tags

from core.policies.models import CorreoEnviado, Cotizacion, FirmaCorreo, PlantillaCorreo, ValorExterno
from core.policies.services.bots.base import normalizar_texto
from core.policies.services.comparativo import construir, dinero, soat
from core.policies.services.polizas import registrar_evento

# (nombre, qué es) — se muestran como botones en el editor de la plantilla.
VARIABLES = (
    ('cliente', 'Nombre del cliente'),
    ('cliente_mayusculas', 'Nombre del cliente en MAYÚSCULAS'),
    ('placa', 'Placa'),
    ('vehiculo', 'Marca y referencia'),
    ('modelo', 'Modelo (año)'),
    ('vigencia', 'Vigencia de la póliza (p. ej. 2026-2027)'),
    ('correo_cliente', 'Correo del cliente'),
    ('empresa', 'Nombre de la empresa'),
    ('asesor', 'Nombre de quien envía'),
    ('correo_asesor', 'Correo de quien envía'),
    ('fecha', 'Fecha de hoy'),
)
BLOQUES = (
    ('datos_vehiculo', 'Datos del vehículo', 'fa-solid fa-car'),
    ('comparativo', 'Comparativo de valores', 'fa-solid fa-table-list'),
    ('promocion', 'Promoción', 'fa-solid fa-bullhorn'),
    ('firma', 'Firma de quien envía', 'fa-solid fa-signature'),
)
# En «Para» y «CC» solo se aceptan correos o estas variables.
VARIABLES_CORREO = ('correo_cliente', 'correo_asesor')

# Las tablas van compactas y centradas (el texto sí ocupa todo el ancho del correo).
ANCHO_TABLAS = 600
ANCHO_PROMOCION = 110  # la imagen de la promoción (logo) va pequeña
# Colores del comparativo (comparativo.css), para que el correo se vea como el «Ranking de valores».
TEXTO = '#0f172a'
GRIS = '#64748b'
BORDE = '#e2e8f0'
BORDE_FUERTE = '#cbd5e1'
SUPERFICIE = '#f8fafc'
ACENTO = '#0891b2'
VERDE = '#15803d'
VERDE_SUAVE = '#ecf8f0'
DORADO = '#d97706'
NARANJA = '#f26a21'
FUENTE = 'Arial, Helvetica, sans-serif'


class CorreoError(Exception):
    """Error con un mensaje que se le puede mostrar al asesor tal cual."""


# ---------------------------------------------------------------------------------------------------------------
# Limpieza del cuerpo (lo que sale del editor de la plantilla)
# ---------------------------------------------------------------------------------------------------------------
_ETIQUETAS = {'p', 'br', 'div', 'span', 'b', 'strong', 'i', 'em', 'u', 'ul', 'ol', 'li', 'a', 'h2', 'h3', 'h4', 'font', 'hr'}
_VACIAS = {'br', 'hr'}
_ESTILOS = {'color', 'background-color', 'text-align', 'font-weight', 'font-style', 'text-decoration', 'font-size'}


class _Limpiador(HTMLParser):
    """Deja solo formato básico (negrita, listas, colores, alineación, enlaces). Descarta scripts, estilos, imágenes
    pegadas y cualquier atributo que no sea de formato."""

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.salida, self.abiertas, self.ignorar = [], [], 0

    def handle_starttag(self, tag, attrs):
        if tag in ('script', 'style', 'head', 'title'):
            self.ignorar += 1
            return
        if self.ignorar or tag not in _ETIQUETAS:
            return
        atributos = []
        for nombre, valor in attrs:
            valor = valor or ''
            if nombre == 'style':
                limpio = _estilo_permitido(valor)
                if limpio:
                    atributos.append(f'style="{escape(limpio)}"')
            elif nombre == 'href' and tag == 'a' and re.match(r'^(https?:|mailto:)', valor.strip(), re.I):
                atributos.append(f'href="{escape(valor.strip())}"')
            elif nombre == 'color' and tag == 'font' and re.match(r'^#?[\w]+$', valor):
                atributos.append(f'color="{escape(valor)}"')
        self.salida.append(f'<{tag}{"".join(" " + a for a in atributos)}>')
        if tag not in _VACIAS:
            self.abiertas.append(tag)

    def handle_endtag(self, tag):
        if tag in ('script', 'style', 'head', 'title'):
            self.ignorar = max(0, self.ignorar - 1)
            return
        if self.ignorar or tag not in _ETIQUETAS or tag in _VACIAS or tag not in self.abiertas:
            return
        while self.abiertas:
            abierta = self.abiertas.pop()
            self.salida.append(f'</{abierta}>')
            if abierta == tag:
                break

    def handle_data(self, data):
        if not self.ignorar:
            self.salida.append(escape(data, quote=False))

    def resultado(self):
        self.close()
        return ''.join(self.salida) + ''.join(f'</{t}>' for t in reversed(self.abiertas))


def _estilo_permitido(estilo):
    partes = []
    for declaracion in estilo.split(';'):
        propiedad, _, valor = declaracion.partition(':')
        propiedad, valor = propiedad.strip().lower(), valor.strip()
        if propiedad in _ESTILOS and valor and not re.search(r'url\(|expression|[<>"]', valor, re.I):
            partes.append(f'{propiedad}: {valor}')
    return '; '.join(partes)


def limpiar_cuerpo(html):
    limpiador = _Limpiador()
    limpiador.feed(html or '')
    return limpiador.resultado().strip()


# ---------------------------------------------------------------------------------------------------------------
# Imágenes (firmas y promociones): siempre PNG. Outlook no muestra WebP y una foto enorme hace pesado el correo.
# ---------------------------------------------------------------------------------------------------------------
ANCHO_MAXIMO_IMAGEN = 1400


def normalizar_imagen(archivo, nombre='imagen'):
    """Convierte la imagen subida a PNG de máximo ANCHO_MAXIMO_IMAGEN px. Lanza ValidationError si no es una imagen."""
    from PIL import Image, UnidentifiedImageError
    try:
        imagen = Image.open(archivo)
        imagen.load()
    except (UnidentifiedImageError, OSError):
        raise ValidationError('El archivo no es una imagen válida (use PNG, JPG o WebP).')
    if imagen.mode not in ('RGB', 'RGBA'):
        imagen = imagen.convert('RGBA')
    if imagen.width > ANCHO_MAXIMO_IMAGEN:
        alto = round(imagen.height * ANCHO_MAXIMO_IMAGEN / imagen.width)
        imagen = imagen.resize((ANCHO_MAXIMO_IMAGEN, alto), Image.LANCZOS)
    salida = io.BytesIO()
    imagen.save(salida, format='PNG', optimize=True)
    return ContentFile(salida.getvalue(), name=f'{nombre}.png')


# ---------------------------------------------------------------------------------------------------------------
# Datos del correo
# ---------------------------------------------------------------------------------------------------------------
def _empresa():
    from core.policies.views.comparativo.views import datos_empresa  # import local: la vista importa servicios
    return datos_empresa() or {}


def _poliza_actual(vehiculo):
    """La póliza más reciente del vehículo (vigente o la última que tuvo)."""
    return (vehiculo.polizas.filter(estado='generada').select_related('aseguradora')
            .order_by('-fecha_renovacion', '-id').first())


def _zona(municipio):
    if municipio is None:
        return ''
    nombre = re.sub(r'\bd\.\s*c\.?', 'D.C.', municipio.nombre, flags=re.I)
    departamento = getattr(municipio, 'departamento', None)
    if departamento is None or normalizar_texto(departamento.nombre)[:5] == normalizar_texto(municipio.nombre)[:5]:
        return nombre
    return f'{nombre}, {departamento.nombre}'


def _nombre_usuario(usuario):
    return (getattr(usuario, 'names', '') or '').strip() or getattr(usuario, 'username', '')


def valores(vehiculo, usuario):
    """Valor de cada variable para este vehículo y quien envía."""
    tomador = vehiculo.tomador
    poliza = _poliza_actual(vehiculo)
    base = poliza.fecha_renovacion if poliza and poliza.fecha_renovacion >= timezone.localdate() else timezone.localdate()
    nombre = (tomador.names or '').strip()
    return {
        'cliente': nombre,
        'cliente_mayusculas': nombre.upper(),
        'placa': vehiculo.placa,
        'vehiculo': ' '.join(x for x in (vehiculo.marca, vehiculo.referencia) if x),
        'modelo': str(vehiculo.modelo or ''),
        'vigencia': f'{base.year}-{base.year + 1}',
        'correo_cliente': ', '.join(c.strip() for c in (tomador.email, tomador.email_secundario) if c and c.strip()),
        'empresa': _empresa().get('nombre', ''),
        'asesor': _nombre_usuario(usuario),
        'correo_asesor': (getattr(usuario, 'email', '') or '').strip(),
        'fecha': timezone.localdate().strftime('%d/%m/%Y'),
    }


def reemplazar(texto, datos, html=True):
    """Cambia {variable} por su valor (escapado si es HTML). Lo que no es una variable conocida queda igual."""
    def cambio(m):
        if m.group(1) not in datos:
            return m.group(0)
        valor = datos[m.group(1)]
        return escape(valor) if html else valor
    return re.sub(r'\{(\w+)\}', cambio, texto or '')


def destinatarios(texto, datos):
    """«{correo_cliente}, otro@x.com» -> lista de correos válidos (sin repetidos). Lanza CorreoError si alguno no sirve."""
    correos = []
    for parte in re.split(r'[,;\s]+', reemplazar(texto, datos, html=False)):
        parte = parte.strip()
        if not parte:
            continue
        try:
            validate_email(parte)
        except ValidationError:
            raise CorreoError(f'«{parte}» no es un correo válido.')
        if parte.lower() not in [c.lower() for c in correos]:
            correos.append(parte)
    return correos


# ---------------------------------------------------------------------------------------------------------------
# Bloques
# ---------------------------------------------------------------------------------------------------------------
def _tarjeta(eyebrow, titulo, contenido, subtitulo=''):
    """Marco de tarjeta como las del comparativo: borde suave, esquinas redondeadas y encabezado con «eyebrow»."""
    sub = (f'<div style="font-family:{FUENTE};font-size:11px;line-height:1.45;color:{GRIS};margin-top:3px;">{subtitulo}</div>') if subtitulo else ''
    titulo = (f'<div style="font-family:{FUENTE};font-size:14px;font-weight:bold;color:{TEXTO};margin-top:1px;">{titulo}</div>') if titulo else ''
    return (
        f'<table role="presentation" align="center" width="100%" cellpadding="0" cellspacing="0" style="border-collapse:separate;'
        f'width:100%;max-width:{ANCHO_TABLAS}px;margin:0 auto;border:1px solid {BORDE};border-radius:12px;background:#ffffff;">'
        f'<tr><td style="padding:10px 12px 8px;border-bottom:1px solid {BORDE};">'
        f'<div style="font-family:{FUENTE};font-size:9px;font-weight:bold;letter-spacing:1.1px;text-transform:uppercase;color:{ACENTO};">{eyebrow}</div>'
        f'{titulo}{sub}</td></tr>'
        f'<tr><td style="padding:0;">{contenido}</td></tr></table>'
    )


def _dato(etiqueta, valor, borde=''):
    return (f'<td valign="top" width="33%" style="padding:6px 12px;font-family:{FUENTE};{borde}">'
            f'<div style="font-size:9px;font-weight:bold;letter-spacing:.7px;text-transform:uppercase;color:{GRIS};">{escape(etiqueta)}</div>'
            f'<div style="font-size:12px;font-weight:bold;color:{TEXTO};margin-top:1px;">{escape(valor)}</div></td>')


def bloque_datos_vehiculo(vehiculo, actual=None):
    """`actual`: aseguradora con la que el vehículo está asegurado hoy (`construir` ya decidió entre el aviso más reciente de
    un portal y la póliza registrada). Las fechas y la prima solo se muestran si la póliza registrada es de esa aseguradora."""
    poliza = _poliza_actual(vehiculo)
    if actual and poliza and poliza.aseguradora.name != actual:
        poliza = None  # el portal avisó después que el vehículo está con otra aseguradora: esa póliza ya no es la actual
    hoy = timezone.localdate()
    pares = [
        ('Placa', vehiculo.placa),
        ('Modelo', str(vehiculo.modelo or '')),
        ('Código Fasecolda', vehiculo.codigo_fasecolda or ''),
        ('Tomador', (vehiculo.tomador.names or '').upper()),
        ('Zona de circulación', _zona(vehiculo.zona_circulacion)),
        ('Valor asegurado', dinero(vehiculo.valor_comercial) if vehiculo.valor_comercial else ''),
    ]
    if poliza:
        dias = (poliza.fecha_renovacion - hoy).days
        pares += [
            ('Aseguradora actual', poliza.aseguradora.name),
            ('Fecha de vigencia', poliza.fecha_renovacion.strftime('%d/%m/%Y')),
            ('Días de vigencia', f'{dias} días' if dias >= 0 else 'Vencida'),
            ('Valor prima actual', dinero(poliza.prima_total) if poliza.prima_total else ''),
        ]
    elif actual:
        pares.append(('Aseguradora actual', actual))
    datos_soat = soat(vehiculo, hoy)
    if datos_soat:
        pares += [('Valor SOAT', datos_soat['valor_fmt']), ('Días de vigencia SOAT', datos_soat['dias_texto'])]
    pares = [(t, v) for t, v in pares if v]
    filas = []
    for i in range(0, len(pares), 3):
        borde = f'border-top:1px solid {BORDE};' if i else ''  # en las celdas: no todos los clientes pintan bordes de <tr>
        grupo = pares[i:i + 3]
        celdas = ''.join(_dato(t, v, borde) for t, v in grupo) + f'<td width="33%" style="{borde}"></td>' * (3 - len(grupo))
        filas.append(f'<tr>{celdas}</tr>')
    rejilla = ''.join(filas)
    contenido = (f'<table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="border-collapse:collapse;width:100%;">'
                 f'{rejilla}</table>')
    titulo = escape(' '.join(x for x in (vehiculo.marca, vehiculo.referencia) if x) or vehiculo.placa)
    return _tarjeta('Vehículo', titulo, contenido)


def _posicion(numero, mejor):
    fondo, color, borde = (DORADO, '#ffffff', DORADO) if mejor else (SUPERFICIE, GRIS, BORDE)
    return (f'<span style="display:inline-block;width:20px;height:20px;line-height:20px;border-radius:10px;text-align:center;'
            f'font-family:{FUENTE};font-size:10px;font-weight:bold;background:{fondo};color:{color};border:1px solid {borde};">'
            f'{"★" if mejor else numero}</span>')


def _barra(porcentaje, mejor):
    return (f'<div style="width:100%;max-width:80px;height:3px;background:{BORDE};border-radius:3px;margin:3px 0 0 auto;font-size:0;line-height:0;">'
            f'<div style="width:{porcentaje}%;height:3px;background:{VERDE if mejor else ACENTO};border-radius:3px;font-size:0;line-height:0;"></div></div>')


def bloque_comparativo(vehiculo, plantilla, filas=None):
    """Ranking de valores (la aseguradora actual del vehículo va en la tarjeta de datos del vehículo, no aquí)."""
    filas = construir(vehiculo)['filas'] if filas is None else filas
    if not filas:
        return (f'<p style="font-family:{FUENTE};font-size:13px;color:{GRIS};margin:0;">'
                f'Todavía no hay valores de aseguradoras para este vehículo.</p>')
    asegurados = dict(Cotizacion.objects.filter(pk__in=[f['cotizacion_id'] for f in filas if f['cotizacion_id']])
                      .values_list('pk', 'valor_asegurado'))
    comercial = vehiculo.valor_comercial
    th = (f'style="background:{SUPERFICIE};font-family:{FUENTE};font-size:9px;font-weight:bold;text-transform:uppercase;'
          f'letter-spacing:.5px;color:{GRIS};padding:6px 8px;border-bottom:2px solid {BORDE_FUERTE};"')
    cuerpo = []
    ultima = len(filas) - 1
    for i, f in enumerate(filas):
        mejor = f['posicion'] == 1
        fondo = VERDE_SUAVE if mejor else '#ffffff'
        borde = '' if i == ultima else f'border-bottom:1px solid {BORDE};'
        td = f'font-family:{FUENTE};padding:6px 8px;background:{fondo};{borde}vertical-align:middle;'
        asegurado = asegurados.get(f['cotizacion_id']) or comercial
        diferencia = (f'<span style="color:{VERDE};font-weight:bold;">—</span>' if mejor else
                      f'+{f["diferencia_fmt"]}<br><span style="font-size:10px;color:{GRIS};">'
                      f'{str(round(f["diferencia_pct"], 1)).replace(".", ",")}% más</span>')
        cuerpo.append(
            f'<tr><td align="center" width="32" style="{td}">{_posicion(f["posicion"], mejor)}</td>'
            f'<td style="{td}"><span style="font-size:12px;font-weight:bold;color:{TEXTO};">{escape(f["aseguradora"])}</span>'
            f'<br><span style="font-size:11px;color:{GRIS};">{escape(f["etiqueta"])}</span></td>'
            f'<td align="right" style="{td}white-space:nowrap;"><span style="font-size:13px;font-weight:bold;color:{VERDE if mejor else TEXTO};">'
            f'{f["valor_fmt"]}</span>{_barra(f["barra"], mejor)}</td>'
            f'<td align="right" class="solo-ancho" style="{td}font-size:12px;color:{TEXTO};white-space:nowrap;">{diferencia}</td>'
            f'<td align="right" class="solo-ancho" style="{td}font-size:12px;color:{TEXTO};white-space:nowrap;">{dinero(asegurado) if asegurado else "—"}</td></tr>')
    dias = plantilla.vigencia_cotizacion_dias if plantilla else 15
    tabla = (
        f'<table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="border-collapse:separate;border-spacing:0;width:100%;">'
        f'<tr><td {th} align="center">#</td><td {th}>Aseguradora</td><td {th} align="right">Valor prima</td>'
        f'<td {th} align="right" class="solo-ancho">Diferencia</td><td {th} align="right" class="solo-ancho">Valor asegurado</td></tr>'
        f'{"".join(cuerpo)}</table>'
    )
    subtitulo = (f'<span style="display:inline-block;background:#e6f6fa;color:{ACENTO};font-weight:bold;padding:1px 7px;border-radius:8px;'
                 f'white-space:nowrap;font-size:10px;">Cotizaciones con vigencia de {dias} días</span>')
    return (_tarjeta('Comparativo de seguros', '', tabla, subtitulo) +
            f'<p style="font-family:{FUENTE};font-size:10px;color:{GRIS};max-width:{ANCHO_TABLAS}px;margin:5px auto 0;text-align:center;">Valores en pesos colombianos (COP). '
            f'El detalle de coberturas, deducibles y asistencias de cada aseguradora va en el PDF adjunto.</p>')


def _imagen(src, alto_texto, ancho=600):
    return (f'<img src="{src}" alt="{escape(alto_texto)}" width="{ancho}" style="display:block;width:100%;max-width:{ancho}px;'
            f'height:auto;border:0;">')


def promocion_visible(plantilla, filas):
    if not plantilla or not plantilla.promocion_activa or not (plantilla.promocion_texto or plantilla.promocion_imagen):
        return False
    return plantilla.promocion_aseguradora_id is None or plantilla.promocion_aseguradora.name in {f['aseguradora'] for f in filas}


def bloque_promocion(plantilla, filas, src):
    if not promocion_visible(plantilla, filas):
        return ''
    # Imagen pequeña arriba y el texto debajo, los dos centrados (tabla con align: Outlook ignora margin:auto).
    partes = []
    if plantilla.promocion_imagen and src:
        partes.append(f'<tr><td align="center" style="padding:0 0 6px;"><img src="{src}" alt="{escape(plantilla.promocion_texto or "Promoción")}" '
                      f'width="{ANCHO_PROMOCION}" style="display:block;margin:0 auto;width:{ANCHO_PROMOCION}px;max-width:100%;height:auto;border:0;"></td></tr>')
    if plantilla.promocion_texto:
        partes.append(f'<tr><td align="center" style="font-family:{FUENTE};font-size:14px;font-weight:bold;color:{TEXTO};text-align:center;">'
                      f'{escape(plantilla.promocion_texto)}</td></tr>')
    return (f'<table role="presentation" align="center" width="100%" cellpadding="0" cellspacing="0" '
            f'style="border-collapse:collapse;width:100%;">{"".join(partes)}</table>')


def bloque_firma(usuario, src):
    if src:
        return _imagen(src, f'Firma de {_nombre_usuario(usuario)}', 600)
    empresa = _empresa()
    lineas = [f'<b style="color:{TEXTO};font-size:15px;">{escape(_nombre_usuario(usuario))}</b>']
    for dato in (empresa.get('nombre'), getattr(usuario, 'email', ''), ' · '.join(empresa.get('telefonos', [])), empresa.get('sitio_texto')):
        if dato:
            lineas.append(escape(dato))
    return (f'<p style="font-family:{FUENTE};font-size:13px;color:{TEXTO};margin:0;border-left:3px solid {NARANJA};'
            f'padding-left:10px;">{"<br>".join(lineas)}</p>')


def firma_de(usuario):
    return FirmaCorreo.objects.filter(usuario=usuario).first() if getattr(usuario, 'pk', None) else None


# ---------------------------------------------------------------------------------------------------------------
# Armar
# ---------------------------------------------------------------------------------------------------------------
def _poner_bloques(html, bloques):
    """Un bloque solo en su párrafo reemplaza el párrafo completo (una tabla no puede ir dentro de un <p>)."""
    for nombre, contenido in bloques.items():
        envoltura = f'<div style="margin:0 0 16px;">{contenido}</div>' if contenido else ''
        html = re.sub(r'<(p|div)\b[^>]*>\s*(?:<br\s*/?>\s*)*\{' + nombre + r'\}\s*(?:<br\s*/?>\s*)*</\1>', lambda m: envoltura, html)
        html = html.replace('{' + nombre + '}', contenido)
    return html


def _estilo_parrafos(html):
    return re.sub(r'<p(?: style="([^"]*)")?>',
                  lambda m: f'<p style="margin:0 0 12px;{(m.group(1) + ";") if m.group(1) else ""}">', html)


def plantilla_para(vehiculo, plantilla_id=None):
    """La plantilla pedida (si está activa) o la predeterminada de autos."""
    activas = PlantillaCorreo.objects.filter(is_active=True, tipo_seguro='autos').select_related('cuenta', 'promocion_aseguradora')
    if plantilla_id:
        elegida = activas.filter(pk=plantilla_id).first()
        if elegida:
            return elegida
    return activas.order_by('-predeterminada', 'nombre').first()


# Al cliente se le adjuntan las cotizaciones (PDF de la aseguradora) de los primeros del ranking.
MAS_BARATAS = 2
PDF_MAXIMO_MB = 10


def cotizaciones_a_adjuntar(filas):
    """Los MAS_BARATAS primeros del ranking y su PDF. Los valores manuales (cotizados por el asesor o por un externo)
    llevan el PDF que sube el asesor; los de bot, el que el bot descargó del portal (o el que suba el asesor si no pudo).
    `tipo` + `ref_id` identifican de dónde es el PDF: 'manual' = ValorExterno, 'bot' = Cotizacion."""
    primeras = filas[:MAS_BARATAS]
    manuales = {v.pk: v.documento for v in ValorExterno.objects.filter(pk__in=[f['valor_externo_id'] for f in primeras if f.get('valor_externo_id')])}
    portal = {c.pk: c.pdf for c in Cotizacion.objects.filter(pk__in=[f['cotizacion_id'] for f in primeras if f.get('cotizacion_id')])}
    resultado = []
    for fila in primeras:
        manual = fila['origen'] == 'manual'
        ref_id = fila.get('valor_externo_id') if manual else fila.get('cotizacion_id')
        documento = (manuales if manual else portal).get(ref_id)
        resultado.append({
            'posicion': fila['posicion'],
            'aseguradora': fila['aseguradora'],
            'valor_fmt': fila['valor_fmt'],
            'manual': manual,
            'tipo': 'manual' if manual else 'bot',
            'ref_id': ref_id,
            'valor_externo_id': fila.get('valor_externo_id'),
            'tiene_pdf': bool(documento),
            'archivo': f'Cotización {fila["aseguradora"]}.pdf',
            'documento': documento or None,
        })
    return resultado


def leer_pdf_subido(archivo):
    """Valida que el archivo subido sea un PDF de tamaño razonable. Lanza CorreoError si no."""
    if archivo is None:
        raise CorreoError('Seleccione el PDF de la cotización.')
    if archivo.size > PDF_MAXIMO_MB * 1024 * 1024:
        raise CorreoError(f'El PDF pesa más de {PDF_MAXIMO_MB} MB: comprímalo o pida uno más liviano.')
    inicio = archivo.read(5)
    archivo.seek(0)
    if inicio != b'%PDF-':
        raise CorreoError('El archivo no es un PDF.')
    return archivo


def armar(plantilla, vehiculo, usuario, para_envio=False):
    """Correo listo para revisar o enviar:
    {'de', 'para', 'cc', 'asunto', 'html', 'texto', 'imagenes': [(cid, ruta, nombre)], 'avisos': [...], 'adjunto'}.
    Con `para_envio` las imágenes van incrustadas (cid:); si no, con su URL para la vista previa."""
    datos = valores(vehiculo, usuario)
    resultado = construir(vehiculo)
    filas, actual = resultado['filas'], resultado['actual']
    imagenes = []

    def fuente(campo_imagen, cid):
        if not campo_imagen:
            return None
        if para_envio:
            imagenes.append((cid, campo_imagen.path, f'{cid}.png'))
            return f'cid:{cid}'
        return campo_imagen.url

    firma = firma_de(usuario)
    bloques = {
        'datos_vehiculo': bloque_datos_vehiculo(vehiculo, actual),
        'comparativo': bloque_comparativo(vehiculo, plantilla, filas),
        'promocion': bloque_promocion(plantilla, filas, fuente(plantilla.promocion_imagen, 'promocion') if promocion_visible(plantilla, filas) else None),
        'firma': bloque_firma(usuario, fuente(firma.imagen if firma else None, 'firma')),
    }
    cuerpo = _estilo_parrafos(reemplazar(plantilla.cuerpo, datos))
    cuerpo = _poner_bloques(cuerpo, bloques)
    html = render_to_string('plantilla_correo/correo.html', {'cuerpo': cuerpo, 'fuente': FUENTE, 'color': TEXTO})

    avisos = []
    cuenta = plantilla.cuenta
    if cuenta is None:
        avisos.append('La plantilla no tiene cuenta de envío: configúrela en Configuraciones › Plantillas de correo.')
    elif not cuenta.is_active:
        avisos.append(f'La cuenta de envío «{cuenta.nombre}» está inactiva.')
    elif not cuenta.clave:
        avisos.append(f'La cuenta «{cuenta.nombre}» no tiene contraseña registrada.')
    if not datos['correo_cliente'] and '{correo_cliente}' in plantilla.para:
        avisos.append('El cliente no tiene correo registrado: escríbalo en «Para».')
    if not filas:
        avisos.append('El comparativo todavía no tiene valores de aseguradoras.')
    cotizaciones = cotizaciones_a_adjuntar(filas)
    faltan = [c['aseguradora'] for c in cotizaciones if not c['tiene_pdf']]
    if faltan:
        avisos.append(f'Falta adjuntar el PDF de la cotización de {" y ".join(faltan)} (está entre las {MAS_BARATAS} más baratas).')
    if firma is None and '{firma}' in plantilla.cuerpo:
        avisos.append('No ha subido su firma: el correo lleva una firma de texto (súbala en Configuraciones › Plantillas de correo).')

    def lista(texto):
        try:
            return destinatarios(texto, datos)
        except CorreoError as e:
            avisos.append(str(e))
            return []

    return {
        'de': cuenta.remitente if cuenta else '',
        'para': lista(plantilla.para),
        'cc': lista(plantilla.cc),
        'asunto': reemplazar(plantilla.asunto, datos, html=False),
        'html': html,
        'texto': _texto_plano(cuerpo),
        'imagenes': imagenes,
        'avisos': avisos,
        'adjunto': f'Comparativo {vehiculo.placa}.pdf' if plantilla.adjuntar_pdf else '',
        'cotizaciones': cotizaciones,
    }


def _texto_plano(html):
    html = re.sub(r'<br\s*/?>', '\n', html)
    html = re.sub(r'</(p|div|tr|h\d|li)>', '\n', html)
    html = re.sub(r'</td>', '  ', html)
    texto = strip_tags(html)
    return re.sub(r'\n{3,}', '\n\n', '\n'.join(linea.strip() for linea in texto.splitlines())).strip()


# ---------------------------------------------------------------------------------------------------------------
# PDF del comparativo (el mismo diseño de «Imprimir», generado por Chromium en el servidor)
# ---------------------------------------------------------------------------------------------------------------
_ORIGEN_PDF = 'http://comparativo.pdf'


def _archivo_local(ruta):
    """Ruta en disco de un /static/… o /media/… (None si no existe o se sale de la carpeta)."""
    if ruta.startswith(settings.STATIC_URL):
        relativa = ruta[len(settings.STATIC_URL):]
        encontrado = finders.find(relativa)
        if encontrado:
            return encontrado if isinstance(encontrado, str) else encontrado[0]
        base = settings.STATIC_ROOT
    elif ruta.startswith(settings.MEDIA_URL):
        relativa, base = ruta[len(settings.MEDIA_URL):], settings.MEDIA_ROOT
    else:
        return None
    if not base:
        return None
    completa = os.path.realpath(os.path.join(base, relativa))
    if completa.startswith(os.path.realpath(base) + os.sep) and os.path.isfile(completa):
        return completa
    return None


def html_a_pdf(html):
    from playwright.sync_api import sync_playwright

    def servir(route):
        url = route.request.url
        if url.startswith(_ORIGEN_PDF):
            ruta = unquote(urlsplit(url).path)
            if ruta in ('', '/'):
                return route.fulfill(body=html, content_type='text/html; charset=utf-8')
            archivo = _archivo_local(ruta)
            return route.fulfill(path=archivo) if archivo else route.abort()
        if 'fonts.googleapis.com' in url or 'fonts.gstatic.com' in url:
            return route.continue_()
        return route.abort()

    with sync_playwright() as playwright:
        navegador = playwright.chromium.launch(headless=True)
        try:
            pagina = navegador.new_page()
            pagina.route('**/*', servir)
            try:
                pagina.goto(_ORIGEN_PDF + '/', wait_until='networkidle', timeout=30000)
            except Exception:
                pagina.wait_for_load_state('load')  # sin internet las fuentes no cargan: se usa la del sistema
            return pagina.pdf(print_background=True, prefer_css_page_size=True)
        finally:
            navegador.close()


def pdf_comparativo(request, vehiculo, solo_diferencias=False):
    from core.policies.views.comparativo.views import ComparativoImprimirView  # import local: evita ciclo
    vista = ComparativoImprimirView()
    vista.setup(request, pk=vehiculo.pk)
    contexto = vista.get_context_data(pk=vehiculo.pk)
    contexto.update({'solo_diferencias': solo_diferencias, 'para_pdf': True})
    return html_a_pdf(render_to_string(vista.template_name, contexto, request=request))


# ---------------------------------------------------------------------------------------------------------------
# Envío
# ---------------------------------------------------------------------------------------------------------------
class _CorreoConImagenes(EmailMultiAlternatives):
    """Correo HTML con imágenes incrustadas (multipart/related): el cliente ve la firma y la promoción sin tener que
    pulsar «mostrar imágenes»."""

    def __init__(self, *args, imagenes=(), **kwargs):
        super().__init__(*args, **kwargs)
        self.imagenes = list(imagenes)

    def _create_alternatives(self, msg):
        msg = super()._create_alternatives(msg)
        if not self.imagenes:
            return msg
        relacionado = SafeMIMEMultipart(_subtype='related', encoding=self.encoding)
        relacionado.attach(msg)
        for cid, ruta, nombre in self.imagenes:
            with open(ruta, 'rb') as archivo:
                imagen = MIMEImage(archivo.read())
            imagen.add_header('Content-ID', f'<{cid}>')
            imagen.add_header('Content-Disposition', 'inline', filename=nombre)
            relacionado.attach(imagen)
        return relacionado


def conexion(cuenta):
    return get_connection(
        'django.core.mail.backends.smtp.EmailBackend', host=cuenta.servidor, port=cuenta.puerto,
        username=cuenta.usuario or cuenta.correo, password=cuenta.clave,
        use_tls=cuenta.seguridad == 'tls', use_ssl=cuenta.seguridad == 'ssl', timeout=30, fail_silently=False)


def explicar_error_smtp(error, cuenta):
    if isinstance(error, smtplib.SMTPAuthenticationError):
        return ('El servidor de correo rechazó el usuario o la contraseña. En Google Workspace se usa una «contraseña de '
                'aplicación» (Cuenta de Google › Seguridad › Verificación en dos pasos › Contraseñas de aplicaciones), '
                'no la contraseña normal.')
    if isinstance(error, smtplib.SMTPRecipientsRefused):
        return 'El servidor de correo rechazó los destinatarios: revise los correos de «Para» y «CC».'
    if isinstance(error, smtplib.SMTPSenderRefused):
        return f'El servidor no deja enviar como {cuenta.correo}: revise que el usuario sea el dueño de ese correo.'
    if isinstance(error, (socket.timeout, TimeoutError)):
        return f'El servidor de correo {cuenta.servidor}:{cuenta.puerto} no respondió a tiempo.'
    if isinstance(error, (socket.gaierror, ConnectionError, OSError)) and not isinstance(error, smtplib.SMTPException):
        return f'No se pudo conectar con {cuenta.servidor}:{cuenta.puerto}. Revise el servidor, el puerto y la seguridad.'
    return f'El servidor de correo respondió con un error: {error}'


def probar_cuenta(cuenta):
    """Abre y cierra la conexión con el servidor (inicia sesión sin enviar nada). Guarda y devuelve (ok, mensaje)."""
    try:
        conn = conexion(cuenta)
        conn.open()
        conn.close()
        ok, mensaje = True, 'Conexión correcta: el servidor aceptó el usuario y la contraseña.'
    except Exception as e:
        ok, mensaje = False, explicar_error_smtp(e, cuenta)
    if cuenta.pk:
        cuenta.probada_en, cuenta.prueba_ok, cuenta.prueba_mensaje = timezone.now(), ok, mensaje[:300]
        cuenta.save(update_fields=['probada_en', 'prueba_ok', 'prueba_mensaje'])
    return ok, mensaje


def enviar(plantilla, vehiculo, usuario, para, cc, asunto, pdf=None):
    """Envía el correo y lo registra. `para` y `cc` son textos con correos separados por coma. Devuelve el
    CorreoEnviado; lanza CorreoError (y deja el intento registrado) si no se pudo."""
    cuenta = plantilla.cuenta
    if cuenta is None or not cuenta.is_active:
        raise CorreoError('La plantilla no tiene una cuenta de envío activa.')
    if not cuenta.clave:
        raise CorreoError(f'La cuenta «{cuenta.nombre}» no tiene contraseña registrada.')
    datos = valores(vehiculo, usuario)
    lista_para, lista_cc = destinatarios(para, datos), destinatarios(cc, datos)
    if not lista_para:
        raise CorreoError('Escriba al menos un correo en «Para».')
    asunto = (asunto or '').strip()
    if not asunto:
        raise CorreoError('Escriba el asunto.')

    correo = armar(plantilla, vehiculo, usuario, para_envio=True)
    mensaje = _CorreoConImagenes(subject=asunto, body=correo['texto'], from_email=cuenta.remitente, to=lista_para,
                                 cc=lista_cc, connection=conexion(cuenta), imagenes=correo['imagenes'])
    mensaje.attach_alternative(correo['html'], 'text/html')
    adjuntos = []
    if pdf:
        adjuntos.append(correo['adjunto'] or f'Comparativo {vehiculo.placa}.pdf')
        mensaje.attach(adjuntos[-1], pdf, 'application/pdf')
    # PDF de las cotizaciones de las 2 más baratas (del portal, descargado por el bot, o subido por el asesor).
    del_portal = []
    for cotizacion in correo['cotizaciones']:
        if cotizacion['documento']:
            with cotizacion['documento'].open('rb') as archivo:
                mensaje.attach(cotizacion['archivo'], archivo.read(), 'application/pdf')
            adjuntos.append(cotizacion['archivo'])
            if cotizacion['tipo'] == 'bot':
                del_portal.append(cotizacion['ref_id'])

    registro = CorreoEnviado(vehiculo=vehiculo, plantilla=plantilla, remitente=cuenta.remitente[:200],
                             para=', '.join(lista_para)[:500], cc=', '.join(lista_cc)[:500], asunto=asunto[:300],
                             adjunto=', '.join(adjuntos)[:150], enviado_por=usuario)
    try:
        mensaje.send()
    except Exception as e:
        registro.estado, registro.error = 'error', str(e)[:2000]
        registro.save()
        raise CorreoError(explicar_error_smtp(e, cuenta))
    registro.save()
    if del_portal:  # enviados al cliente: la limpieza de los 10 días ya no los borra
        Cotizacion.objects.filter(pk__in=del_portal).update(pdf_enviado_en=timezone.now())
    registrar_evento(vehiculo, 'correo', '', f'Cotización enviada a {registro.para}'[:200],
                     f'Desde {cuenta.correo}' + (f' · CC {registro.cc}' if registro.cc else ''), usuario)
    return registro
