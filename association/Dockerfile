FROM python:3.10

WORKDIR /app

RUN existing_user=$(getent passwd 1000 | cut -d: -f1) && \
    if [ -z "$existing_user" ]; then \
        groupadd -g 1000 appuser && \
        useradd -m -u 1000 -g appuser appuser; \
    else \
        echo "Using existing user: $existing_user"; \
    fi

RUN apt-get update && \
    apt-get upgrade -y && \
    apt-get install -y ffmpeg \
    libsm6 \
    libxext6 \
    netcat-openbsd && \
    rm -rf /var/lib/apt/lists/* && \
    chown $(id -un 1000):$(id -gn 1000) /app

COPY requirements.txt .

RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir -r requirements.txt

USER 1000
