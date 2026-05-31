#!/bin/bash
set -eu

cookie_file="${HOME:-/var/lib/rabbitmq}/.erlang.cookie"

if [ ! -s "$cookie_file" ]; then
  (
    umask 177
    tr -dc 'A-Za-z0-9' </dev/urandom | head -c 32 >"$cookie_file"
  )
fi

rabbitmq-server &

until nc -z -v -w30 localhost 5672
do
  echo "Waiting for RabbitMQ server to start..."
  sleep 1
done

echo "RabbitMQ server started"

tail -f /dev/null
