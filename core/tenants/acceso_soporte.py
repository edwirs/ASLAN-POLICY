"""Lado de la EMPRESA del «entrar como» del panel de la plataforma: canjea el token firmado (60 s, un solo uso) por una sesión.

El token lo emite el panel (`gestion.soporte_entrar`) en el dominio `admin.…`; como las cookies no se comparten entre dominios, la
sesión se abre aquí, en el dominio de la empresa, y queda marcada como «soporte» para mostrar un aviso permanente.
"""
import logging

from django.contrib.auth import login
from django.core import signing
from django.core.cache import cache
from django.db import connection
from django.http import HttpResponse, HttpResponseRedirect
from django.urls import reverse
from django_tenants.utils import get_public_schema_name, schema_context

from core.user.models import User

logger = logging.getLogger(__name__)
SAL = 'acceso-soporte'
VIGENCIA = 60


def acceso_soporte(request):
    try:
        datos = signing.loads(request.GET.get('t', ''), salt=SAL, max_age=VIGENCIA)
    except signing.BadSignature:
        return HttpResponse('El enlace de soporte venció o no es válido. Vuelve a generarlo desde el panel.', status=403)
    if datos.get('s') != connection.schema_name or not cache.add(f'soporte:{datos.get("n")}', 1, VIGENCIA * 2):
        return HttpResponse('Este enlace de soporte ya se usó o es de otra empresa.', status=403)
    usuario = User.objects.filter(pk=datos.get('u'), is_active=True).first()
    if usuario is None:
        return HttpResponse('Ese usuario no existe o está inactivo.', status=404)
    login(request, usuario, backend='django.contrib.auth.backends.ModelBackend')
    request.session['soporte'] = True
    from core.tenants.models import Auditoria  # vive en «public»

    with schema_context(get_public_schema_name()):
        Auditoria.objects.create(accion='entrar_como_canjeado', schema=connection.schema_name, detalle=usuario.username,
                                 ip=request.META.get('REMOTE_ADDR', '?')[:45])
    logger.warning('Acceso de soporte a "%s" como %s', connection.schema_name, usuario.username)
    return HttpResponseRedirect(reverse('dashboard'))
