// Cargando de la plataforma: el lobo de ASLAN «respirando» con un anillo en los colores de la marca, en lugar del círculo
// por defecto de jquery-loading-overlay. Se carga justo después de la librería; cualquier $.LoadingOverlay('show') lo usa,
// y los textos ({text: 'Enviando…'}) salen debajo del lobo.
(function () {
    if (!window.jQuery || !$.LoadingOverlaySetup) {
        return;
    }
    var script = document.currentScript;
    var lobo = (script && script.dataset.lobo) || '/static/img/aslan_lobo_cargando.png';
    $.LoadingOverlaySetup({
        image: '',
        custom: '<div class="aslan-cargando" role="status" aria-label="Cargando">' +
                '<span class="aslan-cargando-anillo"></span>' +
                '<img class="aslan-cargando-lobo" src="' + lobo + '" alt=""></div>',
        customAutoResize: false,
        textAutoResize: false,
        textClass: 'aslan-cargando-texto',
        background: 'rgba(255, 255, 255, 0.82)',
        fade: [150, 120]
    });
})();
