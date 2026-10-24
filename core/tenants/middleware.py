"""Bloquea, en el dominio de cada empresa, lo que su plan no incluye: acceso suspendido y módulos no contratados."""
from django.http import HttpResponse, JsonResponse
from django.template.loader import get_template
from django_tenants.utils import get_public_schema_name

from core.tenants.estado import NOMBRE_MODULO, estado_suscripcion, modulo_de_ruta

LIBRES = ('/static/', '/media/', '/logout/', '/acceso-soporte/')


class EstadoEmpresaMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        empresa = getattr(request, 'tenant', None)
        if empresa is not None and getattr(empresa, 'schema_name', get_public_schema_name()) != get_public_schema_name() \
                and hasattr(empresa, 'suspendida') and not request.path.startswith(LIBRES):
            estado = estado_suscripcion(empresa)
            if estado['suspendida']:
                return self._pagina('empresa_suspendida.html', {'empresa': empresa, 'mensaje': estado['mensaje']}, 402, request)
            modulo = modulo_de_ruta(request.path)
            if modulo and not getattr(empresa, f'modulo_{modulo}', True):
                return self._pagina('modulo_no_contratado.html', {'empresa': empresa, 'modulo': NOMBRE_MODULO[modulo]}, 403, request,
                                    mensaje_json=f'El módulo {NOMBRE_MODULO[modulo]} no está incluido en el plan de tu empresa.')
        return self.get_response(request)

    @staticmethod
    def _pagina(plantilla, contexto, status, request, mensaje_json=None):
        if request.method != 'GET' or request.headers.get('x-requested-with') == 'XMLHttpRequest':
            return JsonResponse({'error': mensaje_json or contexto.get('mensaje', 'Acceso no disponible.')}, status=status)
        return HttpResponse(get_template(plantilla).render(contexto), status=status)  # sin request: no corren procesadores de contexto
