"""URLs del dominio de la plataforma (schema «public»): el panel de ASLAN. Las empresas NO llegan aquí: su dominio usa config/urls.py."""
from django.urls import path

from core.tenants import gestion as g
from core.tenants import plataforma as p
from core.tenants import seguridad_panel as sp

urlpatterns = [
    path('', p.inicio, name='plataforma_inicio'),
    path('ingresar/', p.ingresar, name='plataforma_ingresar'),
    path('salir/', p.salir, name='plataforma_salir'),
    path('empresas/', p.empresas, name='plataforma_empresas'),
    path('empresas/nueva/', g.empresa_nueva, name='plataforma_empresa_nueva'),
    path('empresas/nueva/<str:schema>/', g.empresa_nueva_avance, name='plataforma_empresa_nueva_avance'),
    path('empresas/nueva/<str:schema>/estado/', g.empresa_nueva_estado, name='plataforma_empresa_nueva_estado'),
    path('empresas/<str:schema>/', p.empresa, name='plataforma_empresa'),
    path('empresas/<str:schema>/plan/', p.guardar_plan, name='plataforma_plan'),
    path('empresas/<str:schema>/facturacion/', p.guardar_facturacion, name='plataforma_facturacion'),
    path('empresas/<str:schema>/dominios/agregar/', p.agregar_dominio, name='plataforma_dominio_agregar'),
    path('empresas/<str:schema>/dominios/<int:pk>/quitar/', p.quitar_dominio, name='plataforma_dominio_quitar'),
    path('empresas/<str:schema>/modulos/', g.guardar_modulos, name='plataforma_modulos'),
    path('empresas/<str:schema>/pagos/registrar/', g.pago_registrar, name='plataforma_pago_registrar'),
    path('empresas/<str:schema>/pagos/<int:pk>/eliminar/', g.pago_eliminar, name='plataforma_pago_eliminar'),
    path('empresas/<str:schema>/soporte/', g.soporte_pagina, name='plataforma_soporte'),
    path('empresas/<str:schema>/soporte/<int:pk>/desbloquear/', g.soporte_desbloquear, name='plataforma_soporte_desbloquear'),
    path('empresas/<str:schema>/soporte/<int:pk>/clave/', g.soporte_clave, name='plataforma_soporte_clave'),
    path('empresas/<str:schema>/soporte/<int:pk>/entrar/', g.soporte_entrar, name='plataforma_soporte_entrar'),
    path('respaldos/', g.respaldos_pagina, name='plataforma_respaldos'),
    path('respaldos/crear/', g.respaldos_crear, name='plataforma_respaldos_crear'),
    path('respaldos/<str:nombre>/descargar/', g.respaldos_descargar, name='plataforma_respaldo_descargar'),
    path('respaldos/<str:nombre>/verificar/', g.respaldos_verificar, name='plataforma_respaldo_verificar'),
    path('respaldos/<str:nombre>/eliminar/', g.respaldos_eliminar, name='plataforma_respaldo_eliminar'),
    path('salud/', g.salud_pagina, name='plataforma_salud'),
    path('auditoria/', g.auditoria_pagina, name='plataforma_auditoria'),
    path('anuncios/', g.anuncios_pagina, name='plataforma_anuncios'),
    path('anuncios/crear/', g.anuncio_crear, name='plataforma_anuncio_crear'),
    path('anuncios/<int:pk>/cambiar/', g.anuncio_cambiar, name='plataforma_anuncio_cambiar'),
    path('seguridad/', sp.seguridad_pagina, name='plataforma_seguridad'),
    path('seguridad/clave/', sp.cambiar_clave, name='plataforma_seguridad_clave'),
    path('seguridad/dos-pasos/iniciar/', sp.totp_iniciar, name='plataforma_totp_iniciar'),
    path('seguridad/dos-pasos/confirmar/', sp.totp_confirmar, name='plataforma_totp_confirmar'),
    path('seguridad/dos-pasos/desactivar/', sp.totp_desactivar, name='plataforma_totp_desactivar'),
    path('seguridad/ips/', sp.guardar_ips, name='plataforma_ips'),
]
