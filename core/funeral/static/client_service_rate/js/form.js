$(function () {
    $('.select2').select2({
        language: 'es',
        theme: 'bootstrap4'
    });

    $('input[name="price"]')
        .TouchSpin({
            min: 0,
            max: 100000000,
            step: 0.01,
            decimals: 2,
            boostat: 5,
            maxboostedstep: 10,
            prefix: '$'
        })
        .on('keypress', function (e) {
            return validate_text_box({'event': e, 'type': 'decimals'});
        })
        .on('focus', function () {
            $(this).select();
        });
});
