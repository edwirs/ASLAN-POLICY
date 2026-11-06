from django.urls import path

from core.policies.views.solicitud.views import (
    SolicitudCotizacionCreateView,
    consultar_registro,
    estado_cotizaciones,
    iniciar_cotizacion,
    proceso_vehiculo,
    reactivar_placa,
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
from core.policies.views.asistente.views import (
    asistente_accion,
    asistente_chat,
    asistente_conversacion,
    asistente_conversaciones,
    asistente_eliminar,
)
from core.policies.views.asesor.views import AsesorCreateView, AsesorListView, AsesorUpdateView
from core.policies.views.agente.views import AgenteOficinaView
from core.policies.views.buscar import BuscarView
from core.policies.views.comparativo.views import (ComparativoCorreoView, ComparativoImprimirView, ComparativoPdfView,
                                                   ComparativoValoresView, ComparativoValorManualView, ComparativoView)
from core.policies.views.plantilla_correo.views import CuentaCorreoFormView, PlantillaCorreoFormView, PlantillaCorreoListView
from core.policies.views.poliza.views import PolizaConvertirView, PolizaCreateView, PolizaListView, PolizaUpdateView
from core.policies.views.vehiculo.views import VehiculoListView
from core.policies.views.vehiculo_registrado.views import VehiculoRegistradoListView

urlpatterns = [
    path('solicitud/', SolicitudCotizacionCreateView.as_view(), name='solicitud_cotizacion_create'),
    path('solicitud/consultar/', consultar_registro, name='solicitud_consultar_registro'),
    path('solicitud/cotizar/', iniciar_cotizacion, name='solicitud_iniciar_cotizacion'),
    path('solicitud/cotizar/estado/', estado_cotizaciones, name='solicitud_estado_cotizaciones'),
    path('solicitud/cotizar/verificacion/', verificar_cotizacion, name='solicitud_verificar_cotizacion'),
    path('solicitud/cotizar/reintentar/', reintentar_cotizacion, name='solicitud_reintentar_cotizacion'),
    path('solicitud/reactivar-placa/', reactivar_placa, name='solicitud_reactivar_placa'),
    path('aseguradoras/', AseguradoraListView.as_view(), name='aseguradora_list'),
    path('agente-oficina/', AgenteOficinaView.as_view(), name='agente_oficina'),
    path('aseguradoras/nueva/', AseguradoraCreateView.as_view(), name='aseguradora_create'),
    path('aseguradoras/<int:pk>/editar/', AseguradoraUpdateView.as_view(), name='aseguradora_update'),
    path('aseguradoras/<int:pk>/coberturas/', AseguradoraCoberturasView.as_view(), name='aseguradora_coberturas'),
    path('aseguradoras/<int:pk>/coberturas/nueva/', CoberturaFormView.as_view(), name='cobertura_create'),
    path('aseguradoras/<int:pk>/coberturas/<int:ficha>/editar/', CoberturaFormView.as_view(), name='cobertura_update'),
    path('asistente/', asistente_chat, name='asistente_chat'),
    path('asistente/conversaciones/', asistente_conversaciones, name='asistente_conversaciones'),
    path('asistente/conversaciones/<int:pk>/', asistente_conversacion, name='asistente_conversacion'),
    path('asistente/conversaciones/<int:pk>/eliminar/', asistente_eliminar, name='asistente_eliminar'),
    path('asistente/accion/', asistente_accion, name='asistente_accion'),
    path('asesores/', AsesorListView.as_view(), name='asesor_list'),
    path('asesores/nuevo/', AsesorCreateView.as_view(), name='asesor_create'),
    path('asesores/<int:pk>/editar/', AsesorUpdateView.as_view(), name='asesor_update'),
    path('buscar/', BuscarView.as_view(), name='buscar_global'),
    path('polizas/', PolizaListView.as_view(), name='poliza_list'),
    path('polizas/nueva/', PolizaCreateView.as_view(), name='poliza_create'),
    path('polizas/convertir/', PolizaConvertirView.as_view(), name='poliza_convertir'),
    path('polizas/<int:pk>/editar/', PolizaUpdateView.as_view(), name='poliza_update'),
    path('vehiculos/', VehiculoListView.as_view(), name='vehiculo_list'),
    path('vehiculos/registrados/', VehiculoRegistradoListView.as_view(), name='vehiculo_registrado_list'),
    path('vehiculos/<int:pk>/proceso/', proceso_vehiculo, name='vehiculo_proceso'),
    path('vehiculos/<int:pk>/comparativo/', ComparativoView.as_view(), name='vehiculo_comparativo'),
    path('vehiculos/<int:pk>/comparativo/imprimir/', ComparativoImprimirView.as_view(), name='vehiculo_comparativo_imprimir'),
    path('vehiculos/<int:pk>/comparativo/valores/', ComparativoValoresView.as_view(), name='vehiculo_comparativo_valores'),
    path('vehiculos/<int:pk>/comparativo/valores/<int:valor_id>/', ComparativoValorManualView.as_view(),
         name='vehiculo_comparativo_valor_manual'),
    path('vehiculos/<int:pk>/comparativo/pdf/', ComparativoPdfView.as_view(), name='vehiculo_comparativo_pdf'),
    path('vehiculos/<int:pk>/comparativo/correo/', ComparativoCorreoView.as_view(), name='vehiculo_comparativo_correo'),
    path('plantillas-correo/', PlantillaCorreoListView.as_view(), name='plantilla_correo_list'),
    path('plantillas-correo/nueva/', PlantillaCorreoFormView.as_view(), name='plantilla_correo_create'),
    path('plantillas-correo/<int:pk>/', PlantillaCorreoFormView.as_view(), name='plantilla_correo_update'),
    path('plantillas-correo/cuentas/nueva/', CuentaCorreoFormView.as_view(), name='cuenta_correo_create'),
    path('plantillas-correo/cuentas/<int:pk>/', CuentaCorreoFormView.as_view(), name='cuenta_correo_update'),
]
