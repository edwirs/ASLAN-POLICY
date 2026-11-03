from django import forms
from datetime import date, timedelta
from django.forms import inlineformset_factory

from .models import *


class CategoryForm(forms.ModelForm):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['name'].widget.attrs['autofocus'] = True

    class Meta:
        model = Category
        fields = '__all__'
        widgets = {
            'name': forms.TextInput(attrs={'placeholder': 'Ingrese un nombre'}),
            'description': forms.Textarea(attrs={
                'rows': 3,
                'cols': 3,
                'placeholder': 'Ingrese una descripción'
            }),
        }

    def save(self, commit=True):
        data = {}
        try:
            if self.is_valid():
                super().save()
            else:
                data['error'] = self.errors
        except Exception as e:
            data['error'] = str(e)
        return data


class ProductForm(forms.ModelForm):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['name'].widget.attrs['autofocus'] = True

    class Meta:
        model = Product
        fields = '__all__'
        widgets = {
            'name': forms.TextInput(attrs={'class': 'form-control','placeholder': 'Ingrese un nombre'}),
            'code': forms.TextInput(attrs={'class': 'form-control','placeholder': 'Ingrese un código'}),
            'barcode': forms.TextInput(attrs={'class': 'form-control','placeholder': 'Escanee o ingrese código de barras'}),
            'description': forms.Textarea(attrs={'class': 'form-control','rows': 1,'placeholder': 'Ingrese una descripción', 'rows': 3, 'cols': 3}),
            'category': forms.Select(attrs={'class': 'form-control select2', 'style': 'width: 100%;'}),
            'price': forms.TextInput(attrs={'name': 'price'}),
            'pvp': forms.TextInput(attrs={'name': 'pvp'}),
            'stock': forms.TextInput(attrs={'name': 'stock'}),
            'is_service': forms.CheckboxInput(attrs={'class': 'form-check-input', 'name': 'is_service'}),
            'with_tax': forms.CheckboxInput(attrs={'class': 'form-check-input'}),
            'is_active': forms.CheckboxInput(attrs={'class': 'form-check-input'})
        }

    def save(self, commit=True):
        data = {}
        try:
            if self.is_valid():
                super().save()
            else:
                data['error'] = self.errors
        except Exception as e:
            data['error'] = str(e)
        return data


class CompanyForm(forms.ModelForm):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['name'].widget.attrs['autofocus'] = True

    class Meta:
        model = Company
        fields = '__all__'
        widgets = {
            'name': forms.TextInput(attrs={'placeholder': 'Ingrese un nombre de razón social'}),
            'ruc': forms.TextInput(attrs={'placeholder': 'Ingrese un ruc'}),
            'address': forms.TextInput(attrs={'placeholder': 'Ingrese una dirección'}),
            'mobile': forms.TextInput(attrs={'placeholder': 'Ingrese un teléfono celular'}),
            'phone': forms.TextInput(attrs={'placeholder': 'Ingrese un teléfono convencional'}),
            'email': forms.TextInput(attrs={'placeholder': 'Ingrese un email'}),
            'website': forms.TextInput(attrs={'placeholder': 'Ingrese una dirección web'}),
            'description': forms.TextInput(attrs={'placeholder': 'Ingrese una descripción'}),
            'iva': forms.TextInput(),
            'is_active': forms.CheckboxInput(attrs={'class': 'form-check-input'}),
            'enable_barcode_reader': forms.CheckboxInput(attrs={'class': 'form-check-input'})
        }

    def save(self, commit=True):
        data = {}
        try:
            if self.is_valid():
                super().save()
            else:
                data['error'] = self.errors
        except Exception as e:
            data['error'] = str(e)
        return data


class ClientForm(forms.ModelForm):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['names'].widget.attrs['autofocus'] = True

    class Meta:
        model = Client
        fields = '__all__'
        widgets = {
            'document_type': forms.Select(attrs={
                'class': 'form-control select2',
                'style': 'width: 100%'
            }),
            'dni': forms.TextInput(attrs={
                'class': 'form-control',
                'placeholder': 'Número de identificación'
            }),
            'dv': forms.TextInput(attrs={
                'class': 'form-control text-center',
                'placeholder': 'DV'
            }),
            'person_type': forms.Select(attrs={
                'class': 'form-control select2',
                'style': 'width: 100%'
            }),
            'tax_responsibility': forms.Select(attrs={
                'class': 'form-control select2',
                'style': 'width: 100%'
            }),
            'names': forms.TextInput(attrs={
                'class': 'form-control',
                'placeholder': 'Nombres y apellidos'
            }),
            'commercial_name': forms.TextInput(attrs={
                'class': 'form-control',
                'placeholder': 'Nombre comercial (Opcional)'
            }),
            'gender': forms.Select(attrs={
                'class': 'form-control select2',
                'style': 'width: 100%'
            }),
            'birthdate': forms.DateInput(format='%Y-%m-%d', attrs={
                'class': 'form-control datetimepicker-input',
                'id': 'birthdate',
                'value': datetime.now().strftime('%Y-%m-%d'),
                'data-toggle': 'datetimepicker',
                'data-target': '#birthdate'
            }),
            'country': forms.TextInput(attrs={
                'class': 'form-control',
                'placeholder': 'País'
            }),
            'municipality': forms.Select(attrs={
                'class': 'form-control select2',
                'style': 'width: 100%'
            }),
            'address': forms.TextInput(attrs={
                'class': 'form-control',
                'placeholder': 'Dirección'
            }),
            'mobile': forms.TextInput(attrs={
                'class': 'form-control',
                'placeholder': 'Número celular'
            }),
            'phone': forms.TextInput(attrs={
                'class': 'form-control',
                'placeholder': 'Opcional',
                'inputmode': 'tel'
            }),
            'email_secundario': forms.EmailInput(attrs={
                'class': 'form-control',
                'placeholder': 'Opcional'
            }),
            'email': forms.TextInput(attrs={
                'class': 'form-control',
                'placeholder': 'Correo electrónico'
            }),
            'propietario_documento': forms.TextInput(attrs={
                'class': 'form-control',
                'placeholder': 'Opcional',
                'inputmode': 'numeric'
            }),
            'propietario_nombre': forms.TextInput(attrs={
                'class': 'form-control',
                'placeholder': 'Opcional'
            }),
            'is_active': forms.CheckboxInput(attrs={
                'class': 'form-check-input'
            })
        }

    def clean(self):
        cleaned = super().clean()
        tipo = cleaned.get('document_type')
        if not (tipo and tipo.abbreviation == 'NIT'):
            # El propietario solo aplica a empresas: si no es NIT no se guarda.
            cleaned['propietario_documento'] = None
            cleaned['propietario_nombre'] = None
        return cleaned

    def save(self, commit=True):
        data = {}
        try:
            if self.is_valid():
                data = super().save().toJSON()
            else:
                data['error'] = self.errors
        except Exception as e:
            data['error'] = str(e)
        return data

ClientContactFormSet = inlineformset_factory(
    Client,
    ClientContact,
    fields=('names', 'email', 'position', 'phone'),
    extra=0, 
    can_delete=True,
    widgets={
        'names': forms.TextInput(attrs={
            'class': 'form-control', 
            'placeholder': 'Nombre del contacto'
        }),
        'email': forms.EmailInput(attrs={
            'class': 'form-control', 
            'placeholder': 'Correo electrónico'
        }),
        'position': forms.TextInput(attrs={
            'class': 'form-control', 
            'placeholder': 'Cargo (Opcional)'
        }),
        'phone': forms.TextInput(attrs={
            'class': 'form-control', 
            'placeholder': 'Teléfono (Opcional)'
        }),
    }
)
    
class ProviderForm(forms.ModelForm):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['names'].widget.attrs['autofocus'] = True

    class Meta:
        model = Provider
        fields = '__all__'
        widgets = {
            'names': forms.TextInput(attrs={'placeholder': 'Ingrese un nombre'}),
            'dni': forms.TextInput(attrs={'placeholder': 'Ingrese un número de identificación'}),
            'gender': forms.Select(attrs={
                'class': 'select2',
                'style': 'width: 100%'
            }),
            'mobile': forms.TextInput(attrs={'placeholder': 'Ingrese un teléfono celular'}),
            'email': forms.TextInput(attrs={'placeholder': 'Ingrese un email'}),
            'address': forms.TextInput(attrs={
                'placeholder': 'Ingrese una dirección'
            }),
            'is_active': forms.CheckboxInput(attrs={'class': 'form-check-input'})
        }

    def save(self, commit=True):
        data = {}
        try:
            if self.is_valid():
                data = super().save().toJSON()
            else:
                data['error'] = self.errors
        except Exception as e:
            data['error'] = str(e)
        return data


class SaleForm(forms.ModelForm):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['client'].queryset = Client.objects.none()
        if not self.instance.pk:  # solo en formularios nuevos
            self.fields['expiration_date'].initial = next_month_day_10()

    class Meta:
        model = Sale
        fields = '__all__'
        widgets = {
            'client': forms.Select(attrs={'class': 'form-select select2'}),
            'date_joined': forms.DateInput(format='%Y-%m-%d', attrs={
                'class': 'form-control datetimepicker-input',
                'id': 'date_joined',
                'value': datetime.now().strftime('%Y-%m-%d'),
                'data-toggle': 'datetimepicker',
                'data-target': '#date_joined',
                'disabled': True
            }),
            'id': forms.TextInput(attrs={
                'class': 'form-control',
                'disabled': True,
            }),
            'subtotal_0': forms.TextInput(attrs={
                'class': 'form-control',
                'disabled': True,
            }),
            'subtotal_12': forms.TextInput(attrs={
                'class': 'form-control',
                'disabled': True
            }),
            'subtotal_12_sin_iva': forms.TextInput(attrs={
                'class': 'form-control',
                'disabled': True
            }),
            'iva': forms.TextInput(attrs={
                'class': 'form-control',
                'disabled': True
            }),
            'total_iva': forms.TextInput(attrs={
                'class': 'form-control',
                'disabled': True
            }),
            'dscto': forms.TextInput(attrs={
                'class': 'form-control',
                'autocomplete': 'off'
            }),
            'total_dscto': forms.TextInput(attrs={
                'class': 'form-control',
                'disabled': True
            }),
            'total': forms.TextInput(attrs={
                'class': 'form-control',
                'disabled': True
            }),
            'cash': forms.TextInput(attrs={
                'class': 'form-control',
                'autocomplete': 'off'
            }),
            'change': forms.TextInput(attrs={
                'class': 'form-control',
                'readonly': True
            }),
            'paymentmethod': forms.Select(attrs={
                'class': 'select2',
                'style': 'width: 100%'
            }),
            'transfermethods': forms.Select(attrs={
                'class': 'select2',
                'style': 'width: 100%'
            }),
            'service_type': forms.Select(attrs={
                'class': 'select2',
                'style': 'width: 100%'
            }),
            'typemethods': forms.Select(attrs={
                'class': 'select2',
                'style': 'width: 100%'
            }),
            'expiration_date': forms.DateInput(format='%Y-%m-%d', attrs={
                'class': 'form-control datetimepicker-input',
                'id': 'expiration_date',
                'data-toggle': 'datetimepicker',
                'data-target': '#expiration_date'
            }),
            'propina': forms.TextInput(attrs={
                'class': 'form-control',
                'autocomplete': 'off'
            }),
            'nequi_value': forms.TextInput(attrs={
                'class': 'form-control',
                'autocomplete': 'off'
            }),
            'daviplata_value': forms.TextInput(attrs={
                'class': 'form-control',
                'autocomplete': 'off'
            }),
            'description': forms.Textarea(attrs={
                'class': 'form-control',
                'rows': 8,
                'placeholder': 'Observaciones de la venta...',
                'style': 'resize:none;'
            }),
        }
        
def next_month_day_10():
    today = date.today()
    future_date = today + timedelta(days=15)
    return future_date.strftime('%Y-%m-%d')


class CreditNoteForm(forms.ModelForm):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['client'].queryset = Client.objects.none()

    class Meta:
        model = CreditNote
        fields = '__all__'
        widgets = {
            'client': forms.Select(attrs={'class': 'form-select select2'}),
            'operation_type': forms.Select(attrs={
                'class': 'select2',
                'style': 'width: 100%'
            }),
            'correction_concept': forms.Select(attrs={
                'class': 'select2',
                'style': 'width: 100%'
            }),
            'date_joined': forms.DateInput(format='%Y-%m-%d', attrs={
                'class': 'form-control datetimepicker-input',
                'id': 'date_joined',
                'value': datetime.now().strftime('%Y-%m-%d'),
                'data-toggle': 'datetimepicker',
                'data-target': '#date_joined',
                'disabled': True
            }),
            'billing_period_start_date': forms.DateInput(format='%Y-%m-%d', attrs={
                'class': 'form-control datetimepicker-input',
                'id': 'billing_period_start_date',
                'data-toggle': 'datetimepicker',
                'data-target': '#billing_period_start_date',
                'autocomplete': 'off'
            }),
            'billing_period_end_date': forms.DateInput(format='%Y-%m-%d', attrs={
                'class': 'form-control datetimepicker-input',
                'id': 'billing_period_end_date',
                'data-toggle': 'datetimepicker',
                'data-target': '#billing_period_end_date',
                'autocomplete': 'off'
            }),
            'reference_bill_number': forms.TextInput(attrs={
                'class': 'form-control',
                'autocomplete': 'off',
                'placeholder': 'Ingrese el número de la factura...'
            }),
            'reference_cufe': forms.TextInput(attrs={
                'class': 'form-control',
                'readonly': True,
                'placeholder': 'CUFE de la factura...'
            }),
            'subtotal_0': forms.TextInput(attrs={
                'class': 'form-control',
                'disabled': True,
            }),
            'subtotal_12': forms.TextInput(attrs={
                'class': 'form-control',
                'disabled': True
            }),
            'subtotal_12_sin_iva': forms.TextInput(attrs={
                'class': 'form-control',
                'disabled': True
            }),
            'iva': forms.TextInput(attrs={
                'class': 'form-control',
                'disabled': True
            }),
            'total_iva': forms.TextInput(attrs={
                'class': 'form-control',
                'disabled': True
            }),
            'dscto': forms.TextInput(attrs={
                'class': 'form-control',
                'autocomplete': 'off'
            }),
            'total_dscto': forms.TextInput(attrs={
                'class': 'form-control',
                'disabled': True
            }),
            'total': forms.TextInput(attrs={
                'class': 'form-control',
                'disabled': True
            }),
            'paymentmethod': forms.Select(attrs={
                'class': 'select2',
                'style': 'width: 100%'
            }),
            'transfermethods': forms.Select(attrs={
                'class': 'select2',
                'style': 'width: 100%'
            }),
            'typemethods': forms.Select(attrs={
                'class': 'select2',
                'style': 'width: 100%'
            }),
            'expiration_date': forms.DateInput(format='%Y-%m-%d', attrs={
                'class': 'form-control datetimepicker-input',
                'id': 'expiration_date',
                'data-toggle': 'datetimepicker',
                'data-target': '#expiration_date'
            }),
            'nequi_value': forms.TextInput(attrs={
                'class': 'form-control',
                'autocomplete': 'off'
            }),
            'daviplata_value': forms.TextInput(attrs={
                'class': 'form-control',
                'autocomplete': 'off'
            }),
            'description': forms.Textarea(attrs={
                'class': 'form-control',
                'rows': 8,
                'placeholder': 'Observaciones de la nota crédito...',
                'style': 'resize:none;'
            }),
        }

class PriceForm(forms.ModelForm):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['client'].queryset = Client.objects.none()

    class Meta:
        model = Sale
        fields = '__all__'
        widgets = {
            'client': forms.Select(attrs={'class': 'form-select select2'}),
            'date_joined': forms.DateInput(format='%Y-%m-%d', attrs={
                'class': 'form-control datetimepicker-input',
                'id': 'date_joined',
                'value': datetime.now().strftime('%Y-%m-%d'),
                'data-toggle': 'datetimepicker',
                'data-target': '#date_joined'
            }),
            'subtotal_0': forms.TextInput(attrs={
                'class': 'form-control',
                'disabled': True
            }),
            'subtotal_12': forms.TextInput(attrs={
                'class': 'form-control',
                'disabled': True
            }),
            'iva': forms.TextInput(attrs={
                'class': 'form-control',
                'disabled': True
            }),
            'total_iva': forms.TextInput(attrs={
                'class': 'form-control',
                'disabled': True
            }),
            'dscto': forms.TextInput(attrs={
                'class': 'form-control',
                'autocomplete': 'off'
            }),
            'total_dscto': forms.TextInput(attrs={
                'class': 'form-control',
                'disabled': True
            }),
            'total': forms.TextInput(attrs={
                'class': 'form-control',
                'disabled': True
            }),
            'cash': forms.TextInput(attrs={
                'class': 'form-control',
                'autocomplete': 'off'
            }),
            'change': forms.TextInput(attrs={
                'class': 'form-control',
                'readonly': True
            }),
            'paymentmethod': forms.Select(attrs={
                'class': 'select2',
                'style': 'width: 100%'
            }),
        }

class BuyForm(forms.ModelForm):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['provider'].queryset = Provider.objects.none()

    class Meta:
        model = Buy
        fields = '__all__'
        widgets = {
            'provider': forms.Select(attrs={'class': 'form-select select2'}),
            'date_joined': forms.DateInput(format='%Y-%m-%d', attrs={
                'class': 'form-control datetimepicker-input',
                'id': 'date_joined',
                'value': datetime.now().strftime('%Y-%m-%d'),
                'data-toggle': 'datetimepicker',
                'data-target': '#date_joined'
            }),
            'subtotal_0': forms.TextInput(attrs={
                'class': 'form-control',
                'disabled': True
            }),
            'subtotal_12': forms.TextInput(attrs={
                'class': 'form-control',
                'disabled': True
            }),
            'iva': forms.TextInput(attrs={
                'class': 'form-control',
                'disabled': True
            }),
            'total_iva': forms.TextInput(attrs={
                'class': 'form-control',
                'disabled': True
            }),
            'dscto': forms.TextInput(attrs={
                'class': 'form-control',
                'autocomplete': 'off'
            }),
            'total_dscto': forms.TextInput(attrs={
                'class': 'form-control',
                'disabled': True
            }),
            'total': forms.TextInput(attrs={
                'class': 'form-control',
                'disabled': True
            }),
            'cash': forms.TextInput(attrs={
                'class': 'form-control',
                'autocomplete': 'off'
            }),
            'change': forms.TextInput(attrs={
                'class': 'form-control',
                'readonly': True
            }),
            'paymentmethod': forms.Select(attrs={
                'class': 'select2',
                'style': 'width: 100%'
            }),
        }

class ProductAutoAddForm(forms.ModelForm):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

    class Meta:
        model = ProductAutoAdd
        fields = '__all__'
        widgets = {
            'trigger_product': forms.Select(
                attrs={'class': 'form-control select2', 'style': 'width: 100%;'}
            ),
            'auto_product': forms.Select(
                attrs={'class': 'form-control select2', 'style': 'width: 100%;'}
            ),
            'quantity': forms.TextInput(
                attrs={
                    'class': 'form-control touchspin',
                    'autocomplete': 'off',
                    'step': '0.01',   # permite 2 decimales
                    'min': '0'
                }
            ),
        }

    def save(self, commit=True):
        data = {}
        try:
            if self.is_valid():
                super().save()
            else:
                data['error'] = self.errors
        except Exception as e:
            data['error'] = str(e)
        return data
    
class ExpensesForm(forms.ModelForm):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

    class Meta:
        model = Expenses
        fields = '__all__'
        exclude = ['user'] 
        widgets = {
            'source': forms.Select(
                attrs={'class': 'form-control select2', 'style': 'width: 100%;'}
            ),
            'created_at': forms.DateInput(format='%Y-%m-%d', attrs={
                'class': 'form-control datetimepicker-input',
                'id': 'created_at',
                'value': datetime.now().strftime('%Y-%m-%d'),
                'data-toggle': 'datetimepicker',
                'data-target': '#created_at'
            }),
            'amount': forms.TextInput(
                attrs={
                    'class': 'form-control touchspin',
                    'autocomplete': 'off',
                    'step': '0.01',   # permite 2 decimales
                    'min': '0'
                }
            ),
            'description': forms.Textarea(attrs={
                'rows': 4,
                'class': 'form-control w-100',
                'placeholder': 'Ingrese una descripción'
            }),
            'reason': forms.TextInput(attrs={
                'class': 'form-control',
            }),
        }

class EmployeeForm(forms.ModelForm):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        #self.fields['names'].widget.attrs['autofocus'] = True

    class Meta:
        model = Employee
        fields = '__all__'
        widgets = {
            'dni': forms.TextInput(attrs={'class': 'form-control','placeholder': 'Ingrese la identificación'}),
            'names': forms.TextInput(attrs={'class': 'form-control','placeholder': 'Ingrese los nombres'}),
            'email': forms.TextInput(attrs={'class': 'form-control','placeholder': 'Ingrese un correo'}),
            'phone': forms.TextInput(attrs={'class': 'form-control','placeholder': 'Ingrese telefono'}),
            'address': forms.TextInput(attrs={'class': 'form-control','placeholder': 'Ingrese una dirección'}),
            'birth_date': forms.DateInput(format='%Y-%m-%d', attrs={
                'class': 'form-control datetimepicker-input',
                'id': 'birth_date',
                'value': datetime.now().strftime('%Y-%m-%d'),
                'data-toggle': 'datetimepicker',
                'data-target': '#birth_date'
            }),
            'contract_type': forms.Select(attrs={
                'class': 'select2',
                'style': 'width: 100%'
            }),
            'start_date': forms.DateInput(format='%Y-%m-%d', attrs={
                'class': 'form-control datetimepicker-input',
                'id': 'start_date',
                'value': datetime.now().strftime('%Y-%m-%d'),
                'data-toggle': 'datetimepicker',
                'data-target': '#start_date'
            }),
            'retire_date': forms.DateInput(format='%Y-%m-%d', attrs={
                'class': 'form-control datetimepicker-input',
                'id': 'retire_date',
                #'value': datetime.now().strftime('%Y-%m-%d'),
                'data-toggle': 'datetimepicker',
                'data-target': '#retire_date'
            }),
            'salary': forms.TextInput(attrs={'name': 'salary'}),
            'base_salary': forms.TextInput(attrs={'name': 'base_salary'}),
            'eps': forms.TextInput(attrs={'class': 'form-control','placeholder': 'Ingrese una EPS'}),
            'afp': forms.TextInput(attrs={'class': 'form-control','placeholder': 'Ingrese un fondo de pensiones'}),
            'arl': forms.TextInput(attrs={'class': 'form-control','placeholder': 'Ingrese una ARL'}),
            'caja_compensacion': forms.TextInput(attrs={'class': 'form-control','placeholder': 'Ingrese CCF'}),
            'social_security': forms.CheckboxInput(attrs={'class': 'form-check-input', 'name': 'social_security'}),
            'is_active': forms.CheckboxInput(attrs={'class': 'form-check-input', 'name': 'is_active'})
        }

    def save(self, commit=True):
        data = {}
        try:
            if self.is_valid():
                super().save()
            else:
                data['error'] = self.errors
        except Exception as e:
            data['error'] = str(e)
        return data
    
class PayrollForm(forms.ModelForm):
    class Meta:
        model = Payroll
        fields = [
            'employee',
            'period',
            'period_type',
            'days_worked',
            'overtime_hours_value',
            'other_earnings',
            'deductions'
        ]
        widgets = {
            'employee': forms.Select(attrs={'class': 'form-control select2', 'style': 'width: 100%;'}),
            'period_type': forms.Select(attrs={'class': 'form-control select2', 'style': 'width: 100%;'}),
            'period': forms.DateInput(format='%Y-%m-%d', attrs={
                'class': 'form-control datetimepicker-input',
                'id': 'period',
                #'value': datetime.now().strftime('%Y-%m-%d'),
                'data-toggle': 'datetimepicker',
                'data-target': '#period'
            }),
        }

class BarForm(forms.ModelForm):
    def __init__(self, *args, **kwargs):
        user = kwargs.pop('user', None) 
        super().__init__(*args, **kwargs)

        self.fields['client'].queryset = Client.objects.none()

        # Ordenar alfabéticamente por nombre (ajusta al campo correcto)
        self.fields['employee'].queryset = User.objects.all().order_by('names')
        
        if user and user.has_perm('pos.list_employee'):  # cambia al permiso real
            self.fields['employee'].initial = user.pk  # o user.id

    class Meta:
        model = Sale
        fields = '__all__'
        widgets = {
            'client': forms.Select(attrs={'class': 'form-select select2'}),
            'date_joined': forms.DateInput(format='%Y-%m-%d', attrs={
                'class': 'form-control datetimepicker-input',
                'id': 'date_joined',
                'value': datetime.now().strftime('%Y-%m-%d'),
                'data-toggle': 'datetimepicker',
                'data-target': '#date_joined',
                'disabled': True
            }),
            'subtotal_0': forms.TextInput(attrs={
                'class': 'form-control',
                'disabled': True,
            }),
            'subtotal_12': forms.TextInput(attrs={
                'class': 'form-control',
                'disabled': True
            }),
            'iva': forms.TextInput(attrs={
                'class': 'form-control',
                'disabled': True
            }),
            'total_iva': forms.TextInput(attrs={
                'class': 'form-control',
                'disabled': True
            }),
            'dscto': forms.TextInput(attrs={
                'class': 'form-control',
                'autocomplete': 'off'
            }),
            'total_dscto': forms.TextInput(attrs={
                'class': 'form-control',
                'disabled': True
            }),
            'total': forms.TextInput(attrs={
                'class': 'form-control fw-bold',
                'disabled': True,
                'style': 'font-size: 30px;'
            }),
            'cash': forms.TextInput(attrs={
                'class': 'form-control',
                'autocomplete': 'off'
            }),
            'change': forms.TextInput(attrs={
                'class': 'form-control',
                'readonly': True
            }),
            'paymentmethod': forms.Select(attrs={
                'class': 'select2',
                'style': 'width: 100%'
            }),
            'transfermethods': forms.Select(attrs={
                'class': 'select2',
                'style': 'width: 100%'
            }),
            'autorization_discount': forms.Select(attrs={
                'class': 'select2',
                'style': 'width: 100%'
            }),
            'discount_value': forms.TextInput(attrs={
                'class': 'form-control'
            }),
            'employee': forms.Select(attrs={
                'class': 'form-select select2',
                'style': 'width: 100%'
            }),
            'description': forms.Textarea(attrs={
                'class': 'form-control',
                'placeholder': 
                'Ingrese una descripción', 
                'rows': 2, 
                'cols': 3
            }),
        }

class InventoryGroupForm(forms.ModelForm):
    class Meta:
        model = InventoryGroup
        fields = ['name']

class UserInventoryGroupForm(forms.ModelForm):
    class Meta:
        model = UserInventoryGroup
        fields = ['user', 'group']

class ProductInventoryGroupStockForm(forms.ModelForm):
    class Meta:
        model = ProductInventoryGroupStock
        fields = ['product', 'group', 'stock']

class ProductAutoAddForm(forms.ModelForm):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

    class Meta:
        model = ProductAutoAdd
        fields = '__all__'
        widgets = {
            'trigger_product': forms.Select(
                attrs={'class': 'form-control select2', 'style': 'width: 100%;'}
            ),
            'auto_product': forms.Select(
                attrs={'class': 'form-control select2', 'style': 'width: 100%;'}
            ),
            'quantity': forms.TextInput(
                attrs={
                    'class': 'form-control touchspin',
                    'autocomplete': 'off',
                    'step': '0.01',   # permite 2 decimales
                    'min': '0'
                }
            ),
        }

    def save(self, commit=True):
        data = {}
        try:
            if self.is_valid():
                super().save()
            else:
                data['error'] = self.errors
        except Exception as e:
            data['error'] = str(e)
        return data

class TableForm(forms.ModelForm):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['name'].widget.attrs['autofocus'] = True

    class Meta:
        model = Table
        fields = '__all__'
        widgets = {
            'name': forms.TextInput(attrs={'placeholder': 'Ingrese un nombre'}),
        }

    def save(self, commit=True):
        data = {}
        try:
            if self.is_valid():
                super().save()
            else:
                data['error'] = self.errors
        except Exception as e:
            data['error'] = str(e)
        return data

class OrderBarraForm(forms.ModelForm):
    class Meta:
        model = Order
        fields = ['total', 'observations']
        widgets = {
            'total': forms.TextInput(attrs={
                'class': 'form-control fw-bold',
                'disabled': True,
                'style': 'font-size: 30px;'
            }),
            'observations': forms.Textarea(attrs={
                'class': 'form-control',
                'rows': 2,
                'placeholder': 'Ej: Sin cebolla, término medio, cumpleaños, etc.'
            }),
        }

class EmployeeTransactionForm(forms.ModelForm):

    def __init__(self, *args, **kwargs):
        self.request = kwargs.pop('request', None)
        super().__init__(*args, **kwargs)

        self.fields['employee'].widget.attrs['autofocus'] = True
        self.fields['employee'].queryset = Employee.objects.filter(is_active=True)

    class Meta:
        model = EmployeeTransaction
        fields = [
            'employee',
            'transaction_type',
            'source',
            'amount',
            'description',
            'is_paid'
        ]

        widgets = {

            'employee': forms.Select(attrs={
                'class': 'select2',
                'style': 'width:100%'
            }),

            'transaction_type': forms.Select(attrs={
                'class': 'select2',
                'style': 'width:100%'
            }),

            'source': forms.Select(attrs={
                'class': 'select2',
                'style': 'width:100%'
            }),

            'amount': forms.NumberInput(attrs={
                'class': 'form-control',
                'placeholder': 'Ingrese valor'
            }),

            'description': forms.Textarea(attrs={
                'class': 'form-control',
                'rows': 3,
                'placeholder': 'Observación (opcional)'
            }),

            'is_paid': forms.CheckboxInput(attrs={
                'class': 'form-check-input'
            }),
        }

    def clean(self):
        cleaned = super().clean()
        amount = cleaned.get("amount")

        if amount is not None and amount <= 0:
            raise forms.ValidationError("El monto debe ser mayor a 0.")

        return cleaned

    def save(self, commit=True):
        instance = super().save(commit=False)

        # usuario que registra
        if self.request:
            instance.created_by = self.request.user

        # saldo inicial
        if not instance.balance:
            instance.balance = instance.amount

        if commit:
            instance.save()

        return instance

class CashClosingForm(forms.ModelForm):

    real_cash = forms.DecimalField(
        max_digits=10,
        decimal_places=2,
        label='Efectivo real en caja',
        widget=forms.TextInput(
            attrs={
                'class': 'form-control',
                'placeholder': 'Ingrese el efectivo contado',
                'step': '0.01',
                'autocomplete': 'off'
            }
        )
    )

    observations = forms.CharField(
        required=False,
        label='Observaciones',
        widget=forms.Textarea(
            attrs={
                'class': 'form-control',
                'rows': 3,
                'placeholder': 'Observaciones del cierre'
            }
        )
    )

    class Meta:
        model = CashClosing
        fields = [
            'real_cash',
            'observations'
        ]

    def save(self, commit=True):
        data = {}

        try:
            if self.is_valid():
                data = super().save(commit=False)

                # calcular diferencia
                data.difference = data.real_cash - data.expected_cash

                if commit:
                    data.save()
            else:
                data['error'] = self.errors

        except Exception as e:
            data['error'] = str(e)

        return data


class FactusCredentialForm(forms.ModelForm):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['name'].widget.attrs['autofocus'] = True
        # Al editar, no se re-piden ni se muestran los secretos en texto plano;
        # si se dejan vacíos se conservan los valores ya guardados.
        if self.instance.pk:
            self.fields['client_secret'].required = False
            self.fields['password'].required = False

    class Meta:
        model = FactusCredential
        fields = '__all__'
        widgets = {
            'name': forms.TextInput(attrs={
                'class': 'form-control',
                'placeholder': 'Ej: Producción, Sandbox de pruebas'
            }),
            'environment': forms.Select(attrs={'class': 'form-control select2', 'style': 'width: 100%'}),
            'api_url': forms.URLInput(attrs={'class': 'form-control', 'placeholder': 'https://api.factus.com.co'}),
            'client_id': forms.TextInput(attrs={'class': 'form-control', 'autocomplete': 'off'}),
            'client_secret': forms.PasswordInput(attrs={'class': 'form-control', 'autocomplete': 'new-password'}, render_value=False),
            'username': forms.TextInput(attrs={'class': 'form-control', 'autocomplete': 'off'}),
            'password': forms.PasswordInput(attrs={'class': 'form-control', 'autocomplete': 'new-password'}, render_value=False),
        }

    def save(self, commit=True):
        data = {}
        try:
            if self.is_valid():
                instance = super().save(commit=False)
                # Si se dejaron en blanco al editar, se conserva lo guardado.
                if self.instance.pk:
                    if not self.cleaned_data.get('client_secret'):
                        instance.client_secret = FactusCredential.objects.get(pk=self.instance.pk).client_secret
                    if not self.cleaned_data.get('password'):
                        instance.password = FactusCredential.objects.get(pk=self.instance.pk).password
                if commit:
                    instance.save()
            else:
                data['error'] = self.errors
        except Exception as e:
            data['error'] = str(e)
        return data