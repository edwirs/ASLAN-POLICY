import json

from django.http import HttpResponse
from django.urls import reverse_lazy
from django.views.generic import CreateView, TemplateView, UpdateView

from core.policies.forms import AsesorForm
from core.policies.models import Asesor
from core.security.mixins import StrictPermissionMixin

MODULE_NAME = 'Asesores'


class AsesorListView(StrictPermissionMixin, TemplateView):
    template_name = 'asesor/list.html'
    permission_required = 'policies.view_asesor'

    def post(self, request, *args, **kwargs):
        data = {}
        action = request.POST.get('action')
        try:
            if action == 'search':
                data = [a.toJSON() for a in Asesor.objects.select_related('tipo_documento', 'ciudad__departamento', 'usuario')]
            elif action == 'toggle':
                if not request.user.has_perm('policies.change_asesor'):
                    data['error'] = 'Tu perfil no puede activar o inactivar asesores.'
                else:
                    asesor = Asesor.objects.get(pk=request.POST.get('id'))
                    asesor.is_active = request.POST.get('activar') == 'true'
                    asesor.save(update_fields=['is_active'])
                    data = asesor.toJSON()
            else:
                data['error'] = 'No ha seleccionado ninguna opción'
        except Exception as e:
            data['error'] = str(e)
        return HttpResponse(json.dumps(data), content_type='application/json')

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['title'] = 'Asesores'
        context['module_name'] = MODULE_NAME
        context['list_url'] = reverse_lazy('asesor_list')
        if self.request.user.has_perm('policies.add_asesor'):
            context['create_url'] = reverse_lazy('asesor_create')
        return context


class _AsesorFormMixin(StrictPermissionMixin):
    template_name = 'asesor/form.html'
    model = Asesor
    form_class = AsesorForm
    success_url = reverse_lazy('asesor_list')
    accion = None

    def post(self, request, *args, **kwargs):
        data = {}
        try:
            self.object = self.get_object() if 'pk' in self.kwargs else None  # al sobrescribir post, la vista no lo fija sola
            if request.POST.get('action') == self.accion:
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
        context['list_url'] = self.success_url
        context['action'] = self.accion
        context['module_name'] = MODULE_NAME
        return context


class AsesorCreateView(_AsesorFormMixin, CreateView):
    permission_required = 'policies.add_asesor'
    accion = 'add'

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['title'] = 'Nuevo asesor'
        return context


class AsesorUpdateView(_AsesorFormMixin, UpdateView):
    permission_required = 'policies.change_asesor'
    accion = 'edit'

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['title'] = f'Asesor: {self.object.nombres}'
        return context
