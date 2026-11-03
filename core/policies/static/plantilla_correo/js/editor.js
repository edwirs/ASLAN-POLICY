function ajustarMarco(marco) {
    // El alto del marco sigue al correo (también cuando terminan de cargar las imágenes o se abre la ventana).
    function medir() {
        try { marco.style.height = Math.max(420, marco.contentDocument.documentElement.scrollHeight + 10) + 'px'; } catch (e) { /* sin acceso */ }
    }
    medir();
    try { [].forEach.call(marco.contentDocument.images, function (img) { img.addEventListener('load', medir); }); } catch (e) { /* sin acceso */ }
    setTimeout(medir, 350);
}
// Editor de una plantilla de correo: barra de formato, botones para insertar datos y bloques, y vista previa en vivo
// (el servidor arma el correo con un vehículo de ejemplo, igual que cuando se envía).
$(function () {
    var $form = $('#frmPlantilla');
    var editable = $form.data('editable') === 1;
    var editor = document.getElementById('pcEditor');
    var $cuerpo = $('#id_cuerpo');
    var CAMPOS = ['nombre', 'tipo_seguro', 'cuenta', 'para', 'cc', 'asunto', 'promocion_texto', 'promocion_aseguradora', 'vigencia_cotizacion_dias'];

    editor.innerHTML = JSON.parse(document.getElementById('pcCuerpoInicial').textContent) || '<p><br></p>';
    try { document.execCommand('defaultParagraphSeparator', false, 'p'); } catch (e) { /* navegadores viejos */ }

    // Guarda la posición del cursor: al pulsar un botón el editor pierde el foco.
    var rango = null;
    function guardarRango() {
        var sel = window.getSelection();
        if (sel.rangeCount && editor.contains(sel.anchorNode)) { rango = sel.getRangeAt(0).cloneRange(); }
    }
    function restaurarRango() {
        editor.focus();
        if (!rango) { return; }
        var sel = window.getSelection();
        sel.removeAllRanges();
        sel.addRange(rango);
    }
    $(editor).on('keyup mouseup input blur', guardarRango);

    $('.pc-barra [data-cmd]').on('mousedown', function (e) { e.preventDefault(); }).on('click', function () {
        var cmd = $(this).data('cmd'), valor = null;
        if (cmd === 'createLink') {
            valor = prompt('Dirección del enlace (https://…)', 'https://');
            if (!valor || valor === 'https://') { return; }
        }
        restaurarRango();
        document.execCommand(cmd, false, valor);
        cambio();
    });
    $('#pcColor').on('change', function () {
        restaurarRango();
        document.execCommand('styleWithCSS', false, true);
        document.execCommand('foreColor', false, this.value);
        cambio();
    });
    $('.pc-var').on('mousedown', function (e) { e.preventDefault(); }).on('click', function () {
        restaurarRango();
        document.execCommand('insertText', false, '{' + $(this).data('variable') + '}');
        cambio();
    });
    $('.pc-bloque-btn').on('mousedown', function (e) { e.preventDefault(); }).on('click', function () {
        restaurarRango();
        document.execCommand('insertHTML', false, '<p>{' + $(this).data('bloque') + '}</p><p><br></p>');
        cambio();
    });
    // Al pegar desde Word o una página web solo se conserva el texto.
    $(editor).on('paste', function (e) {
        e.preventDefault();
        var texto = (e.originalEvent.clipboardData || window.clipboardData).getData('text/plain');
        document.execCommand('insertText', false, texto);
    });

    // ---- Vista previa ----
    var temporizador = null, peticion = null;
    function datos(accion) {
        var fd = new FormData();
        fd.append('action', accion);
        CAMPOS.forEach(function (c) { fd.append(c, $('#id_' + c).val() || ''); });  // también los deshabilitados (solo lectura)
        ['adjuntar_pdf', 'predeterminada', 'is_active'].forEach(function (c) { if ($('#id_' + c).is(':checked')) { fd.append(c, 'on'); } });
        fd.append('cuerpo', editor.innerHTML);
        return fd;
    }
    function esc(t) { return $('<div>').text(t == null ? '' : t).html(); }
    function previa() {
        if (peticion) { peticion.abort(); }
        var fd = datos('vista_previa');
        fd.append('placa', $('#pcPlaca').val());
        peticion = $.ajax({url: window.location.pathname, type: 'POST', headers: {'X-CSRFToken': csrftoken}, data: fd,
            processData: false, contentType: false, dataType: 'json'})
            .done(function (r) {
                if (r.error) { $('#pvAvisos').html('<div class="pc-aviso">' + esc(r.error) + '</div>'); return; }
                $('#pcPlaca').val(r.placa);
                $('#pvDe').text(r.de || 'Sin cuenta');
                $('#pvPara').text((r.para || []).join(', ') || '—');
                $('#pvCc').text((r.cc || []).join(', ') || '—');
                $('#pvAsunto').text(r.asunto || '—');
                $('#pvAdjunto').text(r.adjunto);
                $('#pvAdjuntoFila').toggle(!!r.adjunto);
                $('#pvAvisos').html((r.avisos || []).map(function (a) { return '<div class="pc-aviso"><i class="fa-solid fa-triangle-exclamation"></i> ' + esc(a) + '</div>'; }).join(''));
                document.getElementById('pvMarco').srcdoc = r.html;
            });
    }
    function cambio() {
        clearTimeout(temporizador);
        temporizador = setTimeout(previa, 600);
    }
    $(editor).on('input', cambio);
    $form.on('input change', 'input, select', function () { if (this.id !== 'pcPlaca') { cambio(); } });
    $('#pcActualizar').on('click', previa);
    $('#pcPlaca').on('keydown', function (e) { if (e.key === 'Enter') { e.preventDefault(); previa(); } });
    // El alto del marco se ajusta al correo para no tener doble barra de desplazamiento.
    $('#pvMarco').on('load', function () { ajustarMarco(this); });
    previa();

    // ---- Guardar ----
    $form.on('submit', function (e) {
        e.preventDefault();
        if (!editable) { return; }
        $cuerpo.val(editor.innerHTML);
        var fd = new FormData(this);
        fd.set('action', 'guardar');
        fd.set('cuerpo', editor.innerHTML);
        $.LoadingOverlay('show');
        $.ajax({url: window.location.pathname, type: 'POST', headers: {'X-CSRFToken': csrftoken}, data: fd,
            processData: false, contentType: false, dataType: 'json'})
            .done(function (r) {
                if (r.error) {
                    var texto = typeof r.error === 'object'
                        ? Object.keys(r.error).map(function (c) { var etiqueta = $('label[for="id_' + c + '"]').first().text().replace('*', '').trim() || c; return etiqueta + ': ' + r.error[c].join(' '); }).join('\n')
                        : r.error;
                    message_error(texto);
                    return;
                }
                Swal.fire({icon: 'success', title: 'Plantilla guardada', timer: 1200, showConfirmButton: false}).then(function () { window.location.href = r.url; });
            })
            .fail(function (xhr) { message_error((xhr.responseJSON && xhr.responseJSON.error) || 'No se pudo guardar.'); })
            .always(function () { $.LoadingOverlay('hide'); });
    });
});
