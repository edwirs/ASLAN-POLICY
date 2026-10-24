from datetime import datetime

from django import forms
from django.contrib.auth import authenticate

from core.security.choices import LOGIN_ATTEMPT
from core.user.models import User
from core.security.models import UserAccess


class AuthenticationForm(forms.Form):
    login_error = None

    username = forms.CharField(widget=forms.TextInput(attrs={
        'placeholder': 'Ingrese un username',
        'class': 'form-control',
        'autocomplete': 'off'
    }), label='Usuario')

    password = forms.CharField(widget=forms.PasswordInput(attrs={
        'placeholder': 'Ingrese un password',
        'class': 'form-control',
        'autocomplete': 'off'
    }), label='Contraseña')

    MAX_INTENTOS = 3

    def _fallar(self, tipo, titulo, mensaje, intentos_restantes=None):
        """Deja el error estructurado para que la pantalla lo muestre según su tipo."""
        self.login_error = {
            'tipo': tipo,
            'titulo': titulo,
            'mensaje': mensaje,
            'intentos_restantes': intentos_restantes,
            'intentos_max': self.MAX_INTENTOS,
        }
        raise forms.ValidationError(mensaje)

    def clean(self):
        cleaned = super().clean()
        username = (cleaned.get('username') or '').strip()
        password = cleaned.get('password') or ''
        if not username:
            self._fallar('campos', 'Falta el usuario', 'Escribe tu nombre de usuario para continuar.')
        if not password:
            self._fallar('campos', 'Falta la contraseña', 'Escribe tu contraseña para continuar.')
        user = User.objects.filter(username=username).first()
        if user is None:
            self._fallar(
                'usuario', 'Usuario no encontrado',
                f'No existe el usuario «{username}». Revisa que esté bien escrito (se distingue entre mayúsculas y minúsculas).')
        if not user.is_active:
            self._fallar(
                'bloqueado', 'Tu usuario está bloqueado',
                'Por seguridad el sistema bloqueó este usuario. Pide a un administrador que lo reactive; '
                'después podrás ingresar con tu contraseña normal.')
        if authenticate(username=username, password=password) is None:
            UserAccess(user=user, login_attempt=LOGIN_ATTEMPT[1][0]).save()
            intentos = user.useraccess_set.filter(
                login_attempt=LOGIN_ATTEMPT[1][0], date_joined=datetime.now().date()).count()
            if intentos >= self.MAX_INTENTOS:
                user.is_active = False
                user.save()
                self._fallar(
                    'bloqueado_ahora', 'Usuario bloqueado',
                    f'Llegaste a {self.MAX_INTENTOS} intentos fallidos en el día, así que bloqueamos tu usuario para proteger tu cuenta. '
                    'Pide a un administrador que lo reactive.')
            restantes = self.MAX_INTENTOS - intentos
            self._fallar(
                'clave', 'Contraseña incorrecta',
                f"La contraseña no coincide con el usuario «{username}». "
                f"Te {'queda' if restantes == 1 else 'quedan'} {restantes} {'intento' if restantes == 1 else 'intentos'} "
                'antes de que se bloquee tu usuario.',
                restantes)
        UserAccess(user=user).save()
        cleaned['username'] = username
        return cleaned

    def get_user(self):
        username = self.cleaned_data.get('username')
        return User.objects.get(username=username)


class ResetPasswordForm(forms.Form):
    username = forms.CharField(widget=forms.TextInput(attrs={
        'placeholder': 'Ingrese un username',
        'class': 'form-control',
        'autocomplete': 'off'
    }), label='Usuario')

    def clean(self):
        cleaned = super().clean()
        users = User.objects.filter(username=cleaned['username'])
        if not users.exists():
            raise forms.ValidationError('El usuario que ingreso no existe en el sistema')
        return cleaned

    def get_user(self):
        return User.objects.get(username=self.cleaned_data.get('username'))


class UpdatePasswordForm(forms.Form):
    password = forms.CharField(widget=forms.PasswordInput(attrs={
        'placeholder': 'Ingrese un password',
        'class': 'form-control',
        'autocomplete': 'off'
    }), label='Password')

    confirm_password = forms.CharField(widget=forms.PasswordInput(attrs={
        'placeholder': 'Repita el password',
        'class': 'form-control',
        'autocomplete': 'off'
    }), label='Confirmación de password')

    def clean(self):
        cleaned = super().clean()
        password = cleaned['password']
        confirm_password = cleaned['confirm_password']
        if password != confirm_password:
            raise forms.ValidationError('Las contraseñas deben ser iguales')
        return cleaned
