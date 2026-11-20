"""Seguimiento de correos: todos los correos de cotización (la cola y su historial) con su estado, para ver qué salió,
qué sigue pendiente de envío y qué falló."""
import json
import re
from datetime import datetime

from django.http import HttpResponse
from django.urls import reverse, reverse_lazy
from django.utils.decorators import method_decorator
from django.views.decorators.gzip import gzip_page
from django.views.generic import TemplateView

from django.db.models import Exists, OuterRef

from core.policies.models import CorreoAdjunto, CorreoEnviado
from core.policies.services import correo, horario_habil
from core.security.mixins import StrictPermissionMixin

MODULE_NAME = 'Cotizador'

# Estado guardado -> (grupo del filtro, cómo se muestra, color). «Programado» y «Enviando» son «Pendiente de envío».
ESTADOS = {
    'programado': ('pendiente', 'Pendiente de envío', 'warning'),
    'enviando': ('pendiente', 'Enviando…', 'info'),
    'enviado': ('enviado', 'Enviado', 'success'),
    'error': ('error', 'Error', 'danger'),
    'cancelado': ('cancelado', 'Cancelado', 'secondary'),
}
# Acción -> (permiso, función que la hace). Cada una revisa también el estado del correo (services/correo.py).
ACCIONES = {
    'cancelar': 'policies.cancel_correoenviado',
    'enviar_ahora': 'policies.send_correoenviado_ahora',
    'destinatarios': 'policies.change_correoenviado',
    'reprogramar': 'policies.reprogram_correoenviado',
    'reintentar': 'policies.retry_correoenviado',
}
FILTROS = (('todos', 'Todos'), ('pendiente', 'Pendientes de envío'), ('enviado', 'Enviados'), ('error', 'Con error'),
           ('cancelado', 'Cancelados'))


def _fecha(momento):
    return momento.astimezone(horario_habil.TZ_COLOMBIA).strftime('%Y-%m-%d %H:%M') if momento else None


def _usuario(usuario):
    return (usuario.names or usuario.username) if usuario else ''


def _fila(c):
    grupo, nombre, color = ESTADOS.get(c.estado, ('todos', c.get_estado_display(), 'secondary'))
    tomador = c.vehiculo.tomador
    return {
        'id': c.pk,
        'creado': _fecha(c.created_at),
        'placa': c.vehiculo.placa,
        'vehiculo_id': c.vehiculo_id,
        'cliente': tomador.names if tomador else '',
        'para': c.para,
        'cc': c.cc,
        'asunto': c.asunto,
        'estado': c.estado,
        'grupo': grupo,
        'estado_nombre': nombre,
        'color': color,
        'programado': horario_habil.texto_fecha(c.programado_para) if c.estado == 'programado' and c.programado_para else '',
        'enviado_en': _fecha(c.enviado_en),
        'error_envio': c.error,  # no «error»: esa clave es la de una falla de la consulta
        'intentos': c.intentos,
        'por': _usuario(c.enviado_por),
        'programado_iso': (c.programado_para.astimezone(horario_habil.TZ_COLOMBIA).strftime('%Y-%m-%dT%H:%M')
                           if c.estado == 'programado' and c.programado_para else ''),
        'sin_adjuntos': bool(c.adjunto) and not getattr(c, 'tiene_adjuntos', True),
        'cuenta': c.cuenta.correo if c.cuenta else c.remitente,
    }


def _frase(texto):
    """Cierra con punto sin duplicarlo («… a las 8:00 a. m.» ya termina en punto)."""
    return texto if texto.endswith('.') else texto + '.'


def _cuerpo_sin_imagenes(html):
    """El cuerpo guardado: las imágenes incrustadas (cid:) no se pueden mostrar fuera del correo, se quitan."""
    return re.sub(r'<img\b[^>]*src=["\']cid:[^"\']*["\'][^>]*>', '', html or '', flags=re.I)


@method_decorator(gzip_page, name='post')
class CorreoSeguimientoView(StrictPermissionMixin, TemplateView):
    template_name = 'correo_seguimiento/list.html'
    permission_required = 'policies.view_correoenviado'

    def post(self, request, *args, **kwargs):
        accion = request.POST.get('action')
        data = {}
        try:
            if accion == 'search':
                correos = (CorreoEnviado.objects.select_related('vehiculo__tomador', 'enviado_por', 'cuenta')
                           .annotate(tiene_adjuntos=Exists(CorreoAdjunto.objects.filter(correo=OuterRef('pk'))))
                           .order_by('-created_at', '-id'))
                data = [_fila(c) for c in correos]
            elif accion == 'detalle':
                c = (CorreoEnviado.objects.select_related('vehiculo__tomador', 'enviado_por', 'cuenta')
                     .annotate(tiene_adjuntos=Exists(CorreoAdjunto.objects.filter(correo=OuterRef('pk')))).get(pk=request.POST.get('id')))
                data = {**_fila(c), 'html': _cuerpo_sin_imagenes(c.html),
                        'adjuntos': [a.strip() for a in (c.adjunto or '').split(',') if a.strip()]}
            elif accion in ACCIONES:
                if not request.user.has_perm(ACCIONES[accion]):
                    data['error'] = 'Su perfil no cuenta con el permiso para esta acción.'
                else:
                    c = CorreoEnviado.objects.select_related('vehiculo', 'cuenta', 'enviado_por').get(pk=request.POST.get('id'))
                    data = self._accion(request, accion, c)
            else:
                data['error'] = 'No ha seleccionado ninguna opción'
        except correo.CorreoError as e:
            data = {'error': str(e)}
        except CorreoEnviado.DoesNotExist:
            data = {'error': 'Ese correo ya no existe.'}
        except Exception as e:
            data = {'error': str(e)}
        return HttpResponse(json.dumps(data), content_type='application/json')

    @staticmethod
    def _accion(request, accion, c):
        """Hace la acción y devuelve {'ok', 'mensaje'} (o {'error'})."""
        if accion == 'cancelar':
            if not correo.cancelar(c, request.user):
                return {'error': correo.NO_PENDIENTE}
            return {'ok': True, 'mensaje': 'Envío cancelado.'}
        if accion == 'enviar_ahora':
            correo.enviar_ahora(c, request.user)
            return {'ok': True, 'mensaje': f'Correo enviado a {c.para}.'}
        if accion == 'destinatarios':
            correo.corregir_destinatarios(c, request.POST.get('para', ''), request.POST.get('cc', ''), request.user)
            return {'ok': True, 'mensaje': 'Destinatarios corregidos.'}
        if accion == 'reprogramar':
            try:
                momento = datetime.strptime(request.POST.get('momento', ''), '%Y-%m-%dT%H:%M').replace(tzinfo=horario_habil.TZ_COLOMBIA)
            except ValueError:
                return {'error': 'Elija la fecha y la hora.'}
            c = correo.reprogramar(c, momento, request.user)
            ajustado = c.programado_para.astimezone(horario_habil.TZ_COLOMBIA).replace(second=0, microsecond=0) != momento
            texto = horario_habil.texto_fecha(c.programado_para)
            return {'ok': True, 'mensaje': _frase(f'Esa hora queda fuera del horario hábil: sale el {texto}' if ajustado
                                                  else f'Reprogramado: sale el {texto}')}
        if accion == 'reintentar':
            c = correo.reintentar(c, request.user)
            if c.estado == 'enviado':
                return {'ok': True, 'mensaje': f'Correo enviado a {c.para}.'}
            return {'ok': True, 'mensaje': _frase(f'Fuera del horario hábil: sale el {horario_habil.texto_fecha(c.programado_para)}')}
        return {'error': 'Acción desconocida.'}

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        user = self.request.user
        context['title'] = 'Seguimiento de correos'
        context['module_name'] = MODULE_NAME
        context['list_url'] = reverse_lazy('correo_seguimiento')
        context['filtros'] = FILTROS
        context['permisos'] = {accion: user.has_perm(permiso) for accion, permiso in ACCIONES.items()}
        # Enlace al comparativo del vehículo (desde ahí se arma y se reenvía el correo).
        context['url_comparativo'] = (reverse('vehiculo_comparativo', args=[0]) if user.has_perm('policies.view_comparativo') else '')
        context['horario'] = horario_habil.texto_horario()
        return context
