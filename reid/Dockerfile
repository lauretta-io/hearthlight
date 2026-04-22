FROM anibali/pytorch:2.0.0-cuda11.8-ubuntu22.04
# Keep reid on the CUDA 11.8 base until ReID_Bench/faiss-gpu are validated on a newer lane.

WORKDIR /app

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
    apt-get install -y g++ \
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
    pip install --no-cache-dir setuptools==67.6.0 && \
    pip install --no-cache-dir --no-build-isolation infomap==2.8.0 && \
    pip install --no-cache-dir -r requirements.txt

USER 1000
