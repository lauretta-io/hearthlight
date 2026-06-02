FROM rabbitmq:3-management

RUN apt-get update && \
    apt-get upgrade -y && \
    apt-get install -y netcat-openbsd && \
    rm -rf /var/lib/apt/lists/*

COPY init.sh /usr/local/bin/

RUN sed -i 's/\r$//' /usr/local/bin/init.sh && chmod +x /usr/local/bin/init.sh

USER rabbitmq
