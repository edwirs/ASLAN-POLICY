from django import forms
from django.forms import inlineformset_factory

from core.funeral.models import (
    ServiceType,
    ClientServiceRate,
    FuneralClientProfile,
    ServiceReception,
    ServiceReceptionDetail,
)


class ServiceTypeForm(forms.ModelForm):
    class Meta:
        model = ServiceType
        fields = '__all__'
        widgets = {
            'code': forms.TextInput(attrs={'class': 'form-control'}),
            'name': forms.TextInput(attrs={'class': 'form-control'}),
            'description': forms.TextInput(attrs={'class': 'form-control'}),
            'is_active': forms.CheckboxInput(attrs={'class': 'form-check-input'}),
        }


class ClientServiceRateForm(forms.ModelForm):
    class Meta:
        model = ClientServiceRate
        fields = '__all__'
        widgets = {
            'client': forms.Select(attrs={'class': 'form-control select2', 'style': 'width: 100%;'}),
            'service_type': forms.Select(attrs={'class': 'form-control select2', 'style': 'width: 100%;'}),
            'product': forms.Select(attrs={'class': 'form-control select2', 'style': 'width: 100%;'}),
            'price': forms.TextInput(attrs={'name': 'price'}),
            'is_active': forms.CheckboxInput(attrs={'class': 'form-check-input'}),
        }


class FuneralClientProfileForm(forms.ModelForm):
    class Meta:
        model = FuneralClientProfile
        fields = '__all__'
        widgets = {
            'client': forms.Select(attrs={'class': 'form-control select2', 'style': 'width: 100%;'}),
            'service_type': forms.Select(attrs={'class': 'form-control select2', 'style': 'width: 100%;'}),
        }


class ServiceReceptionForm(forms.ModelForm):
    class Meta:
        model = ServiceReception
        exclude = ['created_at']
        widgets = {
            'client': forms.Select(attrs={'class': 'form-control select2', 'style': 'width: 100%;'}),
            'service_type': forms.Select(attrs={'class': 'form-control select2', 'style': 'width: 100%;'}),
            'contact_1_name': forms.TextInput(attrs={'class': 'form-control'}),
            'contact_1_phone': forms.TextInput(attrs={'class': 'form-control'}),
            'contact_2_name': forms.TextInput(attrs={'class': 'form-control'}),
            'contact_2_phone': forms.TextInput(attrs={'class': 'form-control'}),
            'authorized_by': forms.TextInput(attrs={'class': 'form-control'}),
            'deceased_name': forms.TextInput(attrs={'class': 'form-control'}),
            'deceased_document': forms.TextInput(attrs={'class': 'form-control'}),
            'death_certificate_number': forms.TextInput(attrs={'class': 'form-control'}),
            'death_city': forms.Select(attrs={'class': 'form-control select2', 'style': 'width: 100%;'}),
            'death_place': forms.Select(attrs={'class': 'form-control select2', 'style': 'width: 100%;'}),
            'final_destination_city': forms.Select(attrs={'class': 'form-control select2', 'style': 'width: 100%;'}),
            'disposition_type': forms.Select(attrs={'class': 'form-control select2', 'style': 'width: 100%;'}),
        }


ServiceReceptionDetailFormSet = inlineformset_factory(
    ServiceReception,
    ServiceReceptionDetail,
    fields=('authorization_number',),
    extra=0,
    can_delete=False,
    widgets={
        'authorization_number': forms.TextInput(attrs={
            'class': 'form-control',
            'placeholder': 'Número de autorización (opcional)'
        }),
    },
)
