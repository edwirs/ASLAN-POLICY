// Tema claro / oscuro: AdminLTE (body.dark-mode) + Bootstrap 5.3 (data-bs-theme).
// La elección se guarda en el navegador de cada usuario; por defecto es el tema claro.
(function () {
    var KEY = 'aslan-theme';

    function stored() {
        try { return localStorage.getItem(KEY); } catch (e) { return null; }
    }

    // ---- Gráficos Highcharts: fondo transparente y textos según el tema ----
    var LIGHT_COLORS = ['#7cb5ec', '#434348', '#90ed7d', '#f7a35c', '#8085e9', '#f15c80', '#e4d354', '#2b908f', '#f45b5b', '#91e8e1'];
    var DARK_COLORS = ['#7cb5ec', '#e8e8ee', '#90ed7d', '#f7a35c', '#8085e9', '#f15c80', '#e4d354', '#2b908f', '#f45b5b', '#91e8e1'];

    function chartOptions(dark) {
        var text = dark ? '#ced4da' : '#666666';
        var title = dark ? '#f8f9fa' : '#333333';
        var line = dark ? '#6c757d' : '#ccd6eb';
        return {
            colors: dark ? DARK_COLORS : LIGHT_COLORS,
            chart: {backgroundColor: 'transparent'},
            title: {style: {color: title}},
            subtitle: {style: {color: text}},
            xAxis: {labels: {style: {color: text}}, title: {style: {color: text}}, lineColor: line, tickColor: line},
            yAxis: {labels: {style: {color: text}}, title: {style: {color: text}}, gridLineColor: dark ? '#4b545c' : '#e6e6e6'},
            legend: {itemStyle: {color: text}, itemHoverStyle: {color: dark ? '#ffffff' : '#000000'},
                itemHiddenStyle: {color: dark ? '#6c757d' : '#cccccc'}},
            tooltip: {backgroundColor: dark ? 'rgba(33, 37, 41, 0.95)' : 'rgba(247, 247, 247, 0.85)',
                style: {color: dark ? '#f8f9fa' : '#333333'}},
            credits: {style: {color: dark ? '#8f98a1' : '#999999'}}
        };
    }

    var chartsWereDark = false;

    function styleCharts(dark) {
        if (!window.Highcharts) return;
        var options = chartOptions(dark);
        var previous = chartsWereDark ? DARK_COLORS : LIGHT_COLORS;
        Highcharts.setOptions(options);   // los gráficos que se dibujen después heredan estos colores
        (Highcharts.charts || []).forEach(function (chart) {
            if (!chart) return;
            // Las series que usan un color de la paleta cambian al color equivalente del tema nuevo
            chart.series.forEach(function (serie) {
                var i = serie.index % options.colors.length;
                if (serie.color === previous[i] && previous[i] !== options.colors[i]) {
                    serie.update({color: options.colors[i]}, false);
                }
                if (serie.options.colorByPoint || serie.type === 'pie') {
                    (serie.points || []).forEach(function (point, j) {
                        var k = j % options.colors.length;
                        if (point.color === previous[k] && previous[k] !== options.colors[k]) {
                            point.update({color: options.colors[k]}, false);
                        }
                    });
                }
            });
            var update = JSON.parse(JSON.stringify(options));
            delete update.colors;
            var xs = [], ys = [], i;
            for (i = 0; i < chart.xAxis.length; i++) xs.push(update.xAxis);
            for (i = 0; i < chart.yAxis.length; i++) ys.push(update.yAxis);
            update.xAxis = xs;
            update.yAxis = ys;
            chart.update(update, true, false, false);
        });
        chartsWereDark = dark;
    }

    function apply(theme, persist) {
        var dark = theme === 'dark';
        document.documentElement.setAttribute('data-bs-theme', dark ? 'dark' : 'light');
        document.body.classList.toggle('dark-mode', dark);

        var nav = document.querySelector('.main-header');
        if (nav) {
            nav.classList.toggle('navbar-dark', dark);
            nav.classList.toggle('navbar-light', !dark);
            nav.classList.toggle('navbar-white', !dark);
        }
        var toggle = document.getElementById('themeToggle');
        if (toggle) {
            toggle.querySelector('i').className = dark ? 'fas fa-sun' : 'fas fa-moon';
            toggle.setAttribute('title', dark ? 'Cambiar a tema claro' : 'Cambiar a tema oscuro');
        }
        styleCharts(dark);
        if (persist) {
            try { localStorage.setItem(KEY, theme); } catch (e) { /* navegación privada: se aplica sin recordar */ }
        }
        document.dispatchEvent(new CustomEvent('themechange', {detail: {theme: theme}}));
    }

    window.AslanTheme = {
        isDark: function () { return document.body.classList.contains('dark-mode'); },
        apply: apply
    };

    document.addEventListener('DOMContentLoaded', function () {
        apply(stored() === 'dark' ? 'dark' : 'light', false);
        var toggle = document.getElementById('themeToggle');
        if (toggle) {
            toggle.addEventListener('click', function (e) {
                e.preventDefault();
                apply(window.AslanTheme.isDark() ? 'light' : 'dark', true);
            });
        }
    });
})();
