from datetime import date

from django import forms

from core.policies.models import Aseguradora, AseguradoraCredencial, Asesor, CoberturaAseguradora
from core.policies.services.bots import BOTS_DISPONIBLES
from core.policies.services.coberturas import CAMPOS as CAMPOS_COBERTURA, SECCIONES as SECCIONES_COBERTURA
from core.policies.services.credenciales import campos_de, obligatorios_de
from core.pos.models import DocumentType, Municipio
from core.user.models import User


class SolicitudCotizacionForm(forms.Form):
    document_type = forms.ModelChoiceField(
        queryset=DocumentType.objects.filter(is_active=True),
        label='Tipo de documento',
        widget=forms.Select(attrs={
            'class': 'form-control select2',
            'style': 'width: 100%',
            'autofocus': True,
        })
    )
    dni = forms.CharField(
        max_length=20,
        label='Número de documento',
        widget=forms.TextInput(attrs={
            'class': 'form-control',
            'placeholder': 'Número de documento',
        })
    )
    names = forms.CharField(
        max_length=150,
        label='Nombre completo',
        widget=forms.TextInput(attrs={
            'class': 'form-control',
            'placeholder': 'Nombre y apellidos del tomador',
        })
    )
    birthdate = forms.DateField(
        label='Fecha de nacimiento',
        widget=forms.DateInput(attrs={
            'class': 'form-control',
            'type': 'date',
        })
    )
    placa = forms.CharField(
        max_length=10,
        label='Placa',
        widget=forms.TextInput(attrs={
            'class': 'form-control',
            'placeholder': 'ABC123',
            'style': 'text-transform: uppercase;',
        })
    )
    zona_circulacion = forms.ModelChoiceField(
        queryset=Municipio.objects.select_related('departamento').all(),
        label='Ciudad de circulación',
        widget=forms.Select(attrs={
            'class': 'form-control select2',
            'style': 'width: 100%',
        })
    )
    email = forms.EmailField(
        max_length=100,
        label='Correo',
        widget=forms.EmailInput(attrs={
            'class': 'form-control',
            'placeholder': 'correo@ejemplo.com',
        })
    )
    es_cero_km = forms.BooleanField(
        required=False,
        label='¿Es 0 kilómetros?',
        widget=forms.HiddenInput()
    )
    # Solo se piden cuando el vehículo es 0 km: sin historial, los portales de
    # las aseguradoras no pueden resolver el vehículo por placa.
    codigo_fasecolda = forms.CharField(
        required=False,
        max_length=20,
        label='Código Fasecolda',
        widget=forms.HiddenInput()
    )
    valor_comercial = forms.DecimalField(
        required=False,
        max_digits=14,
        decimal_places=2,
        min_value=1,
        label='Valor comercial',
        widget=forms.HiddenInput()
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        cedula = DocumentType.objects.filter(abbreviation='CC').first()
        if cedula:
            self.fields['document_type'].initial = cedula.pk

    def clean_dni(self):
        return self.cleaned_data['dni'].strip()

    def clean_placa(self):
        return self.cleaned_data['placa'].strip().upper()

    def clean_birthdate(self):
        birthdate = self.cleaned_data['birthdate']
        if birthdate > date.today():
            raise forms.ValidationError('La fecha de nacimiento no puede ser futura')
        return birthdate

    def clean_codigo_fasecolda(self):
        codigo = (self.cleaned_data.get('codigo_fasecolda') or '').strip()
        if codigo and not codigo.isdigit():
            raise forms.ValidationError('El código Fasecolda solo debe contener números')
        return codigo

    def clean(self):
        cleaned = super().clean()
        if cleaned.get('es_cero_km'):
            if not cleaned.get('codigo_fasecolda'):
                self.add_error('codigo_fasecolda', 'El código Fasecolda es obligatorio para un vehículo 0 km')
            if not cleaned.get('valor_comercial'):
                self.add_error('valor_comercial', 'El valor comercial es obligatorio para un vehículo 0 km')
        return cleaned


class AseguradoraCredencialForm(forms.ModelForm):
    """Datos de acceso al portal de una aseguradora (los usa el bot) y su estado.

    Solo muestra los campos que esa aseguradora necesita. La contraseña no se
    devuelve nunca en el HTML; si se deja vacía al editar, se conserva la guardada.
    """
    aseguradora_activa = forms.BooleanField(required=False, label='Aseguradora activa',
                                            widget=forms.CheckboxInput(attrs={'class': 'form-check-input'}))
    # Datos de la aseguradora: solo se piden al crearla (al editar se retiran del formulario).
    CAMPOS_ASEGURADORA = ('name', 'nit', 'phone', 'email')
    name = forms.CharField(max_length=150, required=False, label='Nombre de la aseguradora',
                           widget=forms.TextInput(attrs={'placeholder': 'Ej: Sura, Mapfre, Bolívar'}))
    nit = forms.CharField(max_length=20, required=False, label='NIT')
    phone = forms.CharField(max_length=20, required=False, label='Teléfono')
    email = forms.EmailField(max_length=100, required=False, label='Correo')

    class Meta:
        model = AseguradoraCredencial
        fields = ('portal_url', 'tipo_documento', 'username', 'clave_agencia', 'codigo_intermediario', 'cuenta',
                  'password', 'ramo', 'tipo_seguro', 'sucursal', 'correo_contacto', 'telefono_contacto')
        widgets = {
            'portal_url': forms.URLInput(attrs={'class': 'form-control', 'placeholder': 'https://…'}),
            'password': forms.PasswordInput(attrs={'class': 'form-control', 'autocomplete': 'new-password'}, render_value=False),
        }

    def __init__(self, *args, aseguradora, credencial=None, **kwargs):
        kwargs.setdefault('instance', credencial)
        super().__init__(*args, **kwargs)
        self.aseguradora = aseguradora
        self.es_nueva = aseguradora.pk is None
        self.fields['aseguradora_activa'].initial = aseguradora.is_active if not self.es_nueva else True
        permitidos = campos_de(aseguradora)
        obligatorios = obligatorios_de(aseguradora)
        for nombre in list(self.fields):
            if nombre in ('aseguradora_activa', *self.CAMPOS_ASEGURADORA):
                continue
            if nombre not in permitidos:
                del self.fields[nombre]
                continue
            campo = self.fields[nombre]
            if 'class' not in campo.widget.attrs:
                campo.widget.attrs['class'] = 'form-control'
            campo.widget.attrs.setdefault('autocomplete', 'off')
            campo.required = False
        if 'password' in self.fields and self.instance.pk and self.instance.password:
            self.fields['password'].widget.attrs['placeholder'] = 'Dejar vacío para conservar la actual'
        if self.es_nueva:
            for nombre in self.CAMPOS_ASEGURADORA:
                self.fields[nombre].widget.attrs.setdefault('class', 'form-control')
                self.fields[nombre].widget.attrs.setdefault('autocomplete', 'off')
            self.fields['name'].required = True
            self.fields['name'].widget.attrs['autofocus'] = True
        else:
            for nombre in self.CAMPOS_ASEGURADORA:
                del self.fields[nombre]
            self.fields['portal_url'].widget.attrs['autofocus'] = True
        # Los datos de la aseguradora (si se piden) van antes que los de acceso.
        orden = [n for n in self.CAMPOS_ASEGURADORA if n in self.fields]
        self.order_fields(orden)

    def clean_name(self):
        nombre = ' '.join((self.cleaned_data.get('name') or '').split())
        if not nombre:
            raise forms.ValidationError('Ingrese el nombre de la aseguradora.')
        if Aseguradora.objects.filter(name__iexact=nombre).exists():
            raise forms.ValidationError('Ya existe una aseguradora con ese nombre.')
        return nombre

    def clean(self):
        cleaned = super().clean()
        # Un bot sin datos de acceso completos no puede quedar activo.
        if cleaned.get('aseguradora_activa') and self.aseguradora.name in BOTS_DISPONIBLES:
            for nombre in obligatorios_de(self.aseguradora):
                if nombre not in self.fields or cleaned.get(nombre):
                    continue
                if nombre == 'password' and self.instance.pk and self.instance.password:
                    continue
                self.add_error(nombre, 'Obligatorio para dejar la aseguradora activa.')
        return cleaned

    def save(self, commit=True):
        credencial = super().save(commit=False)
        aseguradora = self.aseguradora
        if self.es_nueva:
            aseguradora.name = self.cleaned_data['name']
            aseguradora.nit = self.cleaned_data.get('nit') or None
            aseguradora.phone = self.cleaned_data.get('phone') or None
            aseguradora.email = self.cleaned_data.get('email') or None
        aseguradora.is_active = self.cleaned_data.get('aseguradora_activa', False)
        datos_acceso = [n for n in self.fields if n not in ('aseguradora_activa', *self.CAMPOS_ASEGURADORA)]
        if not self.instance.pk and not any(self.cleaned_data.get(n) for n in datos_acceso):
            # Aseguradora sin datos de acceso: solo se guarda ella.
            if commit:
                aseguradora.save()
            return None
        credencial.is_active = True
        if self.instance.pk and not self.cleaned_data.get('password'):
            credencial.password = AseguradoraCredencial.objects.get(pk=self.instance.pk).password
        elif self.cleaned_data.get('password'):
            # Contraseña nueva: si el portal había pedido cambiarla, ya se puede volver a intentar.
            credencial.requiere_cambio_clave = False
            credencial.cambio_clave_detectado_en = None
        if commit:
            aseguradora.save()
            credencial.aseguradora = aseguradora
            credencial.save()
        return credencial


class CoberturaForm(forms.ModelForm):
    """Ficha de coberturas de un producto de una aseguradora. Todos los campos son de texto libre
    (cada aseguradora expresa los valores a su manera); el único numérico es el límite de la RC."""

    class Meta:
        model = CoberturaAseguradora
        fields = ('producto', *CAMPOS_COBERTURA, 'observaciones')
        widgets = {
            'producto': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Ej: Plus, VIP, Integral, General'}),
            'rc_limite_millones': forms.NumberInput(attrs={'class': 'form-control', 'placeholder': 'Ej: 4000', 'min': 0}),
            'observaciones': forms.Textarea(attrs={'class': 'form-control', 'rows': 3}),
        }

    def __init__(self, *args, aseguradora, **kwargs):
        super().__init__(*args, **kwargs)
        self.aseguradora = aseguradora
        for nombre in CAMPOS_COBERTURA:
            if nombre != 'rc_limite_millones':
                self.fields[nombre].widget = forms.TextInput(attrs={'class': 'form-control', 'maxlength': 300, 'placeholder': 'Ej: Sí ampara, No ampara, Hasta 1 SMMLV…'})
            self.fields[nombre].required = False
        self.fields['producto'].widget.attrs['autofocus'] = True

    @property
    def grupos(self):
        """[(título de la sección, [campos del formulario])] en el orden del cuadro comparativo."""
        return [(titulo, [self[nombre] for nombre, _ in campos]) for titulo, campos in SECCIONES_COBERTURA]

    def clean_producto(self):
        producto = ' '.join((self.cleaned_data.get('producto') or '').split())
        if not producto:
            raise forms.ValidationError('Ingrese el nombre del producto o plan (use «General» si solo tiene uno).')
        repetido = CoberturaAseguradora.objects.filter(aseguradora=self.aseguradora, producto__iexact=producto)
        if self.instance.pk:
            repetido = repetido.exclude(pk=self.instance.pk)
        if repetido.exists():
            raise forms.ValidationError(f'{self.aseguradora.name} ya tiene una ficha para «{producto}».')
        return producto

    def save(self, commit=True):
        ficha = super().save(commit=False)
        ficha.aseguradora = self.aseguradora
        if commit:
            ficha.save()
        return ficha


class AsesorForm(forms.ModelForm):
    """Alta y edición de un asesor (interno o externo)."""

    class Meta:
        model = Asesor
        exclude = ('created_at',)
        widgets = {
            'tipo': forms.Select(attrs={'class': 'form-select'}),
            'nombres': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Nombres y apellidos', 'autofocus': True}),
            'tipo_documento': forms.Select(attrs={'class': 'form-select select2', 'style': 'width: 100%'}),
            'documento': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Solo números', 'inputmode': 'numeric'}),
            'correo': forms.EmailInput(attrs={'class': 'form-control', 'placeholder': 'correo@ejemplo.com'}),
            'telefono': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Ej: 3001234567', 'inputmode': 'tel'}),
            'ciudad': forms.Select(attrs={'class': 'form-select select2', 'style': 'width: 100%'}),
            'empresa': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Empresa o agencia del asesor'}),
            'nit_empresa': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'NIT (opcional)'}),
            'porcentaje_comision': forms.NumberInput(attrs={'class': 'form-control', 'step': '0.01', 'min': '0', 'max': '100'}),
            'fecha_vinculacion': forms.DateInput(format='%Y-%m-%d', attrs={'class': 'form-control', 'type': 'date'}),
            'banco': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Ej: Bancolombia'}),
            'tipo_cuenta': forms.Select(attrs={'class': 'form-select'}),
            'numero_cuenta': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Número de cuenta', 'inputmode': 'numeric'}),
            'usuario': forms.Select(attrs={'class': 'form-select select2', 'style': 'width: 100%'}),
            'observaciones': forms.Textarea(attrs={'class': 'form-control', 'rows': 3, 'placeholder': 'Acuerdos, condiciones de la alianza, notas…'}),
            'is_active': forms.CheckboxInput(attrs={'class': 'form-check-input'}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['tipo_documento'].queryset = DocumentType.objects.filter(is_active=True)
        self.fields['tipo_documento'].empty_label = 'Seleccione…'
        self.fields['ciudad'].queryset = Municipio.objects.select_related('departamento').order_by('departamento__nombre', 'nombre')
        self.fields['ciudad'].empty_label = 'Seleccione…'
        self.fields['tipo_cuenta'].choices = [('', 'Seleccione…')] + list(self.fields['tipo_cuenta'].choices)[1:]
        # Un usuario solo puede estar enlazado a un asesor: se ofrecen los activos que aún no lo están (y el actual).
        libres = User.objects.filter(is_active=True, asesor__isnull=True)
        if self.instance.pk and self.instance.usuario_id:
            libres = User.objects.filter(pk=self.instance.usuario_id) | libres
        self.fields['usuario'].queryset = libres.order_by('username')
        self.fields['usuario'].empty_label = 'Sin acceso al sistema'
        self.fields['usuario'].label_from_instance = lambda u: f'{u.username}' + (f' · {u.names}' if u.names else '')
        cedula = DocumentType.objects.filter(abbreviation='CC').first()
        if cedula and not self.instance.pk:
            self.fields['tipo_documento'].initial = cedula.pk

    def clean_nombres(self):
        return ' '.join(self.cleaned_data['nombres'].split())

    def clean_documento(self):
        documento = ''.join(self.cleaned_data['documento'].split()).replace('.', '')
        if not documento.isdigit():
            raise forms.ValidationError('El documento solo debe contener números.')
        return documento

    def clean_correo(self):
        return self.cleaned_data['correo'].strip().lower()

    def clean_telefono(self):
        telefono = ''.join(ch for ch in self.cleaned_data['telefono'] if ch.isdigit() or ch == '+')
        if len(telefono.lstrip('+')) < 7:
            raise forms.ValidationError('Ingrese un teléfono válido.')
        return telefono

    def clean_porcentaje_comision(self):
        porcentaje = self.cleaned_data['porcentaje_comision']
        if porcentaje < 0 or porcentaje > 100:
            raise forms.ValidationError('La comisión debe estar entre 0 y 100.')
        return porcentaje

    def clean_numero_cuenta(self):
        cuenta = ''.join((self.cleaned_data.get('numero_cuenta') or '').split()).replace('-', '')
        if cuenta and not cuenta.isdigit():
            raise forms.ValidationError('El número de cuenta solo debe contener números.')
        return cuenta or None

    def clean(self):
        cleaned = super().clean()
        if cleaned.get('tipo') == 'externo':
            if not (cleaned.get('empresa') or '').strip():
                self.add_error('empresa', 'Indique la empresa del asesor externo (o su nombre si trabaja por su cuenta).')
        else:
            cleaned['empresa'] = None  # los internos trabajan para la casa
            cleaned['nit_empresa'] = None
        if cleaned.get('banco') or cleaned.get('numero_cuenta'):
            if not cleaned.get('tipo_cuenta'):
                self.add_error('tipo_cuenta', 'Indique el tipo de cuenta.')
            if not cleaned.get('numero_cuenta'):
                self.add_error('numero_cuenta', 'Indique el número de cuenta.')
        return cleaned
