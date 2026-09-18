import json

from django.http import HttpResponse
from django.urls import reverse_lazy
from django.views.generic import DeleteView, CreateView, UpdateView, TemplateView

from core.funeral.forms import FuneralClientProfileForm
from core.funeral.models import FuneralClientProfile
from core.pos.models import Client
from core.security.mixins import GroupPermissionMixin

MODULE_NAME = 'Clasificación de clientes'


class FuneralClientProfileListView(GroupPermissionMixin, TemplateView):
    template_name = 'client_profile/list.html'
    permission_required = 'view_funeralclientprofile'

    def post(self, request, *args, **kwargs):
        data = {}
        action = request.POST['action']
        try:
            if action == 'search':
                data = []
                for i in FuneralClientProfile.objects.select_related('client', 'service_type').all():
                    data.append(i.toJSON())
            else:
                data['error'] = 'No ha seleccionado ninguna opción'
        except Exception as e:
            data['error'] = str(e)
        return HttpResponse(json.dumps(data), content_type='application/json')

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['title'] = 'Listado de Clasificación de clientes'
        context['list_url'] = reverse_lazy('funeral_client_profile_list')
        context['create_url'] = reverse_lazy('funeral_client_profile_create')
        context['module_name'] = MODULE_NAME
        return context


class FuneralClientProfileCreateView(GroupPermissionMixin, CreateView):
    template_name = 'client_profile/create.html'
    model = FuneralClientProfile
    form_class = FuneralClientProfileForm
    success_url = reverse_lazy('funeral_client_profile_list')
    permission_required = 'add_funeralclientprofile'

    def get_form(self, form_class=None):
        form = super().get_form(form_class)
        form.fields['client'].queryset = Client.objects.filter(funeral_profile__isnull=True)
        return form

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
        context['title'] = 'Nueva clasificación de un cliente'
        context['list_url'] = self.success_url
        context['action'] = 'add'
        context['module_name'] = MODULE_NAME
        return context


class FuneralClientProfileUpdateView(GroupPermissionMixin, UpdateView):
    template_name = 'client_profile/create.html'
    model = FuneralClientProfile
    form_class = FuneralClientProfileForm
    success_url = reverse_lazy('funeral_client_profile_list')
    permission_required = 'change_funeralclientprofile'

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
        context['title'] = 'Edición de la clasificación de un cliente'
        context['list_url'] = self.success_url
        context['action'] = 'edit'
        context['module_name'] = MODULE_NAME
        return context


class FuneralClientProfileDeleteView(GroupPermissionMixin, DeleteView):
    model = FuneralClientProfile
    template_name = 'delete.html'
    success_url = reverse_lazy('funeral_client_profile_list')
    permission_required = 'delete_funeralclientprofile'

    def post(self, request, *args, **kwargs):
        data = {}
        try:
            self.get_object().delete()
        except Exception as e:
            data['error'] = str(e)
        return HttpResponse(json.dumps(data), content_type='application/json')

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['title'] = 'Eliminación de la clasificación de un cliente'
        context['list_url'] = self.success_url
        context['module_name'] = MODULE_NAME
        return context
