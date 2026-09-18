import json

from django.http import HttpResponse
from django.urls import reverse_lazy
from django.views.generic import DeleteView, CreateView, UpdateView, TemplateView

from core.funeral.forms import ServiceTypeForm
from core.funeral.models import ServiceType
from core.security.mixins import GroupPermissionMixin

MODULE_NAME = 'Tipos de servicio'


class ServiceTypeListView(GroupPermissionMixin, TemplateView):
    template_name = 'service_type/list.html'
    permission_required = 'view_servicetype'

    def post(self, request, *args, **kwargs):
        data = {}
        action = request.POST['action']
        try:
            if action == 'search':
                data = []
                for i in ServiceType.objects.all():
                    data.append(i.toJSON())
            else:
                data['error'] = 'No ha seleccionado ninguna opción'
        except Exception as e:
            data['error'] = str(e)
        return HttpResponse(json.dumps(data), content_type='application/json')

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['title'] = 'Listado de Tipos de servicio'
        context['list_url'] = reverse_lazy('service_type_list')
        context['create_url'] = reverse_lazy('service_type_create')
        context['module_name'] = MODULE_NAME
        return context


class ServiceTypeCreateView(GroupPermissionMixin, CreateView):
    template_name = 'service_type/create.html'
    model = ServiceType
    form_class = ServiceTypeForm
    success_url = reverse_lazy('service_type_list')
    permission_required = 'add_servicetype'

    def post(self, request, *args, **kwargs):
        data = {}
        action = request.POST['action']
        try:
            if action == 'add':
                data = self.get_form().save().toJSON()
            else:
                data['error'] = 'No ha seleccionado ninguna opción'
        except Exception as e:
            data['error'] = str(e)
        return HttpResponse(json.dumps(data), content_type='application/json')

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['title'] = 'Nuevo registro de un Tipo de servicio'
        context['list_url'] = self.success_url
        context['action'] = 'add'
        context['module_name'] = MODULE_NAME
        return context


class ServiceTypeUpdateView(GroupPermissionMixin, UpdateView):
    template_name = 'service_type/create.html'
    model = ServiceType
    form_class = ServiceTypeForm
    success_url = reverse_lazy('service_type_list')
    permission_required = 'change_servicetype'

    def dispatch(self, request, *args, **kwargs):
        self.object = self.get_object()
        return super().dispatch(request, *args, **kwargs)

    def post(self, request, *args, **kwargs):
        data = {}
        action = request.POST['action']
        try:
            if action == 'edit':
                data = self.get_form().save().toJSON()
            else:
                data['error'] = 'No ha seleccionado ninguna opción'
        except Exception as e:
            data['error'] = str(e)
        return HttpResponse(json.dumps(data), content_type='application/json')

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['title'] = 'Edición de un Tipo de servicio'
        context['list_url'] = self.success_url
        context['action'] = 'edit'
        context['module_name'] = MODULE_NAME
        return context


class ServiceTypeDeleteView(GroupPermissionMixin, DeleteView):
    model = ServiceType
    template_name = 'delete.html'
    success_url = reverse_lazy('service_type_list')
    permission_required = 'delete_servicetype'

    def post(self, request, *args, **kwargs):
        data = {}
        try:
            self.get_object().delete()
        except Exception as e:
            data['error'] = str(e)
        return HttpResponse(json.dumps(data), content_type='application/json')

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['title'] = 'Eliminación de un Tipo de servicio'
        context['list_url'] = self.success_url
        context['module_name'] = MODULE_NAME
        return context
