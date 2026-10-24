from django.urls import path

from core.policies.views.solicitud.views import (
    SolicitudCotizacionCreateView,
    consultar_registro,
    estado_cotizaciones,
    iniciar_cotizacion,
    proceso_vehiculo,
    reintentar_cotizacion,
    verificar_cotizacion,
)
from core.policies.views.aseguradora.views import (
    AseguradoraCoberturasView,
    AseguradoraCreateView,
    AseguradoraListView,
    AseguradoraUpdateView,
    CoberturaFormView,
)
from core.policies.views.asesor.views import AsesorCreateView, AsesorListView, AsesorUpdateView
from core.policies.views.comparativo.views import ComparativoImprimirView, ComparativoValoresView, ComparativoView
from core.policies.views.vehiculo.views import VehiculoListView
from core.policies.views.vehiculo_registrado.views import VehiculoRegistradoListView

urlpatterns = [
    path('solicitud/', SolicitudCotizacionCreateView.as_view(), name='solicitud_cotizacion_create'),
    path('solicitud/consultar/', consultar_registro, name='solicitud_consultar_registro'),
    path('solicitud/cotizar/', iniciar_cotizacion, name='solicitud_iniciar_cotizacion'),
    path('solicitud/cotizar/estado/', estado_cotizaciones, name='solicitud_estado_cotizaciones'),
    path('solicitud/cotizar/verificacion/', verificar_cotizacion, name='solicitud_verificar_cotizacion'),
    path('solicitud/cotizar/reintentar/', reintentar_cotizacion, name='solicitud_reintentar_cotizacion'),
    path('aseguradoras/', AseguradoraListView.as_view(), name='aseguradora_list'),
    path('aseguradoras/nueva/', AseguradoraCreateView.as_view(), name='aseguradora_create'),
    path('aseguradoras/<int:pk>/editar/', AseguradoraUpdateView.as_view(), name='aseguradora_update'),
    path('aseguradoras/<int:pk>/coberturas/', AseguradoraCoberturasView.as_view(), name='aseguradora_coberturas'),
    path('aseguradoras/<int:pk>/coberturas/nueva/', CoberturaFormView.as_view(), name='cobertura_create'),
    path('aseguradoras/<int:pk>/coberturas/<int:ficha>/editar/', CoberturaFormView.as_view(), name='cobertura_update'),
    path('asesores/', AsesorListView.as_view(), name='asesor_list'),
    path('asesores/nuevo/', AsesorCreateView.as_view(), name='asesor_create'),
    path('asesores/<int:pk>/editar/', AsesorUpdateView.as_view(), name='asesor_update'),
    path('vehiculos/', VehiculoListView.as_view(), name='vehiculo_list'),
    path('vehiculos/registrados/', VehiculoRegistradoListView.as_view(), name='vehiculo_registrado_list'),
    path('vehiculos/<int:pk>/proceso/', proceso_vehiculo, name='vehiculo_proceso'),
    path('vehiculos/<int:pk>/comparativo/', ComparativoView.as_view(), name='vehiculo_comparativo'),
    path('vehiculos/<int:pk>/comparativo/imprimir/', ComparativoImprimirView.as_view(), name='vehiculo_comparativo_imprimir'),
    path('vehiculos/<int:pk>/comparativo/valores/', ComparativoValoresView.as_view(), name='vehiculo_comparativo_valores'),
]
