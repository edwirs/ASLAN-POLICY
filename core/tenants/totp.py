"""Verificación en dos pasos (TOTP, RFC 6238) sin dependencias: compatible con Google Authenticator, Authy, Microsoft Authenticator…"""
import base64
import hashlib
import hmac
import io
import secrets
import struct
import time
from urllib.parse import quote

PASO = 30
DIGITOS = 6


def nuevo_secreto():
    return base64.b32encode(secrets.token_bytes(20)).decode().rstrip('=')


def _codigo(secreto, contador):
    clave = base64.b32decode(secreto + '=' * (-len(secreto) % 8), casefold=True)
    h = hmac.new(clave, struct.pack('>Q', contador), hashlib.sha1).digest()
    o = h[-1] & 0x0F
    return str((struct.unpack('>I', h[o:o + 4])[0] & 0x7FFFFFFF) % 10 ** DIGITOS).zfill(DIGITOS)


def codigo_actual(secreto, ahora=None):
    return _codigo(secreto, int((ahora or time.time()) // PASO))


def verificar(secreto, texto, ahora=None):
    """Paso (contador) del código si es válido (tolera ±1 paso por desfase del reloj), o None. El llamador debe rechazar un paso ya usado."""
    texto = ''.join(c for c in str(texto) if c.isdigit())
    if len(texto) != DIGITOS or not secreto:
        return None
    actual = int((ahora or time.time()) // PASO)
    for paso in (actual, actual - 1, actual + 1):
        if hmac.compare_digest(_codigo(secreto, paso), texto):
            return paso
    return None


def uri(secreto, usuario, emisor='ASLAN Plataforma'):
    return f'otpauth://totp/{quote(emisor)}:{quote(usuario)}?secret={secreto}&issuer={quote(emisor)}&digits={DIGITOS}&period={PASO}'


def qr_png_base64(texto):
    """Código QR como imagen PNG en base64, listo para <img src="data:image/png;base64,…">."""
    import qrcode

    imagen = qrcode.make(texto, box_size=6, border=2)
    buffer = io.BytesIO()
    imagen.save(buffer, format='PNG')
    return base64.b64encode(buffer.getvalue()).decode()
