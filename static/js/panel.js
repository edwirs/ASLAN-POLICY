/* Gráficas del panel de inicio. Los datos llegan en <script id="panelGraficas"> (ver core/policies/services/panel.py).
   Los colores de texto, ejes y tooltips los pone theme.js según el tema claro/oscuro. */
$(function () {
    var datos = JSON.parse(document.getElementById('panelGraficas').textContent);
    var VERDE = '#28a745', AMBAR = '#ffc107', ROJO = '#dc3545', AZUL = '#2ab1ee', NARANJA = '#f28b41';

    var cop = function (n) { return '$ ' + Number(n).toLocaleString('es-CO', {maximumFractionDigits: 0}); };
    $('.pn-dinero').each(function () { $(this).text(Number($(this).data('v')).toLocaleString('es-CO', {maximumFractionDigits: 0})); });

    function vacio(id, mensaje) {
        $('#' + id).html('<div class="pn-vacio"><i class="fas fa-chart-simple"></i><span>' + mensaje + '</span></div>');
    }

    function suma(arrs) {
        return arrs.reduce(function (t, a) { return t + a.reduce(function (x, y) { return x + y; }, 0); }, 0);
    }

    var base = {title: {text: null}, credits: {enabled: false}, exporting: {enabled: false}};
    Highcharts.setOptions({lang: {thousandsSep: '.', decimalPoint: ','}});

    // 1) Cotizaciones por día (apiladas por resultado)
    var d = datos.dias;
    if (!suma([d.ok, d.aviso, d.error])) {
        vacio('grDias', 'Sin cotizaciones en este período');
    } else {
        Highcharts.chart('grDias', $.extend(true, {}, base, {
            chart: {type: 'column', height: 300},
            xAxis: {categories: d.categorias, tickInterval: Math.ceil(d.categorias.length / 12), crosshair: true},
            yAxis: {min: 0, allowDecimals: false, title: {text: null}, stackLabels: {enabled: false}},
            legend: {align: 'center', verticalAlign: 'bottom'},
            tooltip: {shared: true},
            plotOptions: {column: {stacking: 'normal', borderWidth: 0, borderRadius: 2, pointPadding: .05, groupPadding: .05}},
            series: [
                {name: 'Completadas', data: d.ok, color: VERDE},
                {name: 'Avisos del portal', data: d.aviso, color: AMBAR},
                {name: 'Con error', data: d.error, color: ROJO}
            ]
        }));
    }

    // 2) Estado de las cotizaciones (rosca con el total al centro)
    var total = datos.estados.reduce(function (t, p) { return t + p.y; }, 0);
    if (!total) {
        vacio('grEstados', 'Sin cotizaciones en este período');
    } else {
        Highcharts.chart('grEstados', $.extend(true, {}, base, {
            chart: {type: 'pie', height: 300},
            title: {text: '<b style="font-size:26px">' + total + '</b><br>intentos', verticalAlign: 'middle', y: -12, useHTML: true},
            tooltip: {pointFormat: '<b>{point.y}</b> ({point.percentage:.0f}%)'},
            legend: {align: 'center', verticalAlign: 'bottom', itemStyle: {fontWeight: '500'}},
            plotOptions: {pie: {innerSize: '66%', borderWidth: 0, showInLegend: true, dataLabels: {enabled: false}, size: '88%', center: ['50%', '46%']}},
            series: [{name: 'Cotizaciones', data: datos.estados.filter(function (p) { return p.y > 0; })}]
        }));
    }

    // 3) Resultado por aseguradora (barras horizontales apiladas)
    var a = datos.aseguradoras;
    if (!a.categorias.length) {
        vacio('grAseguradoras', 'Sin cotizaciones en este período');
    } else {
        Highcharts.chart('grAseguradoras', $.extend(true, {}, base, {
            chart: {type: 'bar', height: Math.max(300, 60 + a.categorias.length * 42)},
            xAxis: {categories: a.categorias},
            yAxis: {min: 0, allowDecimals: false, title: {text: null}},
            legend: {align: 'center', verticalAlign: 'bottom'},
            tooltip: {shared: true},
            plotOptions: {series: {stacking: 'normal', borderWidth: 0, borderRadius: 2, pointPadding: .1, groupPadding: .08}},
            series: [
                {name: 'Completadas', data: a.ok, color: VERDE},
                {name: 'Avisos del portal', data: a.aviso, color: AMBAR},
                {name: 'Con error', data: a.error, color: ROJO}
            ]
        }));
    }

    // 4) Prima promedio por aseguradora (la más baja, en verde)
    var p = datos.primas;
    if (!p.categorias.length) {
        vacio('grPrimas', 'Aún no hay cotizaciones completadas');
    } else {
        Highcharts.chart('grPrimas', $.extend(true, {}, base, {
            chart: {type: 'bar', height: Math.max(300, 60 + p.categorias.length * 46)},
            xAxis: {categories: p.categorias},
            yAxis: {min: 0, maxPadding: .3, tickAmount: 5, title: {text: null}, labels: {rotation: 0, formatter: function () { return '$ ' + Highcharts.numberFormat(this.value / 1e6, 1) + ' M'; }}},
            legend: {enabled: false},
            tooltip: {pointFormatter: function () { return '<b>' + cop(this.y) + '</b>'; }},
            plotOptions: {bar: {borderWidth: 0, borderRadius: 3, pointPadding: .12, dataLabels: {enabled: true, crop: false, overflow: 'allow', style: {textOutline: 'none', fontWeight: '600'}, formatter: function () { return cop(this.y); }}}},
            series: [{name: 'Prima promedio', colorByPoint: false, color: AZUL,
                data: p.valores.map(function (v, i) { return {y: v, color: i === 0 ? VERDE : AZUL}; })}]
        }));
    }

    // 5) Evolución mensual
    var m = datos.meses;
    if (!suma([m.solicitudes, m.completadas])) {
        vacio('grMeses', 'Aún no hay actividad en los últimos meses');
    } else {
        Highcharts.chart('grMeses', $.extend(true, {}, base, {
            chart: {type: 'column', height: 300},
            xAxis: {categories: m.categorias, crosshair: true},
            yAxis: {min: 0, allowDecimals: false, title: {text: null}},
            legend: {align: 'center', verticalAlign: 'bottom'},
            tooltip: {shared: true},
            plotOptions: {column: {borderWidth: 0, borderRadius: 3, pointPadding: .08, groupPadding: .18}},
            series: [
                {name: 'Solicitudes', data: m.solicitudes, color: AZUL},
                {name: 'Cotizaciones completadas', data: m.completadas, color: NARANJA}
            ]
        }));
    }
});
