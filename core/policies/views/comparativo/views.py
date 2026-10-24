import hashlib
import json
from decimal import Decimal, InvalidOperation

from django.db import transaction
from django.http import Http404, JsonResponse
from django.conf import settings
from django.shortcuts import get_object_or_404
from django.utils import timezone
from django.urls import reverse, reverse_lazy
from django.views.generic import TemplateView, View

from core.policies.models import Aseguradora, ValorExterno, Vehiculo
from core.pos.models import Company
from core.policies.services.comparativo import aseguradoras_sin_bot, construir, dinero, indicadores, resumen_cliente
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
            'mas_barata': filas[0] if filas else None,
            'puede_registrar_valores': self.request.user.has_perm('policies.add_valor_externo'),
            'aseguradoras_sin_bot': aseguradoras_sin_bot(),
            'guardar_url': reverse('vehiculo_comparativo_valores', args=[vehiculo.pk]),
            'comparativo_url': reverse('vehiculo_comparativo', args=[vehiculo.pk]),
            'imprimir_url': reverse('vehiculo_comparativo_imprimir', args=[vehiculo.pk]),
            'vehiculo_id': vehiculo.pk,
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

        sin_bot = {a.pk: a for a in aseguradoras_sin_bot()}
        nuevos, vistas = [], set()
        for numero, fila in enumerate(filas, start=1):
            try:
                aseguradora_id = int(fila.get('aseguradora'))
            except (TypeError, ValueError, AttributeError):
                return JsonResponse({'error': f'Fila {numero}: elige la aseguradora'}, status=400)
            aseguradora = sin_bot.get(aseguradora_id)
            if aseguradora is None:
                return JsonResponse({'error': f'Fila {numero}: la aseguradora no existe, está inactiva o ya cotiza con bot'}, status=400)
            if aseguradora_id in vistas:
                return JsonResponse({'error': f'{aseguradora.name} está repetida: registra un solo valor por aseguradora'}, status=400)
            vistas.add(aseguradora_id)
            try:
                valor = Decimal(str(fila.get('valor', '')).replace('.', '').replace(',', '').replace('$', '').strip())
            except InvalidOperation:
                return JsonResponse({'error': f'{aseguradora.name}: el valor no es un número válido'}, status=400)
            if valor <= 0 or valor > VALOR_MAXIMO:
                return JsonResponse({'error': f'{aseguradora.name}: el valor debe ser mayor que cero'}, status=400)
            nuevos.append(ValorExterno(vehiculo=vehiculo, aseguradora=aseguradora, valor=valor, asesor=request.user))

        with transaction.atomic():
            ValorExterno.objects.bulk_create(nuevos)
        return JsonResponse({'url': reverse('vehiculo_comparativo', args=[vehiculo.pk])})
