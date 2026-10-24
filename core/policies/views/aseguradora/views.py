import json

from django.http import HttpResponse
from django.shortcuts import get_object_or_404
from django.urls import reverse_lazy
from django.utils import timezone
from django.views.generic import TemplateView

from core.policies.forms import AseguradoraCredencialForm, CoberturaForm
from core.policies.models import Aseguradora, CoberturaAseguradora
from core.policies.services.coberturas import secciones_de
from core.policies.services.bots import BOTS_DISPONIBLES
from core.policies.services.credenciales import credencial_vigente, faltantes
from core.security.mixins import StrictPermissionMixin

MODULE_NAME = 'Aseguradoras'


def _resumen(aseguradora):
    credencial = credencial_vigente(aseguradora)
    pendientes = faltantes(aseguradora, credencial)
    return {
        'id': aseguradora.id,
        'name': aseguradora.name,
        'nit': aseguradora.nit,
        'is_active': aseguradora.is_active,
        'tiene_bot': aseguradora.name in BOTS_DISPONIBLES,
        'portal_url': credencial.portal_url if credencial else None,
        'username': (credencial.username or credencial.cuenta or credencial.codigo_intermediario) if credencial else None,
        # La contraseña nunca viaja al navegador: solo se informa si existe.
        'tiene_password': bool(credencial and credencial.password),
        'clave_pendiente': bool(credencial and credencial.requiere_cambio_clave),
        'clave_detectada': (timezone.localtime(credencial.cambio_clave_detectado_en).strftime('%d/%m/%Y %H:%M')
                            if credencial and credencial.cambio_clave_detectado_en else None),
        'completa': not pendientes,
        'faltantes': pendientes,
    }


class AseguradoraListView(StrictPermissionMixin, TemplateView):
    template_name = 'aseguradora/list.html'
    permission_required = 'policies.view_aseguradora'

    def post(self, request, *args, **kwargs):
        data = {}
        action = request.POST.get('action')
        try:
            if action == 'search':
                data = [_resumen(a) for a in Aseguradora.objects.all()]
            elif action == 'toggle':
                if not request.user.has_perm('policies.change_aseguradora'):
                    data['error'] = 'Tu perfil no puede activar o inactivar aseguradoras.'
                else:
                    aseguradora = Aseguradora.objects.get(pk=request.POST.get('id'))
                    activar = request.POST.get('activar') == 'true'
                    pendientes = faltantes(aseguradora) if aseguradora.name in BOTS_DISPONIBLES else []
                    if activar and pendientes:
                        data['error'] = (f'No se puede activar {aseguradora.name}: faltan datos de acceso ({", ".join(pendientes)}). '
                                         'Complétalos con el botón Editar.')
                    else:
                        aseguradora.is_active = activar
                        aseguradora.save(update_fields=['is_active'])
                        data = _resumen(aseguradora)
            elif action == 'clave_resuelta':
                # Falsa alarma (o ya la cambiaron sin pasar por aquí): se quita el bloqueo sin tocar la contraseña.
                if not request.user.has_perm('policies.change_aseguradora'):
                    data['error'] = 'Tu perfil no puede modificar aseguradoras.'
                else:
                    aseguradora = Aseguradora.objects.get(pk=request.POST.get('id'))
                    aseguradora.credenciales.filter(requiere_cambio_clave=True).update(
                        requiere_cambio_clave=False, cambio_clave_detectado_en=None)
                    data = _resumen(aseguradora)
            else:
                data['error'] = 'No ha seleccionado ninguna opción'
        except Exception as e:
            data['error'] = str(e)
        return HttpResponse(json.dumps(data), content_type='application/json')

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['title'] = 'Aseguradoras'
        context['module_name'] = MODULE_NAME
        context['list_url'] = reverse_lazy('aseguradora_list')
        if self.request.user.has_perm('policies.add_aseguradora'):
            context['create_url'] = reverse_lazy('aseguradora_create')
        return context


class AseguradoraUpdateView(StrictPermissionMixin, TemplateView):
    template_name = 'aseguradora/update.html'
    permission_required = 'policies.change_aseguradora'

    def get_aseguradora(self):
        return get_object_or_404(Aseguradora, pk=self.kwargs['pk'])

    def get_form(self):
        aseguradora = self.get_aseguradora()
        return AseguradoraCredencialForm(
            self.request.POST or None, aseguradora=aseguradora, credencial=credencial_vigente(aseguradora))

    def post(self, request, *args, **kwargs):
        data = {}
        try:
            if request.POST.get('action') == 'edit':
                form = self.get_form()
                if form.is_valid():
                    form.save()
                else:
                    data['error'] = {campo: list(errores) for campo, errores in form.errors.items()}
            else:
                data['error'] = 'No ha seleccionado ninguna opción'
        except Exception as e:
            data['error'] = str(e)
        return HttpResponse(json.dumps(data), content_type='application/json')

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        aseguradora = self.get_aseguradora()
        context['title'] = f'Acceso a {aseguradora.name}'
        context['aseguradora'] = aseguradora
        context['form'] = self.get_form()
        context['action'] = 'edit'
        context['module_name'] = MODULE_NAME
        context['list_url'] = reverse_lazy('aseguradora_list')
        context['tiene_bot'] = aseguradora.name in BOTS_DISPONIBLES
        context['tab_activa'] = 'acceso'
        credencial = credencial_vigente(aseguradora)
        context['clave_pendiente'] = bool(credencial and credencial.requiere_cambio_clave)
        context['clave_detectada'] = credencial.cambio_clave_detectado_en if credencial else None
        return context


class AseguradoraCreateView(StrictPermissionMixin, TemplateView):
    """Alta de una aseguradora con sus datos de acceso. Una aseguradora nueva
    queda guardada con su portal y credenciales, pero solo se cotiza de forma
    automática si existe un bot para ella (ver BOTS_DISPONIBLES)."""
    template_name = 'aseguradora/update.html'
    permission_required = 'policies.add_aseguradora'

    def get_form(self):
        return AseguradoraCredencialForm(self.request.POST or None, aseguradora=Aseguradora())

    def post(self, request, *args, **kwargs):
        data = {}
        try:
            if request.POST.get('action') == 'add':
                form = self.get_form()
                if form.is_valid():
                    form.save()
                else:
                    data['error'] = {campo: list(errores) for campo, errores in form.errors.items()}
            else:
                data['error'] = 'No ha seleccionado ninguna opción'
        except Exception as e:
            data['error'] = str(e)
        return HttpResponse(json.dumps(data), content_type='application/json')

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['title'] = 'Nueva aseguradora'
        context['aseguradora'] = Aseguradora()
        context['form'] = self.get_form()
        context['action'] = 'add'
        context['es_nueva'] = True
        context['module_name'] = MODULE_NAME
        context['list_url'] = reverse_lazy('aseguradora_list')
        context['tiene_bot'] = True  # no se muestra el aviso de "sin bot" al crear
        return context


class AseguradoraCoberturasView(StrictPermissionMixin, TemplateView):
    """Vista previa de las fichas de coberturas (una por producto) de una aseguradora."""
    template_name = 'aseguradora/coberturas.html'
    permission_required = 'policies.view_aseguradora'

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        aseguradora = get_object_or_404(Aseguradora, pk=self.kwargs['pk'])
        context['title'] = f'Coberturas de {aseguradora.name}'
        context['aseguradora'] = aseguradora
        context['fichas'] = [{'ficha': f, 'secciones': secciones_de(f)} for f in aseguradora.fichas.all()]
        context['puede_editar'] = self.request.user.has_perm('policies.change_aseguradora')
        context['tiene_bot'] = aseguradora.name in BOTS_DISPONIBLES
        context['tab_activa'] = 'coberturas'
        context['module_name'] = MODULE_NAME
        context['list_url'] = reverse_lazy('aseguradora_list')
        return context


class CoberturaFormView(StrictPermissionMixin, TemplateView):
    """Alta y edición de una ficha de coberturas. Cambiar coberturas exige poder editar aseguradoras."""
    template_name = 'aseguradora/cobertura_form.html'
    permission_required = 'policies.change_aseguradora'

    def get_aseguradora(self):
        return get_object_or_404(Aseguradora, pk=self.kwargs['pk'])

    def get_ficha(self):
        if 'ficha' in self.kwargs:
            return get_object_or_404(CoberturaAseguradora, pk=self.kwargs['ficha'], aseguradora=self.get_aseguradora())
        return None

    def get_form(self):
        return CoberturaForm(self.request.POST or None, instance=self.get_ficha(), aseguradora=self.get_aseguradora())

    def post(self, request, *args, **kwargs):
        data = {}
        try:
            if request.POST.get('action') in ('add', 'edit'):
                form = self.get_form()
                if form.is_valid():
                    form.save()
                else:
                    data['error'] = {campo: list(errores) for campo, errores in form.errors.items()}
            else:
                data['error'] = 'No ha seleccionado ninguna opción'
        except Exception as e:
            data['error'] = str(e)
        return HttpResponse(json.dumps(data), content_type='application/json')

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        aseguradora = self.get_aseguradora()
        ficha = self.get_ficha()
        context['aseguradora'] = aseguradora
        context['form'] = self.get_form()
        context['action'] = 'edit' if ficha else 'add'
        context['title'] = f'Ficha de {aseguradora.name}' + (f' — {ficha.producto}' if ficha else ': nuevo producto')
        context['tab_activa'] = 'coberturas'
        context['module_name'] = MODULE_NAME
        context['list_url'] = reverse_lazy('aseguradora_coberturas', kwargs={'pk': aseguradora.pk})
        return context
