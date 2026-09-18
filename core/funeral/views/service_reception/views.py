import json

from django.db import transaction
from django.http import HttpResponse
from django.urls import reverse_lazy
from django.views.generic import TemplateView, DeleteView, UpdateView

from core.funeral.forms import ServiceReceptionForm, ServiceReceptionDetailFormSet
from core.funeral.models import (
    ServiceType,
    ClientServiceRate,
    FuneralClientProfile,
    ServiceReception,
    ServiceReceptionDetail,
    DEATH_PLACE_CHOICES,
    DISPOSITION_TYPE_CHOICES,
)
from core.pos.models import Client, Municipio
from core.security.mixins import GroupPermissionMixin

MODULE_NAME = 'Recepción de servicios'


class ServiceReceptionWizardView(GroupPermissionMixin, TemplateView):
    template_name = 'service_reception/wizard.html'
    permission_required = 'add_servicereception'

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['title'] = 'Recepción de servicios'
        context['module_name'] = MODULE_NAME
        context['service_types'] = ServiceType.objects.filter(is_active=True)
        context['municipios'] = Municipio.objects.select_related('departamento').order_by('departamento__nombre', 'nombre')
        context['death_place_choices'] = DEATH_PLACE_CHOICES
        context['disposition_type_choices'] = DISPOSITION_TYPE_CHOICES
        return context

    def post(self, request, *args, **kwargs):
        data = {}
        action = request.POST.get('action')
        try:
            if action == 'get_clients':
                data = self.get_clients(request)
            elif action == 'get_client_rates':
                data = self.get_client_rates(request)
            elif action == 'save':
                data = self.save_reception(request)
            else:
                data['error'] = 'No ha seleccionado ninguna opción'
        except Exception as e:
            data['error'] = str(e)
        return HttpResponse(json.dumps(data), content_type='application/json')

    def get_clients(self, request):
        service_type_id = request.POST.get('service_type')
        clients = Client.objects.filter(
            funeral_profile__service_type_id=service_type_id,
            is_active=True,
        ).order_by('names')
        return [c.toJSON() for c in clients]

    def get_client_rates(self, request):
        client_id = request.POST.get('client')
        rates = ClientServiceRate.objects.filter(client_id=client_id, is_active=True).select_related('product')
        return [r.toJSON() for r in rates]

    @transaction.atomic
    def save_reception(self, request):
        post = request.POST
        service_type_id = post.get('service_type')
        client_id = post.get('client')
        deceased_name = post.get('deceased_name', '').strip()

        if not service_type_id or not client_id:
            return {'error': 'Debe seleccionar el tipo de servicio y el cliente'}
        if not deceased_name:
            return {'error': 'El nombre del fallecido es obligatorio'}

        service_type = ServiceType.objects.get(pk=service_type_id)
        client = Client.objects.get(pk=client_id)

        reception = ServiceReception.objects.create(
            service_type=service_type,
            client=client,
            contact_1_name=post.get('contact_1_name') or None,
            contact_1_phone=post.get('contact_1_phone') or None,
            contact_2_name=post.get('contact_2_name') or None,
            contact_2_phone=post.get('contact_2_phone') or None,
            authorized_by=post.get('authorized_by') or None,
            deceased_name=deceased_name,
            deceased_document=post.get('deceased_document') or None,
            death_certificate_number=post.get('death_certificate_number') or None,
            death_city_id=post.get('death_city') or None,
            death_place=post.get('death_place') or None,
            final_destination_city_id=post.get('final_destination_city') or None,
            disposition_type=post.get('disposition_type') or None,
        )

        rate_ids = post.getlist('rate_ids[]')
        authorization_numbers = post.getlist('authorization_numbers[]')
        rates_by_id = {str(r.id): r for r in ClientServiceRate.objects.filter(id__in=rate_ids, client=client)}
        for index, rate_id in enumerate(rate_ids):
            rate = rates_by_id.get(rate_id)
            if not rate:
                continue
            authorization_number = authorization_numbers[index].strip() if index < len(authorization_numbers) else ''
            ServiceReceptionDetail.objects.create(
                reception=reception,
                product=rate.product,
                price=rate.price,
                authorization_number=authorization_number or None,
            )

        return reception.toJSON()


class ServiceReceptionListView(GroupPermissionMixin, TemplateView):
    template_name = 'service_reception/list.html'
    permission_required = 'view_servicereception'

    def post(self, request, *args, **kwargs):
        data = {}
        action = request.POST.get('action')
        try:
            if action == 'search':
                data = [r.toJSON() for r in ServiceReception.objects.select_related('client', 'service_type').all()]
            else:
                data['error'] = 'No ha seleccionado ninguna opción'
        except Exception as e:
            data['error'] = str(e)
        return HttpResponse(json.dumps(data), content_type='application/json')

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['title'] = 'Listado de Recepciones de servicio'
        context['list_url'] = reverse_lazy('service_reception_list')
        context['create_url'] = reverse_lazy('service_reception_wizard')
        context['module_name'] = MODULE_NAME
        return context


class ServiceReceptionUpdateView(GroupPermissionMixin, UpdateView):
    template_name = 'service_reception/edit.html'
    model = ServiceReception
    form_class = ServiceReceptionForm
    success_url = reverse_lazy('service_reception_list')
    permission_required = 'change_servicereception'

    def dispatch(self, request, *args, **kwargs):
        self.object = self.get_object()
        return super().dispatch(request, *args, **kwargs)

    def post(self, request, *args, **kwargs):
        data = {}
        action = request.POST.get('action')
        try:
            if action == 'edit':
                form = self.form_class(request.POST, instance=self.object)
                details_formset = ServiceReceptionDetailFormSet(request.POST, instance=self.object)

                if form.is_valid() and details_formset.is_valid():
                    with transaction.atomic():
                        reception = form.save()
                        details_formset.instance = reception
                        details_formset.save()
                    data = reception.toJSON()
                else:
                    errors = dict(form.errors.items())
                    if details_formset.errors:
                        errors['formset'] = details_formset.errors
                    data['error'] = errors
            else:
                data['error'] = 'No ha seleccionado ninguna opción'
        except Exception as e:
            data['error'] = str(e)
        return HttpResponse(json.dumps(data), content_type='application/json')

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['title'] = 'Edición de una Recepción de servicio'
        context['list_url'] = self.success_url
        context['action'] = 'edit'
        context['module_name'] = MODULE_NAME
        if self.request.POST:
            context['details_formset'] = ServiceReceptionDetailFormSet(self.request.POST, instance=self.object)
        else:
            context['details_formset'] = ServiceReceptionDetailFormSet(instance=self.object)
        return context


class ServiceReceptionDeleteView(GroupPermissionMixin, DeleteView):
    model = ServiceReception
    template_name = 'delete.html'
    success_url = reverse_lazy('service_reception_list')
    permission_required = 'delete_servicereception'

    def post(self, request, *args, **kwargs):
        data = {}
        try:
            self.get_object().delete()
        except Exception as e:
            data['error'] = str(e)
        return HttpResponse(json.dumps(data), content_type='application/json')

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['title'] = 'Eliminación de una Recepción de servicio'
        context['list_url'] = self.success_url
        context['module_name'] = MODULE_NAME
        return context
