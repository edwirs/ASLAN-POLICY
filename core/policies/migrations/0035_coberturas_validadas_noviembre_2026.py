"""Fichas de coberturas validadas con las cotizaciones en PDF de los portales (noviembre de 2026).

- Qualitas: cotización 0008777484-00 (06/11/2026, clausulado 01/09/2026-1352-P-03-AUTOLIVIANOPER05) y la de KWU676.
- HDI: cotizaciones 115873466 y 115873469 (04/11/2026, plan Liviano Premium, condiciones julio 2026).
- Seguros Mundial (nueva): cotización del 04/11/2026 (clausulado 07/03/2025-1317-P-03-PPSUS10R00000058) y su
  anexo de asistencia 07/03/2025-1317-A-03-ASSUS10R00000060 publicado en segurosmundial.com.co.
- Mapfre: no se había cargado porque no estaba registrada; se carga con los datos del comparativo (sin validar).

Solo se cambia un campo si todavía tiene el valor de la carga inicial: lo que alguien ya corrigió a mano no se toca.
"""
from django.db import migrations

# (aseguradora, producto) -> {campo: (valor de la carga inicial, valor validado)}
CAMBIOS = {
    ('Qualitas', 'General'): {
        'gastos_transporte_perdida_parcial': ('No ampara', '$ 75.000 por día, hasta 15 días'),
        'vehiculo_reemplazo_perdida_total': ('$ 1.500.000', '20 días'),
        'vehiculo_reemplazo_perdida_parcial': ('No ampara', '15 días'),
        'llantas_estalladas': ('Sí ampara deducible 5 %', 'Sí ampara deducible 15 %'),
        'ruptura_vidrios': ('Sí ampara deducible 5 %', 'Hasta el 5 % del valor asegurado, deducible 5 %'),
    },
    ('HDI', 'General'): {
        'asistencia_juridica': ('Penal $13,385,074 Civil $ 6,770,660', 'Penal $ 24.389.300 / Civil $ 12.337.000'),
        'llantas_estalladas': ('Hasta 1,5 SMDLV', 'Hasta 1,5 SMMLV'),
    },
}
NOTA = {
    ('Qualitas', 'General'): 'Validado el 06/11/2026 con la cotización en PDF del portal (clausulado 01/09/2026).',
    ('HDI', 'General'): 'Validado el 04/11/2026 con la cotización en PDF del portal (plan Liviano Premium, condiciones julio 2026).',
}

NO_INCLUIDA = 'No incluida en la cotización'
NUEVAS = {
    ('Seguros Mundial', 'General'): {
        'observaciones': ('Tomado de la cotización en PDF del portal (04/11/2026, «Coberturas básicas», clausulado '
                          '07/03/2025). La cotización no trae asistencia en viaje: el anexo 07/03/2025 ofrece plan Esencial '
                          'o Plus como opción.'),
        'rc_limite_millones': 4000,
        'rc_deducible': 'Sin deducible',
        'perdida_total_cubrimiento': '100%',
        'perdida_parcial_deducible': '10 % mínimo 1 SMMLV',
        'eventos_naturaleza': 'Sí ampara deducible 10 % mínimo 1 SMMLV',
        'amparo_patrimonial': 'Sí ampara',
        'grua': NO_INCLUIDA,
        'carro_taller': NO_INCLUIDA,
        'asistencia_juridica': 'Sí ampara (proceso penal y civil)',
        'gastos_transporte_perdida_total': 'No ampara',
        'gastos_transporte_perdida_parcial': 'No ampara',
        'vehiculo_reemplazo_perdida_total': 'No ampara',
        'vehiculo_reemplazo_perdida_parcial': 'No ampara',
        'conductor_elegido': NO_INCLUIDA,
        'revision_antes_viaje': 'No ampara',
        'asistencia_hogar': 'No ampara',
        'ruptura_vidrios': 'No ampara',
        'accidentes_personales': '$ 40.000.000 (muerte accidental del conductor)',
        'llantas_estalladas': 'No ampara',
        'perdida_llaves': 'No ampara',
        'pequenos_accesorios': 'No ampara',
        'farolas_stop_espejos': 'No ampara',
        'amortiguadores_parachoques': 'No ampara',
    },
    ('Mapfre', 'General'): {
        'observaciones': 'Cargado del comparativo COMPARATIVO.docx (octubre 2026). Sin validar con una cotización del portal.',
        'rc_limite_millones': 4000,
        'rc_deducible': 'Sin deducible',
        'perdida_total_cubrimiento': '100%',
        'perdida_parcial_deducible': '$ 1.200.000',
        'eventos_naturaleza': 'Sí ampara deducible $ 1.200.000',
        'amparo_patrimonial': 'Sí ampara',
        'grua': 'Cliente Plata 50 SMDLV Cliente Oro 75 SMDLV Cliente Platino Ilimitado',
        'carro_taller': 'Cobertura Batería, Alarma, Cambio bujías, Pinchada Y Gasolina.',
        'asistencia_juridica': 'Sí ampara',
        'gastos_transporte_perdida_total': 'Hasta 1,5 SMDLV por 30 días',
        'gastos_transporte_perdida_parcial': 'No ampara',
        'vehiculo_reemplazo_perdida_total': 'Hasta 15 días',
        'vehiculo_reemplazo_perdida_parcial': '10 días',
        'conductor_elegido': '10 servicios por vigencia',
        'revision_antes_viaje': 'No ampara',
        'asistencia_hogar': 'No ampara',
        'ruptura_vidrios': 'No ampara',
        'accidentes_personales': 'No ampara',
        'llantas_estalladas': 'No ampara',
        'perdida_llaves': 'Sí ampara',
        'pequenos_accesorios': 'Sí ampara',
        'farolas_stop_espejos': 'No ampara',
        'amortiguadores_parachoques': 'No ampara',
    },
}


def aplicar(apps, schema_editor):
    Aseguradora = apps.get_model('policies', 'Aseguradora')
    Ficha = apps.get_model('policies', 'CoberturaAseguradora')
    for (nombre, producto), campos in CAMBIOS.items():
        ficha = Ficha.objects.filter(aseguradora__name=nombre, producto=producto).first()
        if ficha is None:
            continue
        cambiados = []
        for campo, (anterior, nuevo) in campos.items():
            if (getattr(ficha, campo) or '').strip() == anterior:
                setattr(ficha, campo, nuevo)
                cambiados.append(campo)
        if cambiados:
            ficha.observaciones = NOTA[(nombre, producto)]
            ficha.save()
    for (nombre, producto), datos in NUEVAS.items():
        aseguradora = Aseguradora.objects.filter(name=nombre).first()
        if aseguradora and not Ficha.objects.filter(aseguradora=aseguradora, producto=producto).exists():
            Ficha.objects.create(aseguradora=aseguradora, producto=producto, **datos)


class Migration(migrations.Migration):
    dependencies = [('policies', '0034_valorexterno_valor_2')]
    operations = [migrations.RunPython(aplicar, migrations.RunPython.noop)]
