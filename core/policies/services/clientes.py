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
        client.save()
    else:
        client = Client.objects.create(
            dni=cd['dni'],
            document_type=cd['document_type'],
            names=cd['names'],
            birthdate=cd['birthdate'],
            email=cd['email'],
            municipality=municipality,
        )
    return client
