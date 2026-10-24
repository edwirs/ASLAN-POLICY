import base64
import hashlib

from cryptography.fernet import Fernet, InvalidToken
from django.conf import settings
from django.db import models


def _get_fernet():
    key = hashlib.sha256(settings.SECRET_KEY.encode()).digest()
    return Fernet(base64.urlsafe_b64encode(key))


class EncryptedCharField(models.CharField):
    """Campo de texto cifrado en reposo con Fernet (clave derivada de SECRET_KEY).

    El valor solo existe en claro en memoria durante la ejecución; en la
    base de datos siempre queda el token cifrado.
    """

    def get_prep_value(self, value):
        value = super().get_prep_value(value)
        if not value:
            return value
        return _get_fernet().encrypt(value.encode()).decode()

    def from_db_value(self, value, expression, connection):
        if not value:
            return value
        try:
            return _get_fernet().decrypt(value.encode()).decode()
        except InvalidToken:
            # Valor preexistente sin cifrar (o cifrado con otra clave): se
            # devuelve tal cual en lugar de reventar la petición.
            return value
