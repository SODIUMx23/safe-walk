#!/bin/sh
set -eu
umask 077
mosquitto_passwd -b -c /mosquitto/config/passwords safewalk "$(cat /run/secrets/mqtt_password)"
printf 'user safewalk\ntopic readwrite safewalk/#\n' > /mosquitto/config/acl
chown mosquitto:mosquitto /mosquitto/config/passwords /mosquitto/config/acl /mosquitto/data /mosquitto/log
chmod 0600 /mosquitto/config/passwords /mosquitto/config/acl
exec /usr/sbin/mosquitto -c /mosquitto/config/mosquitto.conf
