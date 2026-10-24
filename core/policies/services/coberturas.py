"""Campos de la ficha comparativa de coberturas de una aseguradora (cuadro «COMPARATIVO»).

Todas las aseguradoras manejan los mismos campos, apliquen o no. Esta es la única definición de
secciones y etiquetas: la usan el modelo (verbose_name), el formulario, la vista previa y la carga inicial,
para que no se desincronicen. El orden es el del cuadro comparativo.
"""

# (título de la sección, [(nombre del campo del modelo, etiqueta), ...])
SECCIONES = (
    ('Responsabilidad civil extracontractual', (
        ('rc_limite_millones', 'Límite máximo (millones de pesos)'),
        ('rc_deducible', 'Deducible'),
    )),
    ('Coberturas del vehículo', (
        ('perdida_total_cubrimiento', 'Pérdida total por daños o hurto (cubrimiento)'),
        ('perdida_parcial_deducible', 'Pérdida parcial por daños y/o hurto (deducible)'),
        ('eventos_naturaleza', 'Eventos de la naturaleza'),
        ('amparo_patrimonial', 'Amparo patrimonial'),
    )),
    ('Asistencias', (
        ('grua', 'Grúa varada y accidente'),
        ('carro_taller', 'Carro taller (desvare por llanta, batería, gasolina o cerrajería)'),
        ('asistencia_juridica', 'Asistencia jurídica en proceso penal y civil'),
        ('gastos_transporte_perdida_total', 'Gastos de transporte en pérdida total'),
        ('gastos_transporte_perdida_parcial', 'Gastos de transporte en pérdida parcial'),
        ('vehiculo_reemplazo_perdida_total', 'Vehículo de reemplazo en pérdida total'),
        ('vehiculo_reemplazo_perdida_parcial', 'Vehículo de reemplazo en pérdida parcial'),
        ('conductor_elegido', 'Conductor elegido'),
        ('revision_antes_viaje', 'Revisión antes de viaje'),
        ('asistencia_hogar', 'Asistencia hogar'),
    )),
    ('Amparos adicionales', (
        ('ruptura_vidrios', 'Ruptura de vidrios'),
        ('accidentes_personales', 'Accidentes personales'),
        ('llantas_estalladas', 'Llantas estalladas'),
        ('perdida_llaves', 'Pérdida de llaves'),
        ('pequenos_accesorios', 'Pequeños accesorios'),
        ('farolas_stop_espejos', 'Farolas, stop, vidrios y espejos retrovisores (exclusiva por daños)'),
        ('amortiguadores_parachoques', 'Amortiguadores y parachoques'),
    )),
)

CAMPOS = tuple(campo for _, campos in SECCIONES for campo, _ in campos)
ETIQUETAS = {campo: etiqueta for _, campos in SECCIONES for campo, etiqueta in campos}
PRODUCTO_UNICO = 'General'


def secciones_de(ficha):
    """[(título, [(etiqueta, valor), ...]), ...] de una ficha, para mostrarla como vista previa."""
    resultado = []
    for titulo, campos in SECCIONES:
        filas = []
        for campo, etiqueta in campos:
            valor = getattr(ficha, campo)
            if campo == 'rc_limite_millones' and valor is not None:
                valor = f'${valor:,}'.replace(',', '.') + ' millones'
            filas.append((etiqueta, valor if valor not in (None, '') else ''))
        resultado.append((titulo, filas))
    return resultado
