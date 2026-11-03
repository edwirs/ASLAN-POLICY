import json

from django.core.exceptions import ValidationError
from django.http import Http404, HttpResponse
from django.shortcuts import get_object_or_404, render
from django.urls import reverse, reverse_lazy
from django.views.generic import TemplateView, View

from core.policies.forms import CuentaCorreoForm, PlantillaCorreoForm
from core.policies.models import Cotizacion, CuentaCorreo, FirmaCorreo, PlantillaCorreo, Vehiculo
from core.policies.services import correo
from core.security.mixins import StrictPermissionMixin
from core.user.models import User

MODULE_NAME = 'Plantillas de correo'
VER = 'policies.view_plantillacorreo'
CREAR = 'policies.add_plantillacorreo'
EDITAR = 'policies.change_plantillacorreo'
CUENTAS = 'policies.change_cuentacorreo'
FIRMA_PROPIA = 'policies.change_firma_propia'


def _alguno(usuario, *permisos):
    return any(usuario.has_perm(p) for p in permisos)


class _AccesoModulo(StrictPermissionMixin):
    """Entra quien puede ver las plantillas o al menos cambiar su propia firma (el resto lo ve en solo lectura)."""
    permisos_entrada = (VER, EDITAR, FIRMA_PROPIA)

    def dispatch(self, request, *args, **kwargs):
        if request.user.is_authenticated and not _alguno(request.user, *self.permisos_entrada):
            return self.handle_no_permission(request, forbidden=True)
        return super().dispatch(request, *args, **kwargs)


def _json(data, status=200):
    return HttpResponse(json.dumps(data), content_type='application/json', status=status)


def _vehiculo_de_ejemplo(placa=None):
    """Vehículo para la vista previa: el de la placa pedida o el último que tiene valores cotizados."""
    if placa:
        return Vehiculo.objects.filter(placa__iexact=placa.strip().replace(' ', '')).select_related('tomador').first()
    ultima = (Cotizacion.objects.filter(estado_bot='completado').select_related('vehiculo__tomador').order_by('-id').first())
    return ultima.vehiculo if ultima else Vehiculo.objects.select_related('tomador').order_by('-id').first()


class PlantillaCorreoListView(_AccesoModulo, TemplateView):
    template_name = 'plantilla_correo/list.html'

    def post(self, request, *args, **kwargs):
        action = request.POST.get('action')
        usuario = request.user
        try:
            if action in ('firma_guardar', 'firma_quitar'):
                destino = usuario
                if request.POST.get('usuario') and str(request.POST['usuario']) != str(usuario.pk):
                    if not usuario.has_perm(EDITAR):
                        return _json({'error': 'Tu perfil solo puede cambiar tu propia firma.'}, 403)
                    destino = get_object_or_404(User, pk=request.POST['usuario'], is_active=True)
                elif not _alguno(usuario, FIRMA_PROPIA, EDITAR):
                    return _json({'error': 'Tu perfil no puede cambiar la firma.'}, 403)
                if action == 'firma_quitar':
                    FirmaCorreo.objects.filter(usuario=destino).delete()
                    return _json({'ok': True})
                archivo = request.FILES.get('imagen')
                if not archivo:
                    return _json({'error': 'Elige la imagen de la firma.'}, 400)
                try:
                    imagen = correo.normalizar_imagen(archivo, f'firma_{destino.pk}')
                except ValidationError as e:
                    return _json({'error': e.messages[0]}, 400)
                firma = FirmaCorreo.objects.filter(usuario=destino).first() or FirmaCorreo(usuario=destino)
                firma.imagen = imagen
                firma.save()
                return _json({'ok': True, 'url': firma.imagen.url})
            if action == 'cuenta_probar':
                if not usuario.has_perm(CUENTAS):
                    return _json({'error': 'Tu perfil no puede configurar las cuentas de correo.'}, 403)
                cuenta = get_object_or_404(CuentaCorreo, pk=request.POST.get('id'))
                ok, mensaje = correo.probar_cuenta(cuenta)
                return _json({'ok': ok, 'mensaje': mensaje})
            if action == 'plantilla_estado':
                if not usuario.has_perm(EDITAR):
                    return _json({'error': 'Tu perfil no puede editar las plantillas.'}, 403)
                plantilla = get_object_or_404(PlantillaCorreo, pk=request.POST.get('id'))
                plantilla.is_active = request.POST.get('activar') == 'true'
                plantilla.save(update_fields=['is_active', 'updated_at'])
                return _json({'ok': True})
            return _json({'error': 'No ha seleccionado ninguna opción'}, 400)
        except Http404:
            return _json({'error': 'El registro no existe.'}, 404)

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        usuario = self.request.user
        puede_editar = usuario.has_perm(EDITAR)
        context.update({
            'title': MODULE_NAME,
            'module_name': MODULE_NAME,
            'list_url': reverse_lazy('plantilla_correo_list'),
            'plantillas': PlantillaCorreo.objects.select_related('cuenta', 'actualizada_por'),
            'cuentas': CuentaCorreo.objects.all(),
            'mi_firma': FirmaCorreo.objects.filter(usuario=usuario).first(),
            'puede_ver': _alguno(usuario, VER, EDITAR),
            'puede_crear': usuario.has_perm(CREAR),
            'puede_editar': puede_editar,
            'puede_cuentas': usuario.has_perm(CUENTAS),
            'puede_firma': _alguno(usuario, FIRMA_PROPIA, EDITAR),
            'variables': correo.VARIABLES,
            'bloques': correo.BLOQUES,
        })
        if puede_editar:
            firmas = {f.usuario_id: f for f in FirmaCorreo.objects.all()}
            context['equipo'] = [{'usuario': u, 'firma': firmas.get(u.pk)}
                                 for u in User.objects.filter(is_active=True).order_by('names', 'username')]
        return context


class PlantillaCorreoFormView(_AccesoModulo, View):
    """Crear, editar o (sin permiso de edición) solo ver una plantilla, con vista previa en vivo."""
    template_name = 'plantilla_correo/form.html'
    permisos_entrada = (VER, EDITAR, CREAR)

    def _plantilla(self):
        return get_object_or_404(PlantillaCorreo, pk=self.kwargs['pk']) if 'pk' in self.kwargs else None

    def _puede_guardar(self, plantilla):
        return self.request.user.has_perm(EDITAR if plantilla else CREAR)

    def get(self, request, *args, **kwargs):
        plantilla = self._plantilla()
        if plantilla is None and not request.user.has_perm(CREAR):
            return self.handle_no_permission(request, forbidden=True)
        form = PlantillaCorreoForm(instance=plantilla)
        editable = self._puede_guardar(plantilla)
        if not editable:
            for campo in form.fields.values():
                campo.disabled = True
        return render(request, self.template_name, {
            'title': plantilla.nombre if plantilla else 'Nueva plantilla de correo',
            'module_name': MODULE_NAME,
            'list_url': reverse_lazy('plantilla_correo_list'),
            'form': form,
            'plantilla': plantilla,
            'editable': editable,
            'variables': correo.VARIABLES,
            'bloques': correo.BLOQUES,
            'cuerpo_inicial': plantilla.cuerpo if plantilla else '',
            'ejemplo': _vehiculo_de_ejemplo(),
        })

    def post(self, request, *args, **kwargs):
        plantilla = self._plantilla()
        action = request.POST.get('action')
        if action == 'vista_previa':
            return self._vista_previa(request, plantilla)
        if action != 'guardar':
            return _json({'error': 'No ha seleccionado ninguna opción'}, 400)
        if not self._puede_guardar(plantilla):
            return _json({'error': 'Tu perfil solo puede ver las plantillas.'}, 403)
        form = PlantillaCorreoForm(request.POST, request.FILES, instance=plantilla)
        if not form.is_valid():
            return _json({'error': {campo: list(errores) for campo, errores in form.errors.items()}})
        guardada = form.save(commit=False)
        guardada.actualizada_por = request.user
        guardada.save()
        form.save_m2m()
        if guardada.predeterminada:
            PlantillaCorreo.objects.filter(tipo_seguro=guardada.tipo_seguro).exclude(pk=guardada.pk).update(predeterminada=False)
        return _json({'ok': True, 'url': str(reverse_lazy('plantilla_correo_list'))})

    def _vista_previa(self, request, plantilla):
        """Arma el correo con lo que está en pantalla (sin guardar) para un vehículo de ejemplo."""
        borrador = PlantillaCorreo(pk=plantilla.pk if plantilla else None)
        if plantilla:
            borrador.promocion_imagen = plantilla.promocion_imagen
        borrador.asunto = request.POST.get('asunto', '')
        borrador.para = request.POST.get('para', '')
        borrador.cc = request.POST.get('cc', '')
        borrador.cuerpo = correo.limpiar_cuerpo(request.POST.get('cuerpo', ''))
        borrador.promocion_texto = request.POST.get('promocion_texto', '')
        borrador.adjuntar_pdf = request.POST.get('adjuntar_pdf') in ('on', 'true', '1')
        try:
            borrador.vigencia_cotizacion_dias = max(1, int(request.POST.get('vigencia_cotizacion_dias') or 15))
        except ValueError:
            borrador.vigencia_cotizacion_dias = 15
        borrador.cuenta = CuentaCorreo.objects.filter(pk=request.POST.get('cuenta') or 0).first()
        mostrar = request.POST.get('promocion_aseguradora') or ''
        borrador.promocion_activa = mostrar != PlantillaCorreoForm.NUNCA
        borrador.promocion_aseguradora_id = int(mostrar) if mostrar.isdigit() else None
        vehiculo = _vehiculo_de_ejemplo(request.POST.get('placa'))
        if vehiculo is None:
            return _json({'error': 'No hay un vehículo con esa placa para la vista previa.'})
        armado = correo.armar(borrador, vehiculo, request.user)
        return _json({'placa': vehiculo.placa, 'de': armado['de'], 'para': armado['para'], 'cc': armado['cc'],
                      'asunto': armado['asunto'], 'html': armado['html'], 'avisos': armado['avisos'], 'adjunto': armado['adjunto']})


class CuentaCorreoFormView(StrictPermissionMixin, View):
    """Cuenta SMTP. Solo quien tiene permiso de configurar cuentas."""
    template_name = 'plantilla_correo/cuenta_form.html'
    permission_required = CUENTAS

    def _cuenta(self):
        return get_object_or_404(CuentaCorreo, pk=self.kwargs['pk']) if 'pk' in self.kwargs else None

    def get(self, request, *args, **kwargs):
        cuenta = self._cuenta()
        return render(request, self.template_name, {
            'title': f'Cuenta: {cuenta.nombre}' if cuenta else 'Nueva cuenta de correo',
            'module_name': MODULE_NAME,
            'list_url': reverse_lazy('plantilla_correo_list'),
            'action': 'edit' if cuenta else 'add',
            'form': CuentaCorreoForm(instance=cuenta),
            'cuenta': cuenta,
        })

    def post(self, request, *args, **kwargs):
        cuenta = self._cuenta()
        form = CuentaCorreoForm(request.POST, instance=cuenta)
        if not form.is_valid():
            return _json({'error': {campo: list(errores) for campo, errores in form.errors.items()}})
        if request.POST.get('action') == 'probar':
            prueba = form.save(commit=False)
            prueba.pk = None  # la prueba de lo que está en pantalla no se guarda
            ok, mensaje = correo.probar_cuenta(prueba)
            return _json({'ok': ok, 'mensaje': mensaje})
        guardada = form.save()
        guardada.probada_en = guardada.prueba_ok = None
        guardada.prueba_mensaje = ''
        guardada.save(update_fields=['probada_en', 'prueba_ok', 'prueba_mensaje'])
        return _json({'ok': True, 'url': str(reverse('plantilla_correo_list')) + '#cuentas'})
