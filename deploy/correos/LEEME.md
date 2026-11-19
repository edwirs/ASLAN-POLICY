# Cola de correos de cotización

El botón «Enviar correo» del comparativo deja el correo en la cola tal como el asesor lo revisó:

- **Dentro del horario hábil** sale en el acto. El horario es de lunes a viernes de 8:00 a. m. a 5:00 p. m. y los sábados de 8:00 a. m. a 12:00 m., hora de Colombia, sin festivos.
- **Fuera del horario** queda «Programado» para la siguiente hora hábil. Lo envía el comando `enviar_correos_programados`, que el timer de systemd corre cada minuto.
- **Envíos de a pocos:** cada corrida envía como máximo 10 correos por empresa, para no saturar el servidor de correo a las 8:00 a. m.
- **Fallas pasajeras** del servidor de correo (sin conexión, tiempo agotado): se reintenta hasta 3 veces, con 5 minutos entre intentos.
- **Fallas definitivas** (contraseña o destinatario rechazado): el correo queda en «No se pudo enviar» y la falla queda anotada en el historial del vehículo.
- Los festivos de Colombia se calculan solos en `core/policies/services/horario_habil.py`, incluidos los de la Ley Emiliani y los de Semana Santa.

## Instalar el timer en el VPS (una sola vez)

```bash
sudo cp ~/aslan-multiagente/ASLAN-POLICY/deploy/correos/aslan-correos.service ~/aslan-multiagente/ASLAN-POLICY/deploy/correos/aslan-correos.timer /etc/systemd/system/
```

```bash
sudo systemctl daemon-reload && sudo systemctl enable --now aslan-correos.timer
```

## Revisar que está corriendo

```bash
systemctl list-timers aslan-correos.timer
```

```bash
journalctl -u aslan-correos.service --since today
```
