"""Seguridad del panel de la plataforma: cambio de clave, verificación en dos pasos (TOTP) y lista de IPs permitidas."""
import ipaddress

from django.contrib.auth.hashers import check_password, make_password
from django.core import signing
from django.core.cache import cache
from django.http import HttpResponseRedirect
from django.urls import reverse
from django.views.decorators.http import require_POST

from core.tenants import totp
from core.tenants.models import AccesoPlataforma
from core.tenants.plataforma import (_ip, _responder, _sesion_cookie, acceso_guardado, auditar, credenciales, ips_permitidas, requiere_acceso)


def _volver(ok=None, error=None):
    from urllib.parse import urlencode

    return HttpResponseRedirect(reverse('plataforma_seguridad') + '?' + urlencode({'ok': ok} if ok else {'error': error}))


def _guardado_o_crear():
    """El acceso guardado; si todavía rige lo de .env.secrets, lo copia a la base para poder agregarle 2FA o IPs."""
    acceso = acceso_guardado()
    if acceso is None:
        usuario, clave_hash = credenciales()
        acceso = AccesoPlataforma.objects.create(usuario=usuario, clave_hash=clave_hash)
    return acceso


@requiere_acceso
def seguridad_pagina(request, extra=None):
    acceso = acceso_guardado()
    contexto = {'seccion': 'seguridad', 'ip': _ip(request), 'ips': ', '.join(ips_permitidas()), 'totp_activo': bool(acceso and acceso.totp_activo),
                'origen': 'panel' if acceso else 'archivo', 'aviso': request.GET.get('ok'), 'error': request.GET.get('error')}
    if acceso and acceso.totp_secreto and not acceso.totp_activo:  # configuración a medias: se vuelve a mostrar el QR
        contexto['totp_pendiente'] = {'secreto': acceso.totp_secreto,
                                      'qr': totp.qr_png_base64(totp.uri(acceso.totp_secreto, acceso.usuario))}
    return _responder(request, 'plataforma/seguridad.html', {**contexto, **(extra or {})})


@requiere_acceso
@require_POST
def cambiar_clave(request):
    usuario, clave_hash = credenciales()
    actual, nueva, repetir = request.POST.get('actual', ''), request.POST.get('nueva', ''), request.POST.get('repetir', '')
    if not check_password(actual, clave_hash):
        auditar(request, 'cambio_clave_fallido', detalle='la clave actual no coincide')
        return _volver(error='La clave actual no es correcta.')
    if len(nueva) < 12:
        return _volver(error='La clave nueva debe tener al menos 12 caracteres.')
    if nueva != repetir:
        return _volver(error='Las dos claves nuevas no coinciden.')
    if check_password(nueva, clave_hash):
        return _volver(error='La clave nueva debe ser distinta de la actual.')
    acceso = _guardado_o_crear()
    acceso.clave_hash = make_password(nueva)
    acceso.save(update_fields=['clave_hash', 'actualizado'])
    auditar(request, 'clave_cambiada')
    # Cambiar la clave invalida todas las cookies anteriores (llevan la huella de la clave); aquí se emite una nueva para seguir adentro.
    return _sesion_cookie(_volver(ok='Clave cambiada. Las demás sesiones abiertas se cerraron.'), usuario)


@requiere_acceso
@require_POST
def totp_iniciar(request):
    acceso = _guardado_o_crear()
    if acceso.totp_activo:
        return _volver(error='La verificación en dos pasos ya está activa.')
    acceso.totp_secreto = totp.nuevo_secreto()
    acceso.save(update_fields=['totp_secreto', 'actualizado'])
    return _volver(ok='Escanea el código QR con tu app de autenticación y escribe el código que te muestra para terminar.')


@requiere_acceso
@require_POST
def totp_confirmar(request):
    acceso = acceso_guardado()
    if acceso is None or not acceso.totp_secreto or acceso.totp_activo:
        return _volver(error='No hay una activación pendiente.')
    paso = totp.verificar(acceso.totp_secreto, request.POST.get('codigo', ''))
    if paso is None:
        return _volver(error='Ese código no es correcto. Revisa que la hora de tu celular sea automática e intenta de nuevo.')
    cache.add(f'plataforma:totp:{paso}', 1, 120)  # el código con que se activó no sirve otra vez para entrar
    acceso.totp_activo = True
    acceso.save(update_fields=['totp_activo', 'actualizado'])
    auditar(request, 'dos_pasos_activado')
    return _volver(ok='Verificación en dos pasos activada. Desde el próximo ingreso se pedirá el código.')


@requiere_acceso
@require_POST
def totp_desactivar(request):
    acceso = acceso_guardado()
    if acceso is None or not acceso.totp_activo:
        return _volver(error='La verificación en dos pasos no está activa.')
    paso = totp.verificar(acceso.totp_secreto, request.POST.get('codigo', ''))
    if not check_password(request.POST.get('clave', ''), acceso.clave_hash) or paso is None or not cache.add(f'plataforma:totp:{paso}', 1, 120):
        auditar(request, 'dos_pasos_desactivar_fallido')
        return _volver(error='Para desactivarla escribe tu clave y un código vigente.')
    acceso.totp_activo, acceso.totp_secreto = False, ''
    acceso.save(update_fields=['totp_activo', 'totp_secreto', 'actualizado'])
    auditar(request, 'dos_pasos_desactivado')
    return _volver(ok='Verificación en dos pasos desactivada.')


@requiere_acceso
@require_POST
def guardar_ips(request):
    """Lista de IPs (o rangos tipo 181.1.2.0/24) que pueden abrir el panel. Se rechaza si dejaría fuera a quien la está guardando."""
    crudo = request.POST.get('ips', '').replace('\n', ',').replace(';', ',').replace(' ', ',')
    lista = [i.strip() for i in crudo.split(',') if i.strip()]
    try:
        redes = [ipaddress.ip_network(i, strict=False) for i in lista]
    except ValueError as exc:
        return _volver(error=f'Dirección no válida: {exc}')
    if redes:
        try:
            propia = ipaddress.ip_address(_ip(request))
        except ValueError:
            propia = None
        if propia is None or not any(propia in r for r in redes):
            return _volver(error=f'Tu dirección actual ({_ip(request)}) no está en la lista; si la guardas te quedarías fuera. Inclúyela.')
    acceso = _guardado_o_crear()
    acceso.ips_permitidas = ','.join(lista)
    acceso.save(update_fields=['ips_permitidas', 'actualizado'])
    auditar(request, 'ips_permitidas', detalle=acceso.ips_permitidas or 'cualquiera')
    return _volver(ok='Lista de direcciones guardada.' if lista else 'Sin restricción de direcciones: el panel abre desde cualquier lugar.')
