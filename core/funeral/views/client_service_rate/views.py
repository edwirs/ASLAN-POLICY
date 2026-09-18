import json

from django.http import HttpResponse
from django.urls import reverse_lazy
from django.views.generic import DeleteView, CreateView, UpdateView, TemplateView

from core.funeral.forms import ClientServiceRateForm
from core.funeral.models import ClientServiceRate
from core.security.mixins import GroupPermissionMixin

MODULE_NAME = 'Servicios por entidad'


class ClientServiceRateListView(GroupPermissionMixin, TemplateView):
    template_name = 'client_service_rate/list.html'
    permission_required = 'view_clientservicerate'

    def post(self, request, *args, **kwargs):
        data = {}
        action = request.POST['action']
        try:
            if action == 'search':
                data = []
                for i in ClientServiceRate.objects.select_related('client', 'service_type', 'product').all():
                    data.append(i.toJSON())
            else:
                data['error'] = 'No ha seleccionado ninguna opción'
        except Exception as e:
            data['error'] = str(e)
        return HttpResponse(json.dumps(data), content_type='application/json')

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['title'] = 'Listado de Servicios por entidad'
        context['list_url'] = reverse_lazy('client_service_rate_list')
        context['create_url'] = reverse_lazy('client_service_rate_create')
        context['module_name'] = MODULE_NAME
        return context


class ClientServiceRateCreateView(GroupPermissionMixin, CreateView):
    template_name = 'client_service_rate/create.html'
    model = ClientServiceRate
    form_class = ClientServiceRateForm
    success_url = reverse_lazy('client_service_rate_list')
    permission_required = 'add_clientservicerate'

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
        context['title'] = 'Nuevo registro de un Servicio por entidad'
        context['list_url'] = self.success_url
        context['action'] = 'add'
        context['module_name'] = MODULE_NAME
        return context


class ClientServiceRateUpdateView(GroupPermissionMixin, UpdateView):
    template_name = 'client_service_rate/create.html'
    model = ClientServiceRate
    form_class = ClientServiceRateForm
    success_url = reverse_lazy('client_service_rate_list')
    permission_required = 'change_clientservicerate'

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
        context['title'] = 'Edición de un Servicio por entidad'
        context['list_url'] = self.success_url
        context['action'] = 'edit'
        context['module_name'] = MODULE_NAME
        return context


class ClientServiceRateDeleteView(GroupPermissionMixin, DeleteView):
    model = ClientServiceRate
    template_name = 'delete.html'
    success_url = reverse_lazy('client_service_rate_list')
    permission_required = 'delete_clientservicerate'

    def post(self, request, *args, **kwargs):
        data = {}
        try:
            self.get_object().delete()
        except Exception as e:
            data['error'] = str(e)
        return HttpResponse(json.dumps(data), content_type='application/json')

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['title'] = 'Eliminación de un Servicio por entidad'
        context['list_url'] = self.success_url
        context['module_name'] = MODULE_NAME
        return context
