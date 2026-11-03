import re

from core.pos.models import Client


def get_or_update_client(cd, municipality=None):
    """Busca un Client por cédula y actualiza sus datos, o lo crea si no
    existe. `municipality` solo se toca si se pasa explícitamente, para no
    borrar la ciudad ya guardada de un cliente existente cuando el
    formulario que llama a esto no la pide (ej. cambio de propietario)."""
    client = Client.objects.filter(dni=cd['dni']).first()
    if client:
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
            dni=cd['dni'],
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
