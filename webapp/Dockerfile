FROM python:3.10

WORKDIR /app

ARG TARGETARCH
ARG HEARTHLIGHT_IMAGE_VARIANT=cpu

USER root

RUN existing_user=$(getent passwd 1000 | cut -d: -f1) && \
    if [ -z "$existing_user" ]; then \
        groupadd -g 1000 appuser && \
        useradd -m -u 1000 -g appuser appuser; \
    else \
        echo "Using existing user: $existing_user"; \
    fi

RUN apt-get update && \
    apt-get upgrade -y && \
    apt-get install -y nodejs \
    npm \
    g++ \
    ffmpeg \
    netcat-openbsd \
    git \
    libsm6 \
    libxext6 \
    libxrender-dev \
    libglib2.0-0 \
    libxkbcommon-x11-0 \
    libxcb1 \
    libxcb-icccm4 \
    libxcb-image0 \
    libxcb-keysyms1 \
    libxcb-randr0 \
    libxcb-render-util0 \
    libxcb-shape0 \
    libxcb-shm0 \
    libxcb-sync1 \
    libxcb-util1 \
    libxcb-xfixes0 \
    libxcb-xinerama0 \
    libxcb-xkb1 && \
    rm -rf /var/lib/apt/lists/* && \
    chown $(id -un 1000):$(id -gn 1000) /app

COPY requirements.txt .

RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir -r requirements.txt && \
    if [ "$HEARTHLIGHT_IMAGE_VARIANT" = "cuda" ]; then \
        pip install --no-cache-dir \
            onnxruntime-gpu==1.22.0 \
            tensorrt==10.10.0.31 \
            torch==2.7.0 \
            triton==3.3.0; \
    elif [ "$TARGETARCH" = "arm64" ]; then \
        pip install --no-cache-dir \
            onnxruntime==1.22.0 \
            torch==2.7.0; \
    else \
        pip install --no-cache-dir \
            onnxruntime==1.22.0 \
            --index-url https://download.pytorch.org/whl/cpu \
            torch==2.7.0; \
    fi

USER 1000
