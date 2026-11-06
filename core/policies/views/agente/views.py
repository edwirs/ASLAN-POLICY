"""Pantalla «Agente de la oficina» (Configuraciones) y la API con la que el Agente ASLAN se vincula.

La pantalla deja ver qué equipos tienen el agente y si están en línea, generar el código para vincular uno nuevo y
desvincular los que ya no se usan. La lógica está en core/tenants/agentes.py; el relevo en
core/tenants/management/commands/relay_agentes.py.
"""
import json

from django.conf import settings
from django.core.cache import cache
from django.db import connection
from django.http import HttpResponse, JsonResponse
from django.urls import reverse_lazy
from django.utils import timezone
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST
from django.views.generic import TemplateView
from django_tenants.utils import schema_context

from core.policies.models import Aseguradora
from core.policies.services.credenciales import CON_AGENTE, OPCIONES_EJECUCION, credencial_vigente, parametro
from core.security.mixins import StrictPermissionMixin
from core.tenants import agentes

MODULE_NAME = 'Agente de la oficina'
ETIQUETA_MODO = dict(OPCIONES_EJECUCION)


def _aseguradoras_con_agente():
    """Cómo está configurada cada aseguradora con bot que puede usar el agente."""
    filas = []
    for aseguradora in Aseguradora.objects.filter(name__in=CON_AGENTE).order_by('name'):
        modo = parametro(credencial_vigente(aseguradora), aseguradora.name, 'ejecutar_en') or 'servidor'
        filas.append({'id': aseguradora.id, 'nombre': aseguradora.name, 'activa': aseguradora.is_active,
                      'modo': modo, 'modo_texto': ETIQUETA_MODO.get(modo, modo)})
    return filas


class AgenteOficinaView(StrictPermissionMixin, TemplateView):
    template_name = 'agente/oficina.html'
    permission_required = 'policies.view_aseguradora'

    def post(self, request, *args, **kwargs):
        data = {}
        action = request.POST.get('action')
        schema = connection.schema_name
        try:
            if action == 'search':
                with schema_context('public'):
                    data = {'agentes': [agentes.resumen(a) for a in agentes.agentes_de(schema)]}
                data['aseguradoras'] = _aseguradoras_con_agente()
            elif not request.user.has_perm('policies.change_aseguradora'):
                data['error'] = 'Tu perfil no puede administrar el agente de la oficina.'
            elif action == 'codigo':
                empresa = request.tenant
                with schema_context('public'):
                    codigo, vence = agentes.nuevo_codigo(empresa, request.user.username)
                data = {'codigo': codigo, 'vence': timezone.localtime(vence).strftime('%I:%M %p'),
                        'servidor': f'{request.scheme}://{request.get_host()}'}
            elif action == 'desvincular':
                with schema_context('public'):
                    agente = agentes.agentes_de(schema).filter(pk=request.POST.get('id')).first()
                    if agente is None:
                        data['error'] = 'Ese equipo ya no está vinculado.'
                    else:
                        agente.activo = False
                        agente.conectado = False
                        agente.save(update_fields=['activo', 'conectado'])
            elif action == 'renombrar':
                nombre = ' '.join((request.POST.get('nombre') or '').split())[:80]
                if not nombre:
                    data['error'] = 'Escribe un nombre para el equipo.'
                else:
                    with schema_context('public'):
                        agentes.agentes_de(schema).filter(pk=request.POST.get('id')).update(nombre=nombre)
            else:
                data['error'] = 'No ha seleccionado ninguna opción'
        except Exception as e:
            data['error'] = str(e)
        return HttpResponse(json.dumps(data), content_type='application/json')

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['title'] = MODULE_NAME
        context['module_name'] = MODULE_NAME
        context['list_url'] = reverse_lazy('agente_oficina')
        context['descarga_url'] = settings.AGENTE_DESCARGA_URL
        context['puede_editar'] = self.request.user.has_perm('policies.change_aseguradora')
        return context


def _ip_cliente(request):
    reenviada = request.META.get('HTTP_X_FORWARDED_FOR', '')
    if reenviada and getattr(settings, 'PLATAFORMA_CONFIAR_PROXY', False):
        return reenviada.split(',')[-1].strip()
    return request.META.get('HTTP_X_REAL_IP') or request.META.get('REMOTE_ADDR', '')


@csrf_exempt
@require_POST
def api_vincular(request):
    """El Agente ASLAN canjea aquí el código de vinculación por su llave. JSON: {codigo, equipo, sistema, version}."""
    ip = _ip_cliente(request)
    intentos_clave = f'agente-vincular:{ip}'
    intentos = cache.get(intentos_clave, 0)
    if intentos >= 10:
        return JsonResponse({'error': 'Demasiados intentos. Espere 10 minutos y vuelva a intentar.'}, status=429)
    try:
        datos = json.loads(request.body or b'{}')
    except ValueError:
        return JsonResponse({'error': 'Solicitud inválida.'}, status=400)
    try:
        with schema_context('public'):
            agente, llave = agentes.vincular(datos.get('codigo'), datos.get('equipo'), datos.get('sistema', ''),
                                             datos.get('version', ''), ip)
    except agentes.VinculacionError as exc:
        cache.set(intentos_clave, intentos + 1, 600)
        return JsonResponse({'error': str(exc)}, status=400)
    return JsonResponse({'llave': llave, 'equipo': agente.nombre, 'empresa': agente.empresa.name,
                         'control': '/agente/ws/control'})
