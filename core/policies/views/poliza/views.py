import json
from datetime import date, timedelta
from decimal import Decimal

from django.db import transaction
from django.db.models import Count, Exists, Min, OuterRef, Q
from django.http import HttpResponse
from django.shortcuts import get_object_or_404
from django.urls import reverse, reverse_lazy
from django.utils.decorators import method_decorator
from django.views.generic import TemplateView, View
from django.views.decorators.gzip import gzip_page

from core.policies.forms import PolizaForm
from core.policies.models import Aseguradora, Asesor, Cotizacion, CuotaPoliza, Poliza, TipoPoliza, Vehiculo
from core.policies.services.polizas import (DIAS_AVISO_RENOVACION, MAX_CUOTAS, asesor_de, generar_cuotas, opciones_poliza,
                                           resolver_opcion, sumar_meses)
from core.security.mixins import StrictPermissionMixin

MODULE_NAME = 'Pólizas'
FILTROS = (
    ('todas', 'Todas'),
    ('vigentes', 'Vigentes'),
    ('por_renovar', f'Por renovar ({DIAS_AVISO_RENOVACION} días)'),
    ('vencidas', 'Vencidas'),
    ('cuotas', 'Cuotas atrasadas'),
    ('cuotas_semana', 'Cuotas de esta semana'),
    ('cartera', 'Comisión pendiente'),
    ('canceladas', 'Canceladas'),
)
DIAS_CUOTAS_SEMANA = 7


def _json(data, status=200):
    return HttpResponse(json.dumps(data), content_type='application/json', status=status)


def filtrar(queryset, filtro):
    hoy = date.today()
    if filtro == 'vigentes':
        return queryset.filter(estado='generada', fecha_renovacion__gte=hoy)
    if filtro == 'cuotas_semana':
        semana = CuotaPoliza.objects.filter(poliza=OuterRef('pk'), pagada=False, fecha__gte=hoy, fecha__lte=hoy + timedelta(days=DIAS_CUOTAS_SEMANA))
        return queryset.filter(estado='generada').filter(Exists(semana))
    if filtro == 'por_renovar':
        return queryset.filter(estado='generada', fecha_renovacion__gte=hoy, fecha_renovacion__lte=hoy + timedelta(days=DIAS_AVISO_RENOVACION))
    if filtro == 'vencidas':
        return queryset.filter(estado='generada', fecha_renovacion__lt=hoy)
    if filtro == 'cuotas':
        atrasadas = CuotaPoliza.objects.filter(poliza=OuterRef('pk'), pagada=False, fecha__lt=hoy)
        return queryset.filter(estado='generada').filter(Exists(atrasadas))
    if filtro == 'cartera':
        return queryset.filter(estado='generada', estado_comision='cartera')
    if filtro == 'canceladas':
        return queryset.filter(estado='cancelada')
    return queryset


# Los datos de la tabla (JSON) viajan comprimidos: con miles de filas pesan ~10 veces menos.
@method_decorator(gzip_page, name='post')
class PolizaListView(StrictPermissionMixin, TemplateView):
    template_name = 'poliza/list.html'
    permission_required = 'policies.view_poliza'

    def post(self, request, *args, **kwargs):
        data = {}
        action = request.POST.get('action')
        try:
            if action == 'search':
                hoy = date.today()
                base = self._acotar(Poliza.objects.all(), request.POST)
                qs = (base.select_related('vehiculo', 'tomador', 'tomador__document_type', 'asesor', 'aseguradora',
                                          'tipo_poliza', 'zona_circulacion', 'zona_circulacion__departamento')
                      .annotate(cuotas_atrasadas=Count('cuotas', filter=Q(cuotas__pagada=False, cuotas__fecha__lt=hoy)),
                                cuotas_pagadas=Count('cuotas', filter=Q(cuotas__pagada=True)),
                                proxima_cuota=Min('cuotas__fecha', filter=Q(cuotas__pagada=False))))
                filas = []
                for p in filtrar(qs, request.POST.get('filtro', 'todas')):
                    item = p.toJSON()
                    item['cuotas_atrasadas'] = p.cuotas_atrasadas
                    item['cuotas_pagadas'] = p.cuotas_pagadas
                    item['proxima_cuota'] = p.proxima_cuota.strftime('%Y-%m-%d') if p.proxima_cuota else None
                    item['otro_celular'] = p.tomador.phone
                    filas.append(item)
                data = {'filas': filas, 'conteos': {valor: filtrar(base, valor).count() for valor, _ in FILTROS}}
            elif action == 'delete':
                if not request.user.has_perm('policies.delete_poliza'):
                    data['error'] = 'Tu perfil no puede eliminar pólizas.'
                else:
                    Poliza.objects.get(pk=request.POST.get('id')).delete()
            else:
                data['error'] = 'No ha seleccionado ninguna opción'
        except Exception as e:
            data['error'] = str(e)
        return _json(data)

    @staticmethod
    def _acotar(queryset, datos):
        """Filtros de la barra: asesor, aseguradora y mes de vencimiento (AAAA-MM)."""
        if (datos.get('asesor') or '').isdigit():
            queryset = queryset.filter(asesor_id=datos['asesor'])
        if (datos.get('aseguradora') or '').isdigit():
            queryset = queryset.filter(aseguradora_id=datos['aseguradora'])
        mes = (datos.get('mes') or '').split('-')
        if len(mes) == 2 and all(x.isdigit() for x in mes):
            queryset = queryset.filter(fecha_renovacion__year=int(mes[0]), fecha_renovacion__month=int(mes[1]))
        return queryset

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        hoy = date.today()
        context['title'] = 'Pólizas tomadas'
        context['module_name'] = MODULE_NAME
        context['list_url'] = reverse_lazy('poliza_list')
        if self.request.user.has_perm('policies.add_poliza'):
            context['create_url'] = reverse_lazy('poliza_create')
        context['filtros'] = FILTROS
        context['filtro'] = self.request.GET.get('filtro', 'todas')
        context['asesores'] = Asesor.objects.filter(polizas__isnull=False).distinct().order_by('nombres')
        context['aseguradoras'] = Aseguradora.objects.filter(polizas__isnull=False).distinct().order_by('name')
        context['dias_aviso'] = DIAS_AVISO_RENOVACION
        context['hoy'] = hoy
        return context


class _PolizaFormMixin(StrictPermissionMixin):
    template_name = 'poliza/form.html'
    accion = None

    def _guardar(self, form, vehiculo):
        with transaction.atomic():
            poliza = form.save(commit=False)
            if not poliza.pk:
                poliza.vehiculo = vehiculo
                poliza.tomador = vehiculo.tomador  # el dueño de ESTE momento; no cambia si después vende el carro
                poliza.creado_por = self.request.user
                cotizacion_id = self.request.POST.get('cotizacion') or None
                poliza.cotizacion = Cotizacion.objects.filter(pk=cotizacion_id, vehiculo=vehiculo).first() if cotizacion_id else None
            poliza.save()
            generar_cuotas(poliza)
        return poliza

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['list_url'] = reverse_lazy('poliza_list')
        context['module_name'] = MODULE_NAME
        context['action'] = self.accion
        return context


class PolizaCreateView(_PolizaFormMixin, TemplateView):
    """Registrar la póliza que eligió el cliente. Desde el comparativo llega con el vehículo, la aseguradora, el plan, el
    valor y la cotización ya elegidos; también se puede registrar a mano (ej. una póliza del histórico)."""
    permission_required = 'policies.add_poliza'
    accion = 'add'

    def _vehiculo(self):
        pk = self.request.GET.get('vehiculo') or self.request.POST.get('vehiculo')
        return Vehiculo.objects.select_related('tomador', 'tomador__document_type', 'zona_circulacion').filter(pk=pk).first() if pk else None

    def _inicial(self, vehiculo):
        g = self.request.GET
        hoy = date.today()
        inicial = {
            'zona_circulacion': vehiculo.zona_circulacion_id,
            'asesor': getattr(asesor_de(self.request.user), 'pk', None),
            'tipo_poliza': getattr(TipoPoliza.objects.filter(code='todo-riesgo').first() or TipoPoliza.objects.filter(is_active=True).first(), 'pk', None),
            'fecha_renovacion': sumar_meses(hoy, 12),
            'numero_cuotas': 1,
            'aseguradora': g.get('aseguradora'),
            'plan': g.get('plan', '')[:80],
        }
        cotizacion = Cotizacion.objects.filter(pk=g.get('cotizacion'), vehiculo=vehiculo).first() if g.get('cotizacion') else None
        if cotizacion:
            inicial['aseguradora'] = cotizacion.aseguradora_id
            inicial['tipo_poliza'] = cotizacion.tipo_poliza_id
            for campo in ('valor_sin_iva', 'valor_comision', 'descuentos'):
                if getattr(cotizacion, campo):
                    inicial[campo] = getattr(cotizacion, campo)
            if cotizacion.fecha_descuento:
                inicial['fecha_descuento'] = cotizacion.fecha_descuento
        valor = (g.get('valor') or '').replace('.', '')
        if valor.isdigit():
            inicial['prima_total'] = Decimal(valor)
        elif cotizacion and cotizacion.prima_total:
            inicial['prima_total'] = cotizacion.prima_total
        return inicial, cotizacion

    def post(self, request, *args, **kwargs):
        data = {}
        try:
            vehiculo = self._vehiculo()
            if request.POST.get('action') != 'add':
                data['error'] = 'No ha seleccionado ninguna opción'
            elif vehiculo is None:
                data['error'] = 'Elige el vehículo de la póliza.'
            else:
                form = PolizaForm(request.POST, vehiculo=vehiculo)
                if form.is_valid():
                    poliza = self._guardar(form, vehiculo)
                    data = {'id': poliza.pk, 'url': reverse('poliza_update', args=[poliza.pk])}
                else:
                    data['error'] = {campo: list(errores) for campo, errores in form.errors.items()}
        except Exception as e:
            data['error'] = str(e)
        return _json(data)

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        vehiculo = self._vehiculo()
        context['title'] = 'Registrar póliza elegida'
        context['vehiculo'] = vehiculo
        if vehiculo is None:
            context['vehiculos'] = Vehiculo.objects.select_related('tomador').order_by('placa')
            return context
        inicial, cotizacion = self._inicial(vehiculo)
        form = PolizaForm(initial=inicial, vehiculo=vehiculo)
        context['form'] = form
        context['tomador'] = vehiculo.tomador
        context['cotizacion'] = cotizacion
        context['polizas_previas'] = vehiculo.polizas.select_related('aseguradora', 'zona_circulacion').order_by('-fecha_renovacion')[:5]
        return context


class PolizaUpdateView(_PolizaFormMixin, TemplateView):
    permission_required = 'policies.change_poliza'
    accion = 'edit'

    def get_object(self):
        return get_object_or_404(Poliza.objects.select_related('vehiculo', 'tomador', 'tomador__document_type', 'cotizacion',
                                                               'creado_por'), pk=self.kwargs['pk'])

    def post(self, request, *args, **kwargs):
        data = {}
        try:
            poliza = self.get_object()
            action = request.POST.get('action')
            if action == 'edit':
                form = PolizaForm(request.POST, instance=poliza, vehiculo=poliza.vehiculo)
                if form.is_valid():
                    self._guardar(form, poliza.vehiculo)
                else:
                    data['error'] = {campo: list(errores) for campo, errores in form.errors.items()}
            elif action == 'cuota':
                cuota = poliza.cuotas.get(pk=request.POST.get('id'))
                cuota.pagada = request.POST.get('pagada') == 'true'
                cuota.fecha_pagada = date.today() if cuota.pagada else None
                cuota.save(update_fields=['pagada', 'fecha_pagada'])
                data = cuota.toJSON()
            else:
                data['error'] = 'No ha seleccionado ninguna opción'
        except Exception as e:
            data['error'] = str(e)
        return _json(data)

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        poliza = self.get_object()
        context['title'] = f'Póliza de {poliza.vehiculo.placa}'
        context['object'] = poliza
        context['vehiculo'] = poliza.vehiculo
        context['tomador'] = poliza.tomador
        context['cotizacion'] = poliza.cotizacion
        context['form'] = PolizaForm(instance=poliza, vehiculo=poliza.vehiculo)
        context['cuotas'] = list(poliza.cuotas.all())
        context['hoy'] = date.today()
        return context


class PolizaConvertirView(StrictPermissionMixin, View):
    """«El cliente eligió esta»: convierte una solicitud cotizada en póliza sin volver a llenar nada.

    GET ?vehiculo=ID → opciones cotizadas (aseguradora y plan con su valor) y los valores por defecto.
    POST → crea la póliza con lo de la cotización elegida; solo se piden la forma de pago y la fecha de pago."""
    permission_required = 'policies.add_poliza'

    def get(self, request):
        vehiculo = get_object_or_404(Vehiculo.objects.select_related('tomador'), pk=request.GET.get('vehiculo') or 0)
        hoy = date.today()
        vigente = (vehiculo.polizas.filter(estado='generada', fecha_renovacion__gte=hoy).select_related('aseguradora')
                   .order_by('-fecha_renovacion').first())
        asesor = asesor_de(request.user)
        return _json({
            'placa': vehiculo.placa,
            'tomador': vehiculo.tomador.names,
            'opciones': opciones_poliza(vehiculo),
            'vigente': {'aseguradora': vigente.aseguradora.name, 'vence': vigente.fecha_renovacion.strftime('%d/%m/%Y')} if vigente else None,
            'asesores': [{'id': a.pk, 'nombre': a.nombres} for a in Asesor.objects.filter(is_active=True).order_by('nombres')],
            'asesor_id': asesor.pk if asesor else None,
            'fecha_renovacion': sumar_meses(hoy, 12).strftime('%Y-%m-%d'),
            'max_cuotas': MAX_CUOTAS,
        })

    def post(self, request):
        vehiculo = get_object_or_404(Vehiculo.objects.select_related('tomador'), pk=request.POST.get('vehiculo') or 0)
        try:
            elegida = resolver_opcion(vehiculo, request.POST.get('opcion', ''))
        except ValueError as exc:
            return _json({'error': str(exc)}, status=400)
        tipo = elegida['tipo_poliza'] or TipoPoliza.objects.filter(code='todo-riesgo').first() or TipoPoliza.objects.filter(is_active=True).first()
        entero = lambda v: str(int(v or 0))
        datos = {
            'asesor': request.POST.get('asesor', ''), 'aseguradora': elegida['aseguradora'].pk, 'tipo_poliza': tipo.pk if tipo else '',
            'plan': elegida['plan'][:80], 'numero_poliza': request.POST.get('numero_poliza', '').strip(),
            'zona_circulacion': elegida['zona_circulacion_id'], 'fecha_renovacion': request.POST.get('fecha_renovacion', ''),
            'prima_total': entero(elegida['prima_total']), 'valor_sin_iva': entero(elegida['valor_sin_iva']),
            'valor_comision': entero(elegida['valor_comision']), 'descuentos': entero(elegida['descuentos']),
            'fecha_descuento': elegida['fecha_descuento'].strftime('%Y-%m-%d') if elegida['fecha_descuento'] else '',
            'numero_cuotas': request.POST.get('numero_cuotas', '1'), 'fecha_pago': request.POST.get('fecha_pago', ''),
            'estado_comision': 'cartera', 'observaciones': '',
        }
        form = PolizaForm(datos, vehiculo=vehiculo)
        if not form.is_valid():
            mensajes = [f'{form.fields[c].label}: {" ".join(e)}' if c in form.fields else ' '.join(e) for c, e in form.errors.items()]
            return _json({'error': ' · '.join(mensajes)}, status=400)
        with transaction.atomic():
            poliza = form.save(commit=False)
            poliza.vehiculo, poliza.tomador, poliza.cotizacion, poliza.creado_por = vehiculo, vehiculo.tomador, elegida['cotizacion'], request.user
            poliza.save()
            generar_cuotas(poliza)
        return _json({'id': poliza.pk, 'url': reverse('poliza_update', args=[poliza.pk]),
                      'resumen': f'{poliza.aseguradora.name}{" · " + poliza.plan if poliza.plan else ""} · {poliza.forma_pago}'})
