import hashlib
import json
from datetime import date
from decimal import Decimal, InvalidOperation

from django.db import transaction
from django.http import FileResponse, Http404, HttpResponse, JsonResponse
from django.conf import settings
from django.shortcuts import get_object_or_404
from django.utils import timezone
from django.urls import reverse, reverse_lazy
from django.views.generic import TemplateView, View

from core.policies.models import Aseguradora, CorreoEnviado, Cotizacion, PlantillaCorreo, ValorExterno, Vehiculo
from core.policies.services import correo
from core.policies.services.polizas import registrar_evento
from core.pos.models import Company
from core.policies.services.bots import BOTS_DISPONIBLES
from core.policies.services.comparativo import aseguradoras_valor_manual, construir, dinero, indicadores, pendientes_de_valor, resumen_cliente, soat
from core.security.mixins import StrictPermissionMixin

MODULE_NAME = 'Cotizador'
VALOR_MAXIMO = Decimal('99999999999')  # cabe en DecimalField(14, 0)


class ComparativoView(StrictPermissionMixin, TemplateView):
    """Datos del vehículo y su propietario, y la tabla de valores por aseguradora de menor a mayor."""
    template_name = 'comparativo/detalle.html'
    permission_required = 'policies.view_comparativo'

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        vehiculo = get_object_or_404(
            Vehiculo.objects.select_related('tomador', 'tomador__document_type', 'tomador__municipality',
                                            'zona_circulacion', 'zona_circulacion__departamento'),
            pk=self.kwargs['pk'])
        resultado = construir(vehiculo)
        filas = resultado['filas']
        context.update({
            'title': f'Comparativo de {vehiculo.placa}',
            'module_name': MODULE_NAME,
            'list_url': reverse_lazy('vehiculo_list'),
            'vehiculo': vehiculo,
            'tomador': vehiculo.tomador,
            'valor_comercial_fmt': dinero(vehiculo.valor_comercial) if vehiculo.valor_comercial else None,
            'filas': filas,
            'resumen': resumen_cliente(filas),
            'indicadores': indicadores(filas),
            'sin_valor': resultado['sin_valor'],
            'aseguradora_actual': resultado['actual'],
            'mas_barata': filas[0] if filas else None,
            'puede_registrar_valores': self.request.user.has_perm('policies.add_valor_externo'),
            'aseguradoras_manual': [(a, a.name in BOTS_DISPONIBLES) for a in aseguradoras_valor_manual(vehiculo, filas)],
            'guardar_url': reverse('vehiculo_comparativo_valores', args=[vehiculo.pk]),
            'comparativo_url': reverse('vehiculo_comparativo', args=[vehiculo.pk]),
            'imprimir_url': reverse('vehiculo_comparativo_imprimir', args=[vehiculo.pk]),
            'puede_enviar_correo': self.request.user.has_perm('policies.send_cotizacion_correo'),
            'correo_url': reverse('vehiculo_comparativo_correo', args=[vehiculo.pk]),
            'vehiculo_id': vehiculo.pk,
            'soat': soat(vehiculo),
            'pendientes_valor_json': json.dumps(pendientes_de_valor(vehiculo, filas)).replace('<', '\\u003c'),
            'soat_url': reverse('vehiculo_comparativo_soat', args=[vehiculo.pk]),
            'poliza_vigente': vehiculo.polizas.filter(estado='generada', fecha_renovacion__gte=timezone.localdate())
                                            .select_related('aseguradora').order_by('-fecha_renovacion').first(),
        })
        return context


def _telefono(numero):
    """3227354638 -> +57 322 735 4638 (si no tiene 10 dígitos se deja como está)."""
    digitos = ''.join(c for c in (numero or '') if c.isdigit())
    if len(digitos) == 12 and digitos.startswith('57'):
        digitos = digitos[2:]
    if len(digitos) == 10:
        return f'+57 {digitos[:3]} {digitos[3:6]} {digitos[6:]}'
    return (numero or '').strip()


def datos_empresa():
    """Datos de la empresa para el encabezado y el pie del PDF (Configuración › Empresa)."""
    empresa = Company.objects.filter(is_active=True).first()
    if empresa is None:
        return None
    telefonos = []
    for numero in (empresa.mobile, empresa.phone):
        formateado = _telefono(numero)
        if formateado and formateado not in telefonos:
            telefonos.append(formateado)
    sitio = (empresa.website or '').strip()
    return {
        'nombre': empresa.name,
        'logo_url': empresa.image.url if empresa.image else None,
        'telefonos': telefonos,
        'email': (empresa.email or '').strip(),
        'sitio': sitio,
        'sitio_url': sitio if sitio.startswith('http') else (f'https://{sitio}' if sitio else ''),
        'sitio_texto': sitio.replace('https://', '').replace('http://', '').rstrip('/'),
        'direccion': (empresa.address or '').strip().title(),
    }


class ComparativoImprimirView(ComparativoView):
    """Resumen para el cliente en una página limpia (sin menú ni contenedor de la aplicación), pensada para
    imprimir o guardar como PDF: cada navegador maneja distinto la impresión del diseño de AdminLTE."""
    template_name = 'comparativo/imprimir.html'

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        columnas = len(context['resumen']['columnas'])
        context['solo_diferencias'] = self.request.GET.get('solo_diferencias') == '1'
        context['empresa'] = datos_empresa()
        # Leyenda lateral del PDF: cuándo y por quién se generó, con una referencia propia del documento.
        ahora = timezone.localtime()
        vehiculo = context['vehiculo']
        huella = hashlib.sha256(
            f"{vehiculo.pk}|{[(f['aseguradora'], str(f['valor'])) for f in context['filas']]}|{settings.SECRET_KEY}".encode()
        ).hexdigest()[:6].upper()
        usuario = self.request.user
        context['generado_en'] = ahora
        context['generado_por'] = (usuario.get_full_name() if hasattr(usuario, 'get_full_name') else '') or usuario.get_username()
        context['documento_ref'] = f'CMP-{vehiculo.pk}-{ahora:%y%m%d%H%M}-{huella}'
        context['escala'] = 'xs' if columnas >= 9 else 'sm' if columnas >= 7 else 'md' if columnas >= 5 else 'lg'
        return context


def _leer_valor(texto):
    """'1.234.567' / '$1,234,567' -> Decimal, o None si no es un valor válido."""
    try:
        valor = Decimal(str(texto or '').replace('.', '').replace(',', '').replace('$', '').strip())
    except InvalidOperation:
        return None
    return valor if 0 < valor <= VALOR_MAXIMO else None


class ComparativoValoresView(StrictPermissionMixin, View):
    """Registra los valores finales de aseguradoras sin bot para el vehículo.

    Recibe `valores` = JSON [{"aseguradora": id, "valor": "1234567"}, ...]. Se valida todo antes de
    guardar nada: si una fila falla no se registra ninguna."""
    permission_required = 'policies.add_valor_externo'

    def post(self, request, pk):
        vehiculo = get_object_or_404(Vehiculo, pk=pk)
        try:
            filas = json.loads(request.POST.get('valores', '[]'))
        except ValueError:
            return JsonResponse({'error': 'Los valores enviados no son válidos'}, status=400)
        if not isinstance(filas, list) or not filas:
            return JsonResponse({'error': 'Agrega al menos una aseguradora con su valor'}, status=400)

        permitidas = {a.pk: a for a in aseguradoras_valor_manual(vehiculo)}
        nuevos, vistas = [], set()
        for numero, fila in enumerate(filas, start=1):
            try:
                aseguradora_id = int(fila.get('aseguradora'))
            except (TypeError, ValueError, AttributeError):
                return JsonResponse({'error': f'Fila {numero}: elige la aseguradora'}, status=400)
            aseguradora = permitidas.get(aseguradora_id)
            if aseguradora is None:
                return JsonResponse({'error': f'Fila {numero}: la aseguradora no existe, está inactiva o su bot ya trajo el valor'}, status=400)
            if aseguradora_id in vistas:
                return JsonResponse({'error': f'{aseguradora.name} está repetida: registra un solo valor por aseguradora'}, status=400)
            vistas.add(aseguradora_id)
            valor = _leer_valor(fila.get('valor'))
            if valor is None:
                return JsonResponse({'error': f'{aseguradora.name}: el valor debe ser un número mayor que cero'}, status=400)
            valor_2 = None
            if str(fila.get('valor_2') or '').strip():  # opcional: segundo valor al cotizar a mano (Integral en SdE)
                valor_2 = _leer_valor(fila.get('valor_2'))
                if valor_2 is None:
                    return JsonResponse({'error': f'{aseguradora.name}: el segundo valor debe ser un número mayor que cero'}, status=400)
            nuevos.append(ValorExterno(vehiculo=vehiculo, aseguradora=aseguradora, valor=valor, valor_2=valor_2,
                                       asesor=request.user))

        with transaction.atomic():
            ValorExterno.objects.bulk_create(nuevos)
        return JsonResponse({'url': reverse('vehiculo_comparativo', args=[vehiculo.pk])})


class ComparativoSoatView(StrictPermissionMixin, View):
    """Guarda el valor y el vencimiento del SOAT del vehículo (modal «Comparativo»). Los dos son opcionales: vacío borra."""
    permission_required = 'policies.view_comparativo'

    def post(self, request, pk):
        vehiculo = get_object_or_404(Vehiculo, pk=pk)
        texto_valor = str(request.POST.get('soat_valor') or '').strip()
        texto_fecha = str(request.POST.get('soat_vencimiento') or '').strip()
        valor = None
        if texto_valor:
            valor = _leer_valor(texto_valor)
            if valor is None:
                return JsonResponse({'error': 'El valor del SOAT debe ser un número mayor que cero'}, status=400)
        fecha = None
        if texto_fecha:
            try:
                fecha = date.fromisoformat(texto_fecha)
            except ValueError:
                return JsonResponse({'error': 'La fecha de vencimiento del SOAT no es válida'}, status=400)
            hoy = timezone.localdate()
            if not (hoy.replace(year=hoy.year - 2) <= fecha <= hoy.replace(year=hoy.year + 2)):
                return JsonResponse({'error': 'Revisa la fecha de vencimiento del SOAT: está muy lejos de hoy'}, status=400)
        vehiculo.soat_valor, vehiculo.soat_vencimiento = valor, fecha
        vehiculo.save(update_fields=['soat_valor', 'soat_vencimiento'])
        return JsonResponse({'ok': True, 'soat': soat(vehiculo)})


class ComparativoPdfView(StrictPermissionMixin, View):
    """El PDF del comparativo tal como va adjunto en el correo (mismo diseño de «Imprimir»)."""
    permission_required = 'policies.view_comparativo'

    def get(self, request, pk):
        vehiculo = get_object_or_404(Vehiculo, pk=pk)
        pdf = correo.pdf_comparativo(request, vehiculo, solo_diferencias=request.GET.get('solo_diferencias') == '1')
        respuesta = HttpResponse(pdf, content_type='application/pdf')
        respuesta['Content-Disposition'] = f'inline; filename="Comparativo {vehiculo.placa}.pdf"'
        return respuesta


class ComparativoCorreoView(StrictPermissionMixin, View):
    """«Armar correo»: GET devuelve el correo armado con la plantilla para revisarlo; POST lo envía."""
    permission_required = 'policies.send_cotizacion_correo'

    @staticmethod
    def _cotizaciones(vehiculo):
        """Las más baratas del ranking, para la sección «Cotizaciones que se adjuntan» de la ventana."""
        return [{k: v for k, v in c.items() if k != 'documento'} for c in correo.cotizaciones_a_adjuntar(construir(vehiculo)['filas'])]

    def get(self, request, pk):
        if request.GET.get('cotizacion_pdf') or request.GET.get('portal_pdf'):
            # Ver el PDF (subido o del portal): se sirve por aquí (con permiso), nunca por un enlace público de /media.
            if request.GET.get('portal_pdf'):
                origen = get_object_or_404(Cotizacion.objects.select_related('aseguradora'), pk=request.GET['portal_pdf'], vehiculo_id=pk)
                archivo = origen.pdf
            else:
                origen = get_object_or_404(ValorExterno.objects.select_related('aseguradora'), pk=request.GET['cotizacion_pdf'], vehiculo_id=pk)
                archivo = origen.documento
            if not archivo:
                raise Http404
            return FileResponse(archivo.open('rb'), content_type='application/pdf', filename=f'Cotización {origen.aseguradora.name}.pdf')
        vehiculo = get_object_or_404(Vehiculo.objects.select_related('tomador', 'zona_circulacion__departamento'), pk=pk)
        plantilla = correo.plantilla_para(vehiculo, request.GET.get('plantilla'))
        if plantilla is None:
            return JsonResponse({'error': 'No hay plantillas de correo activas. Créelas en Configuraciones › Plantillas de correo.'})
        armado = correo.armar(plantilla, vehiculo, request.user)
        solo = '?solo_diferencias=1' if request.GET.get('solo_diferencias') == '1' else ''
        enviados = [{
            'fecha': timezone.localtime(c.created_at).strftime('%d/%m/%Y %H:%M'),
            'para': c.para, 'estado': c.estado, 'estado_display': c.get_estado_display(),
            'por': (c.enviado_por.names or c.enviado_por.username) if c.enviado_por else '',
        } for c in CorreoEnviado.objects.filter(vehiculo=vehiculo).select_related('enviado_por')[:5]]
        return JsonResponse({
            'plantillas': [{'id': p.pk, 'nombre': p.nombre, 'predeterminada': p.predeterminada}
                           for p in PlantillaCorreo.objects.filter(is_active=True, tipo_seguro='autos').order_by('-predeterminada', 'nombre')],
            'plantilla_id': plantilla.pk,
            'de': armado['de'],
            'para': ', '.join(armado['para']),
            'cc': ', '.join(armado['cc']),
            'asunto': armado['asunto'],
            'html': armado['html'],
            'avisos': armado['avisos'],
            'adjunto': armado['adjunto'],
            'cotizaciones': [{k: v for k, v in c.items() if k != 'documento'} for c in armado['cotizaciones']],
            'pdf_url': reverse('vehiculo_comparativo_pdf', args=[vehiculo.pk]) + solo,
            'puede_enviar': bool(plantilla.cuenta and plantilla.cuenta.is_active and plantilla.cuenta.clave),
            'enviados': enviados,
        })

    def post(self, request, pk):
        vehiculo = get_object_or_404(Vehiculo.objects.select_related('tomador'), pk=pk)
        accion = request.POST.get('action')
        if accion in ('subir_cotizacion', 'quitar_cotizacion'):
            return self._cotizacion_manual(request, vehiculo, accion)
        plantilla = correo.plantilla_para(vehiculo, request.POST.get('plantilla'))
        if plantilla is None:
            return JsonResponse({'error': 'No hay plantillas de correo activas.'}, status=400)
        try:
            pdf = None
            if plantilla.adjuntar_pdf:
                pdf = correo.pdf_comparativo(request, vehiculo, solo_diferencias=request.POST.get('solo_diferencias') == '1')
            registro = correo.enviar(plantilla, vehiculo, request.user, request.POST.get('para', ''),
                                     request.POST.get('cc', ''), request.POST.get('asunto', ''), pdf=pdf)
        except correo.CorreoError as e:
            return JsonResponse({'error': str(e)}, status=400)
        return JsonResponse({'ok': True, 'mensaje': f'Correo enviado a {registro.para}' + (f' (CC {registro.cc})' if registro.cc else '') + '.'})

    def _cotizacion_manual(self, request, vehiculo, accion):
        """Sube o quita el PDF de la cotización de una de las más baratas: de un valor manual (tipo 'manual') o de una
        cotización de bot cuyo PDF no bajó del portal o se quiere cambiar (tipo 'bot')."""
        if request.POST.get('tipo') == 'bot':
            origen = Cotizacion.objects.select_related('aseguradora').filter(pk=request.POST.get('ref_id'), vehiculo=vehiculo).first()
            campo = 'pdf'
        else:
            origen = ValorExterno.objects.select_related('aseguradora').filter(
                pk=request.POST.get('ref_id') or request.POST.get('valor_id'), vehiculo=vehiculo).first()
            campo = 'documento'
        if origen is None:
            return JsonResponse({'error': 'Ese valor ya no existe: vuelva a abrir el correo.'}, status=404)
        nombre = origen.aseguradora.name
        actual = getattr(origen, campo)
        if accion == 'subir_cotizacion':
            try:
                archivo = correo.leer_pdf_subido(request.FILES.get('archivo'))
            except correo.CorreoError as e:
                return JsonResponse({'error': str(e)}, status=400)
            if actual:
                actual.delete(save=False)
            if campo == 'pdf':
                origen.pdf_descargado_en = timezone.now()
            getattr(origen, campo).save('cotizacion.pdf', archivo, save=True)
            registrar_evento(vehiculo, 'valor', '', f'{nombre}: PDF de la cotización adjuntado',
                             'Para el correo al cliente', request.user)
        else:
            if actual:
                actual.delete(save=True)
            registrar_evento(vehiculo, 'valor', f'{nombre}: PDF de la cotización', 'Quitado', 'Correo al cliente', request.user)
        return JsonResponse({'ok': True, 'cotizaciones': self._cotizaciones(vehiculo)})


class ComparativoValorManualView(StrictPermissionMixin, View):
    """Corrige o elimina el valor manual (aseguradora sin bot) que muestra el comparativo.

    Corregir registra un valor nuevo (el anterior queda como historial y el comparativo toma el más reciente);
    eliminar borra todos los valores manuales de esa aseguradora para el vehículo, para que no reaparezca uno viejo.
    Las dos acciones quedan en el historial del vehículo."""
    permission_required = 'policies.add_valor_externo'

    def post(self, request, pk, valor_id):
        vehiculo = get_object_or_404(Vehiculo, pk=pk)
        actual = ValorExterno.objects.select_related('aseguradora').filter(pk=valor_id, vehiculo=vehiculo).first()
        if actual is None:
            return JsonResponse({'error': 'Ese valor ya no existe: recargue el comparativo.'}, status=404)
        aseguradora = actual.aseguradora
        anterior = dinero(actual.valor)
        accion = request.POST.get('action')
        if accion == 'editar':
            valor = _leer_valor(request.POST.get('valor'))
            if valor is None:
                return JsonResponse({'error': 'El valor debe ser un número mayor que cero.'}, status=400)
            if valor == actual.valor:
                return JsonResponse({'ok': True})
            ValorExterno.objects.create(vehiculo=vehiculo, aseguradora=aseguradora, valor=valor, valor_2=actual.valor_2,
                                        asesor=request.user, documento=actual.documento.name or None)
            registrar_evento(vehiculo, 'valor', f'{aseguradora.name}: {anterior}', f'{aseguradora.name}: {dinero(valor)}',
                             'Valor manual corregido en el comparativo', request.user)
        elif accion == 'eliminar':
            with transaction.atomic():
                ValorExterno.objects.filter(vehiculo=vehiculo, aseguradora=aseguradora).delete()
                registrar_evento(vehiculo, 'valor', f'{aseguradora.name}: {anterior}', 'Eliminado',
                                 'Valor manual eliminado del comparativo', request.user)
        else:
            return JsonResponse({'error': 'No ha seleccionado ninguna opción'}, status=400)
        return JsonResponse({'ok': True})
