import json
import re

from django.contrib.auth.mixins import LoginRequiredMixin
from django.db.models import Q
from django.http import HttpResponse
from django.urls import reverse
from django.views import View

from core.tenants.estado import modulo_activo
from core.policies.models import Poliza, Vehiculo
from core.policies.services.etapas import etapas_por_vehiculo

MAX_RESULTADOS = 8
PERMISOS = ('policies.view_vehiculo', 'policies.view_vehiculo_registrado', 'policies.view_poliza')


def puede_buscar(user):
    return any(user.has_perm(p) for p in PERMISOS)


class BuscarView(LoginRequiredMixin, View):
    """Buscador de la barra superior: placa, cédula, nombre del cliente (actual o de una póliza anterior) o número de póliza.
    Devuelve los vehículos con su etapa y los enlaces a Solicitudes, Vehículos registrados y Pólizas según los permisos."""

    def get(self, request):
        user = request.user
        q = (request.GET.get('q') or '').strip()
        if not puede_buscar(user) or len(q) < 2:
            return self._json({'resultados': []})
        placa = re.sub(r'[\s-]', '', q).upper()
        filtro = (Q(placa__icontains=placa) | Q(tomador__dni__icontains=q) | Q(tomador__names__icontains=q)
                  | Q(polizas__numero_poliza__icontains=q) | Q(polizas__tomador__names__icontains=q)
                  | Q(polizas__tomador__dni__icontains=q))
        vehiculos = list(Vehiculo.objects.filter(filtro).select_related('tomador', 'tomador__document_type', 'zona_circulacion')
                         .distinct().order_by('placa')[:MAX_RESULTADOS])
        etapas = etapas_por_vehiculo(vehiculos)
        con_polizas = set(Poliza.objects.filter(vehiculo__in=vehiculos).values_list('vehiculo_id', flat=True))
        numeros = {}
        for vid, numero in Poliza.objects.filter(vehiculo__in=vehiculos, numero_poliza__icontains=q).values_list('vehiculo_id', 'numero_poliza'):
            numeros[vid] = numero

        ver_solicitudes = user.has_perm('policies.view_vehiculo')
        ver_vehiculos = user.has_perm('policies.view_vehiculo_registrado')
        ver_polizas = user.has_perm('policies.view_poliza') and modulo_activo(request, 'cartera')
        resultados = []
        for v in vehiculos:
            t = v.tomador
            enlaces = []
            if ver_vehiculos:
                enlaces.append({'texto': 'Vehículo', 'icono': 'fa-car',
                                'url': f'{reverse("vehiculo_registrado_list")}?buscar={v.placa}&abrir={v.pk}'})
            if ver_solicitudes:
                enlaces.append({'texto': 'Solicitud', 'icono': 'fa-list-check', 'url': f'{reverse("vehiculo_list")}?buscar={v.placa}'})
            if ver_polizas and v.pk in con_polizas:
                enlaces.append({'texto': 'Pólizas', 'icono': 'fa-file-shield', 'url': f'{reverse("poliza_list")}?buscar={v.placa}'})
            if not enlaces:
                continue
            resultados.append({
                'placa': v.placa,
                'vehiculo': ' '.join(str(x) for x in (v.marca, v.clase or v.referencia, v.modelo) if x),
                'cliente': t.names,
                'documento': f'{t.document_type.abbreviation if t.document_type else ""} {t.dni}'.strip(),
                'celular': t.mobile,
                'numero_poliza': numeros.get(v.pk),
                'etapa': etapas[v.pk],
                'enlaces': enlaces,
            })
        return self._json({'resultados': resultados})

    @staticmethod
    def _json(data):
        return HttpResponse(json.dumps(data), content_type='application/json')
