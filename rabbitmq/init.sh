#!/bin/bash

rabbitmq-server &

until nc -z -v -w30 localhost 5672
do
  echo "Waiting for RabbitMQ server to start..."
  sleep 1
done

echo "RabbitMQ server started"

tail -f /dev/null