import re

from core.pos.models import Client


PESOS_DV_NIT = (3, 7, 13, 17, 19, 23, 29, 37, 41, 43, 47, 53, 59, 67, 71)


def digito_verificacion_nit(numero):
    """Dígito de verificación de un NIT con el cálculo de la DIAN (pesos primos de derecha a izquierda, módulo 11)."""
    digitos = re.sub(r'\D', '', str(numero or ''))
    if not digitos or len(digitos) > len(PESOS_DV_NIT):
        return None
    suma = sum(int(d) * p for d, p in zip(reversed(digitos), PESOS_DV_NIT))
    resto = suma % 11
    return str(resto if resto in (0, 1) else 11 - resto)


def separar_nit(documento, dv=None):
    """(número, dígito de verificación) de un NIT escrito de cualquier forma: «900.123.456-7», «900123456 7»,
    «9001234567» o «900123456» (con el dígito en `dv`). Los portales de las aseguradoras piden el número SIN el dígito.
    Diez dígitos sin separador solo se parten si empiezan por 8 o 9 (el rango de las empresas) y el último es el dígito
    correcto de los nueve primeros: así nunca se recorta una cédula de 10 dígitos (empiezan por 1)."""
    texto = str(documento or '').strip()
    dv = (str(dv).strip() or None) if dv is not None else None
    partes = re.split(r'\s*[-‐–—]\s*|\s+(?=\d$)', texto.replace('.', '').replace(',', ''))
    if len(partes) == 2 and re.fullmatch(r'\d+', partes[0]) and re.fullmatch(r'\d', partes[1]):
        return partes[0], partes[1]
    numero = re.sub(r'\D', '', texto)
    if not dv and re.fullmatch(r'[89]\d{9}', numero) and digito_verificacion_nit(numero[:9]) == numero[9]:
        return numero[:9], numero[9]
    return numero or texto, dv


def normalizar_documento(document_type, dni, dv=None):
    """(dni, dv) como se guardan en el cliente: para NIT, solo el número y el dígito aparte; los demás tipos, tal cual
    (un pasaporte puede tener letras)."""
    dni = str(dni or '').strip()
    if (getattr(document_type, 'abbreviation', '') or '').upper() != 'NIT':
        return dni, dv
    return separar_nit(dni, dv)


def buscar_cliente_por_documento(dni):
    """El cliente con ese número. Para un NIT también encuentra los guardados antes con el dígito pegado («…-7»)."""
    client = Client.objects.filter(dni=dni).first()
    if client is None and re.fullmatch(r'\d{6,10}', dni or ''):
        client = Client.objects.filter(dni__regex=rf'^{dni}\s*-\s*\d$').first()
    return client


def cliente_por_documento_escrito(valor):
    """Para «Consultar» de la nueva solicitud: el cliente con el documento tal como lo escribió el asesor y, si tiene
    forma de NIT con su dígito (900.123.456-7, 9001234567), el guardado con el número solo."""
    valor = (valor or '').strip()
    client = Client.objects.filter(dni=valor).first()
    if client is None and re.fullmatch(r'\d{6,10}', valor):
        client = buscar_cliente_por_documento(valor)
    if client is None and re.fullmatch(r'[\d.\s]+(?:[-‐–—]\s*\d|\s\d)|[89]\d{9}', valor):
        client = buscar_cliente_por_documento(separar_nit(valor)[0])
    return client


def get_or_update_client(cd, municipality=None):
    """Busca un Client por cédula y actualiza sus datos, o lo crea si no
    existe. `municipality` solo se toca si se pasa explícitamente, para no
    borrar la ciudad ya guardada de un cliente existente cuando el
    formulario que llama a esto no la pide (ej. cambio de propietario).
    Un NIT se guarda sin el dígito de verificación, que va en `dv`."""
    dni, dv = normalizar_documento(cd['document_type'], cd['dni'], cd.get('dv'))
    client = buscar_cliente_por_documento(dni)
    if client:
        if client.dni != dni and not Client.objects.filter(dni=dni).exclude(pk=client.pk).exists():
            client.dni = dni  # NIT guardado antes con el dígito pegado: queda solo el número
        if dv:
            client.dv = dv
        client.document_type = cd['document_type']
        client.names = cd['names']
        client.birthdate = cd['birthdate']
        client.email = cd['email']
        if municipality is not None:
            client.municipality = municipality
        # El celular solo se actualiza si viene: un formulario que no lo pide no debe borrarlo.
        if cd.get('mobile'):
            client.mobile = cd['mobile']
        # Otro celular y otro correo: los manda (o los borra) el formulario que trae «mas_contacto»; los demás no los tocan.
        if 'mas_contacto' in cd:
            client.phone = cd.get('phone') or None
            client.email_secundario = cd.get('email_secundario') or None
        elif cd.get('phone'):
            client.phone = cd['phone']
        _propietario_empresa(client, cd)
        client.save()
    else:
        client = Client.objects.create(
            dni=dni,
            dv=dv,
            document_type=cd['document_type'],
            names=cd['names'],
            birthdate=cd['birthdate'],
            email=cd['email'],
            mobile=cd.get('mobile') or None,
            phone=cd.get('phone') or None,
            email_secundario=cd.get('email_secundario') or None,
            municipality=municipality,
        )
        if _propietario_empresa(client, cd):
            client.save(update_fields=['propietario_documento', 'propietario_nombre'])
    return client


def _propietario_empresa(client, cd):
    """Cédula y nombre del dueño de la empresa: solo para NIT. Si el cliente deja de ser NIT se borran; si el formulario
    que llama no trae los campos, no se tocan. Devuelve True si cambió algo."""
    antes = (client.propietario_documento, client.propietario_nombre)
    if not client.es_empresa:
        client.propietario_documento = client.propietario_nombre = None
    elif 'propietario_documento' in cd or 'propietario_nombre' in cd:
        client.propietario_documento = cd.get('propietario_documento') or None
        client.propietario_nombre = cd.get('propietario_nombre') or None
    return (client.propietario_documento, client.propietario_nombre) != antes


def parece_nit(documento):
    """Para el importador del Excel (la columna CEDULA no dice el tipo): es NIT si trae dígito de verificación
    (900123456-7) o si son 9 dígitos que empiezan por 8 o 9, el rango de las personas jurídicas en Colombia."""
    texto = str(documento or '').strip().replace('.', '').replace(' ', '')
    if re.fullmatch(r'\d{6,10}-\d', texto):
        return True
    return bool(re.fullmatch(r'[89]\d{8}', texto))
