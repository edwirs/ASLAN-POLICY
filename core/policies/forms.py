from datetime import date
from decimal import Decimal

from django import forms

from core.policies.models import (Aseguradora, AseguradoraCredencial, Asesor, CoberturaAseguradora, CuentaCorreo, PlantillaCorreo,
                                  Poliza, TipoPoliza, Vehiculo)
from core.policies.services.polizas import MAX_CUOTAS
from core.policies.services.bots import BOTS_DISPONIBLES
from core.policies.services import correo as servicio_correo
from core.policies.services.coberturas import CAMPOS as CAMPOS_COBERTURA, SECCIONES as SECCIONES_COBERTURA
from core.policies.services.credenciales import (CAMPOS_CONTACTO, INICIALES, PORTALES, campos_de, contacto_general,
                                                 obligatorios_de, parametros_de)
from core.pos.models import DocumentType, Municipio
from core.user.models import User


class SolicitudCotizacionForm(forms.Form):
    document_type = forms.ModelChoiceField(
        queryset=DocumentType.objects.filter(is_active=True),
        label='Tipo de documento',
        widget=forms.Select(attrs={
            'class': 'form-control select2',
            'style': 'width: 100%',
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
    mobile = forms.CharField(
        required=False,
        max_length=20,
        label='Celular',
        widget=forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Ej: 3001234567', 'inputmode': 'tel'})
    )
    # «Tiene más datos de contacto»: si está apagado, otro celular y otro correo se ignoran (y se borran del cliente).
    mas_contacto = forms.BooleanField(
        required=False,
        label='El cliente tiene otro celular u otro correo',
        widget=forms.CheckboxInput(attrs={'class': 'form-check-input', 'role': 'switch'})
    )
    phone = forms.CharField(
        required=False,
        max_length=20,
        label='Otro celular',
        widget=forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Ej: 3101234567', 'inputmode': 'tel'})
    )
    email_secundario = forms.EmailField(
        required=False,
        max_length=100,
        label='Otro correo',
        widget=forms.EmailInput(attrs={'class': 'form-control', 'placeholder': 'otro@ejemplo.com'})
    )
    # Solo se muestran si el tipo de documento es NIT: la persona dueña de la empresa. Opcionales.
    propietario_documento = forms.CharField(
        required=False,
        max_length=20,
        label='Cédula del propietario',
        widget=forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Opcional', 'inputmode': 'numeric'})
    )
    propietario_nombre = forms.CharField(
        required=False,
        max_length=150,
        label='Nombre del propietario de la empresa',
        widget=forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Opcional'})
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

    @staticmethod
    def _celular(valor):
        celular = ''.join(c for c in valor or '' if c.isdigit())
        if celular.startswith('57') and len(celular) == 12:
            celular = celular[2:]
        if celular and len(celular) != 10:
            raise forms.ValidationError('El celular debe tener 10 dígitos')
        return celular

    def clean_mobile(self):
        return self._celular(self.cleaned_data.get('mobile'))

    def clean_phone(self):
        return self._celular(self.cleaned_data.get('phone'))

    def clean_codigo_fasecolda(self):
        codigo = (self.cleaned_data.get('codigo_fasecolda') or '').strip()
        if codigo and not codigo.isdigit():
            raise forms.ValidationError('El código Fasecolda solo debe contener números')
        return codigo

    def clean_propietario_documento(self):
        return ''.join(c for c in self.cleaned_data.get('propietario_documento') or '' if c.isdigit())

    def clean_propietario_nombre(self):
        return ' '.join((self.cleaned_data.get('propietario_nombre') or '').split())

    def clean(self):
        cleaned = super().clean()
        tipo = cleaned.get('document_type')
        if not (tipo and tipo.abbreviation == 'NIT'):
            cleaned['propietario_documento'] = ''
            cleaned['propietario_nombre'] = ''
        if not cleaned.get('mas_contacto'):
            cleaned['phone'] = ''
            cleaned['email_secundario'] = ''
        else:
            if cleaned.get('phone') and cleaned['phone'] == cleaned.get('mobile'):
                cleaned['phone'] = ''  # repetido: no aporta
            if (cleaned.get('email_secundario') or '').lower() == (cleaned.get('email') or '').lower():
                cleaned['email_secundario'] = ''
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
        # Aseguradora con bot aún sin datos de acceso (empresa nueva): se propone activarla al guardarlos.
        self.fields['aseguradora_activa'].initial = (aseguradora.is_active or credencial is None) if not self.es_nueva else True
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
        # Correo y celular: opcionales aquí; si se dejan vacíos el bot usa el contacto general para los portales.
        general = contacto_general()
        for nombre, del_general in CAMPOS_CONTACTO.items():
            if nombre in self.fields:
                valor = getattr(general, del_general)
                self.fields[nombre].label = str(self.fields[nombre].label).replace(' (cotizador)', '') + ' (opcional)'
                self.fields[nombre].help_text = (f'Vacío = el contacto general para los portales ({valor}).' if valor else
                                                 'Vacío = el contacto general para los portales (arriba en Aseguradoras).')
                self.fields[nombre].widget.attrs['placeholder'] = valor or ''
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
        # Credencial nueva: URL del portal y campos comunes a cualquier intermediario ya escritos.
        if credencial is None and not self.es_nueva:
            iniciales = {'portal_url': PORTALES.get(aseguradora.name), **INICIALES.get(aseguradora.name, {})}
            for nombre, valor in iniciales.items():
                if nombre in self.fields and valor:
                    self.fields[nombre].initial = valor
        # Opciones de la empresa en el cotizador de este portal (oficina, productos…): van en `parametros`.
        guardados = (credencial.parametros or {}) if credencial else {}
        for p in parametros_de(aseguradora.name):
            if p.get('opciones'):
                self.fields['param_' + p['clave']] = forms.ChoiceField(
                    required=False, label=p['etiqueta'], choices=p['opciones'], help_text=p.get('ayuda', ''),
                    initial=guardados.get(p['clave']) or p.get('defecto', ''),
                    widget=forms.Select(attrs={'class': 'form-control form-select'}))
                continue
            self.fields['param_' + p['clave']] = forms.CharField(
                required=False, max_length=300, label=p['etiqueta'],
                help_text=' '.join(x for x in (p.get('ayuda', ''), f'Si se deja vacío se usa: {p["defecto"]}.' if p.get('defecto') else '') if x),
                initial=guardados.get(p['clave']) or p.get('defecto', ''),
                widget=forms.TextInput(attrs={'class': 'form-control', 'autocomplete': 'off'}))
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
            general = contacto_general()
            for nombre in obligatorios_de(self.aseguradora):
                if nombre not in self.fields or cleaned.get(nombre):
                    continue
                if nombre in CAMPOS_CONTACTO and getattr(general, CAMPOS_CONTACTO[nombre]):
                    continue  # lo cubre el contacto general para los portales
                if nombre == 'password' and self.instance.pk and self.instance.password:
                    continue
                self.add_error(nombre, 'Obligatorio para dejar la aseguradora activa.')
            for p in parametros_de(self.aseguradora.name):
                if p.get('obligatorio') and not (cleaned.get('param_' + p['clave']) or '').strip():
                    self.add_error('param_' + p['clave'], 'Obligatorio para dejar la aseguradora activa.')
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
        datos_acceso = [n for n in self.fields if n not in ('aseguradora_activa', *self.CAMPOS_ASEGURADORA) and not n.startswith('param_')]
        if not self.instance.pk and not any(self.cleaned_data.get(n) for n in datos_acceso):
            # Aseguradora sin datos de acceso: solo se guarda ella.
            if commit:
                aseguradora.save()
            return None
        credencial.is_active = True
        parametros = dict(credencial.parametros or {})
        for p in parametros_de(aseguradora.name):
            parametros[p['clave']] = ' '.join((self.cleaned_data.get('param_' + p['clave']) or '').split())
        credencial.parametros = parametros
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


class PolizaForm(forms.ModelForm):
    """La póliza que eligió el cliente. El vehículo y el tomador se fijan en la vista (el tomador es el dueño de ESE momento)."""
    numero_cuotas = forms.TypedChoiceField(
        coerce=int, label='Forma de pago',
        choices=[(1, 'Totalidad (un solo pago)')] + [(n, f'{n} cuotas mensuales') for n in range(2, MAX_CUOTAS + 1)],
        widget=forms.Select(attrs={'class': 'form-select'}))

    class Meta:
        model = Poliza
        fields = ('asesor', 'aseguradora', 'tipo_poliza', 'plan', 'numero_poliza', 'zona_circulacion', 'fecha_renovacion',
                  'prima_total', 'valor_sin_iva', 'valor_comision', 'descuentos', 'fecha_descuento', 'numero_cuotas', 'fecha_pago',
                  'estado', 'fecha_pago_aseguradora', 'estado_comision', 'fecha_pago_cartera', 'observaciones')
        fecha = lambda: forms.DateInput(format='%Y-%m-%d', attrs={'class': 'form-control', 'type': 'date'})
        dinero = lambda: forms.TextInput(attrs={'class': 'form-control dinero', 'inputmode': 'numeric', 'autocomplete': 'off'})
        widgets = {
            'asesor': forms.Select(attrs={'class': 'form-select select2', 'style': 'width: 100%'}),
            'aseguradora': forms.Select(attrs={'class': 'form-select select2', 'style': 'width: 100%'}),
            'tipo_poliza': forms.Select(attrs={'class': 'form-select'}),
            'plan': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Ej: Plus, Vip, Premium'}),
            'numero_poliza': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Opcional'}),
            'zona_circulacion': forms.Select(attrs={'class': 'form-select select2', 'style': 'width: 100%'}),
            'fecha_renovacion': fecha(),
            'prima_total': dinero(), 'valor_sin_iva': dinero(), 'valor_comision': dinero(), 'descuentos': dinero(),
            'fecha_descuento': fecha(),
            'fecha_pago': fecha(),
            'estado': forms.Select(attrs={'class': 'form-select'}),
            'fecha_pago_aseguradora': fecha(),
            'estado_comision': forms.Select(attrs={'class': 'form-select'}),
            'fecha_pago_cartera': fecha(),
            'observaciones': forms.Textarea(attrs={'class': 'form-control', 'rows': 2, 'placeholder': 'Notas del seguimiento…'}),
        }

    def __init__(self, *args, vehiculo=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.vehiculo = vehiculo
        asesores = Asesor.objects.filter(is_active=True)
        if self.instance.pk:
            asesores = Asesor.objects.filter(pk=self.instance.asesor_id) | asesores
        self.fields['asesor'].queryset = asesores.order_by('nombres')
        self.fields['aseguradora'].queryset = Aseguradora.objects.filter(is_active=True) | Aseguradora.objects.filter(
            pk=self.instance.aseguradora_id or 0)
        self.fields['tipo_poliza'].queryset = TipoPoliza.objects.filter(is_active=True)
        self.fields['zona_circulacion'].queryset = Municipio.objects.select_related('departamento').order_by('departamento__nombre', 'nombre')
        for campo in ('asesor', 'aseguradora', 'zona_circulacion', 'tipo_poliza'):
            self.fields[campo].empty_label = 'Seleccione…'
        for campo in ('valor_sin_iva', 'valor_comision', 'descuentos'):
            self.fields[campo].required = False  # vacío = 0 (en el histórico a veces no vienen)
        for campo in ('prima_total', 'valor_sin_iva', 'valor_comision', 'descuentos'):
            self.fields[campo].localize = False
            valor = self.initial.get(campo)
            if valor not in (None, ''):
                self.initial[campo] = int(Decimal(str(valor)))  # sin decimales: en pantalla se ve $1.234.567
        if not self.instance.pk:
            del self.fields['estado']  # una póliza nueva siempre nace «generada»

    def _dinero(self, campo):
        """Los montos llegan con puntos de miles ($1.234.567): se dejan solo los dígitos."""
        crudo = str(self.data.get(campo, '') or '').replace('.', '').replace('$', '').replace(' ', '').replace(',', '')
        return crudo or '0'

    def full_clean(self):
        if self.is_bound:
            self.data = self.data.copy()
            for campo in ('prima_total', 'valor_sin_iva', 'valor_comision', 'descuentos'):
                self.data[campo] = self._dinero(campo)
        super().full_clean()

    def clean(self):
        cleaned = super().clean()
        prima, sin_iva, comision = cleaned.get('prima_total'), cleaned.get('valor_sin_iva'), cleaned.get('valor_comision')
        if prima is not None and prima <= 0:
            self.add_error('prima_total', 'La prima total debe ser mayor que cero.')
        if sin_iva and prima and sin_iva > prima:
            self.add_error('valor_sin_iva', 'El valor sin IVA no puede ser mayor que la prima total.')
        if comision and sin_iva and comision > sin_iva:
            self.add_error('valor_comision', 'La comisión no puede ser mayor que el valor sin IVA.')
        renovacion, tipo = cleaned.get('fecha_renovacion'), cleaned.get('tipo_poliza')
        vehiculo = self.vehiculo or getattr(self.instance, 'vehiculo', None)
        if vehiculo and renovacion and tipo:
            repetida = (Poliza.objects.filter(vehiculo=vehiculo, tipo_poliza=tipo, fecha_renovacion=renovacion)
                        .exclude(estado='cancelada').exclude(pk=self.instance.pk or 0))
            if repetida.exists():
                self.add_error('fecha_renovacion', f'{vehiculo.placa} ya tiene una póliza de {tipo} que vence ese mismo día.')
        return cleaned


class PlantillaCorreoForm(forms.ModelForm):
    """Plantilla del correo de cotización. El cuerpo llega del editor como HTML y se limpia (solo formato básico)."""
    NUNCA = 'nunca'
    # «Mostrarla»: Siempre / Nunca / solo si cierta aseguradora está en el comparativo. Se guarda en
    # promocion_activa + promocion_aseguradora (ver save).
    promocion_aseguradora = forms.ChoiceField(required=False, label='Mostrarla', widget=forms.Select(attrs={'class': 'form-select'}))

    class Meta:
        model = PlantillaCorreo
        fields = ('nombre', 'tipo_seguro', 'cuenta', 'para', 'cc', 'asunto', 'cuerpo', 'promocion_texto', 'promocion_imagen',
                  'vigencia_cotizacion_dias', 'adjuntar_pdf', 'predeterminada', 'is_active')
        widgets = {
            'nombre': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Ej: Cotización de autos'}),
            'tipo_seguro': forms.Select(attrs={'class': 'form-select'}),
            'cuenta': forms.Select(attrs={'class': 'form-select'}),
            'para': forms.TextInput(attrs={'class': 'form-control', 'placeholder': '{correo_cliente}'}),
            'cc': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'correo@empresa.com, otro@empresa.com'}),
            'asunto': forms.TextInput(attrs={'class': 'form-control'}),
            'cuerpo': forms.Textarea(attrs={'hidden': True}),
            'promocion_texto': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Ej: MAPFRE te da la opción de pagar tu póliza en 3 cuotas sin intereses'}),
            'promocion_imagen': forms.ClearableFileInput(attrs={'class': 'form-control', 'accept': 'image/*'}),
            'vigencia_cotizacion_dias': forms.NumberInput(attrs={'class': 'form-control', 'min': '1', 'max': '90'}),
            'adjuntar_pdf': forms.CheckboxInput(attrs={'class': 'form-check-input'}),
            'predeterminada': forms.CheckboxInput(attrs={'class': 'form-check-input'}),
            'is_active': forms.CheckboxInput(attrs={'class': 'form-check-input'}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['cuenta'].queryset = CuentaCorreo.objects.filter(is_active=True) | CuentaCorreo.objects.filter(pk=self.instance.cuenta_id or 0)
        self.fields['cuenta'].empty_label = 'Sin cuenta (no se puede enviar)'
        aseguradoras = [(str(a.pk), f'Solo si {a.name} está en el comparativo') for a in Aseguradora.objects.filter(is_active=True).order_by('name')]
        self.fields['promocion_aseguradora'].choices = [('', 'Siempre'), (self.NUNCA, 'Nunca')] + aseguradoras
        if not self.is_bound:
            self.initial['promocion_aseguradora'] = (self.NUNCA if not self.instance.promocion_activa
                                                     else str(self.instance.promocion_aseguradora_id or ''))
        self.fields['cuerpo'].required = True

    def _correos(self, campo):
        texto = ' '.join((self.cleaned_data.get(campo) or '').split())
        for parte in [p.strip() for p in texto.replace(';', ',').split(',') if p.strip()]:
            if parte.startswith('{') and parte.endswith('}'):
                if parte[1:-1] not in servicio_correo.VARIABLES_CORREO:
                    raise forms.ValidationError(f'{parte} no es una variable de correo (use {{correo_cliente}} o {{correo_asesor}}).')
                continue
            try:
                forms.EmailField().clean(parte)
            except forms.ValidationError:
                raise forms.ValidationError(f'«{parte}» no es un correo válido.')
        return ', '.join(p.strip() for p in texto.replace(';', ',').split(',') if p.strip())

    def clean_para(self):
        para = self._correos('para')
        if not para:
            raise forms.ValidationError('Indique a quién va el correo (normalmente {correo_cliente}).')
        return para

    def clean_cc(self):
        return self._correos('cc')

    def clean_cuerpo(self):
        cuerpo = servicio_correo.limpiar_cuerpo(self.cleaned_data.get('cuerpo'))
        if not servicio_correo.strip_tags(cuerpo).strip():
            raise forms.ValidationError('Escriba el cuerpo del correo.')
        return cuerpo

    def clean_promocion_imagen(self):
        imagen = self.cleaned_data.get('promocion_imagen')
        if imagen and hasattr(imagen, 'content_type'):  # recién subida: se pasa a PNG
            return servicio_correo.normalizar_imagen(imagen, 'promocion')
        return imagen

    def save(self, commit=True):
        mostrar = self.cleaned_data.get('promocion_aseguradora') or ''
        self.instance.promocion_activa = mostrar != self.NUNCA
        self.instance.promocion_aseguradora_id = int(mostrar) if mostrar.isdigit() else None
        plantilla = super().save(commit=commit)
        if commit and plantilla.predeterminada:
            PlantillaCorreo.objects.filter(tipo_seguro=plantilla.tipo_seguro).exclude(pk=plantilla.pk).update(predeterminada=False)
        return plantilla


class CuentaCorreoForm(forms.ModelForm):
    """Cuenta SMTP desde la que salen los correos. La contraseña nunca se muestra: si se deja vacía se conserva."""
    clave = forms.CharField(required=False, label='Contraseña de aplicación', strip=True,
                            widget=forms.PasswordInput(attrs={'class': 'form-control', 'autocomplete': 'new-password'}, render_value=False))

    class Meta:
        model = CuentaCorreo
        fields = ('nombre', 'correo', 'nombre_remitente', 'servidor', 'puerto', 'seguridad', 'usuario', 'clave', 'is_active')
        widgets = {
            'nombre': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Ej: Ventas - Mi Agencia de Seguros'}),
            'correo': forms.EmailInput(attrs={'class': 'form-control', 'placeholder': 'cotizaciones@miagencia.com'}),
            'nombre_remitente': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Ej: Mi Agencia de Seguros'}),
            'servidor': forms.TextInput(attrs={'class': 'form-control'}),
            'puerto': forms.NumberInput(attrs={'class': 'form-control'}),
            'seguridad': forms.Select(attrs={'class': 'form-select'}),
            'usuario': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Vacío = el mismo correo'}),
            'is_active': forms.CheckboxInput(attrs={'class': 'form-check-input'}),
        }

    def clean_clave(self):
        clave = (self.cleaned_data.get('clave') or '').replace(' ', '')  # Google muestra la clave de aplicación en grupos de 4
        if not clave and not (self.instance.pk and self.instance.clave):
            raise forms.ValidationError('Escriba la contraseña de aplicación de la cuenta.')
        return clave or self.instance.clave
