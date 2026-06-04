FROM anibali/pytorch:2.0.0-cuda11.8-ubuntu22.04

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

RUN apt-get update && apt-get install -y wget gnupg && \
    wget https://developer.download.nvidia.com/compute/cuda/repos/ubuntu2204/x86_64/cuda-ubuntu2204.pin && \
    mv cuda-ubuntu2204.pin /etc/apt/preferences.d/cuda-repository-pin-600 && \
    wget https://developer.download.nvidia.com/compute/cuda/11.8.0/local_installers/cuda-repo-ubuntu2204-11-8-local_11.8.0-520.61.05-1_amd64.deb && \
    dpkg -i cuda-repo-ubuntu2204-11-8-local_11.8.0-520.61.05-1_amd64.deb && \
    cp /var/cuda-repo-ubuntu2204-11-8-local/cuda-*-keyring.gpg /usr/share/keyrings/ && \
    apt-get update && apt-get install -y cuda-toolkit-11-8 && \
    rm -rf /var/lib/apt/lists/*

ENV CUDA_HOME=/usr/local/cuda
ENV PATH=${CUDA_HOME}/bin:${PATH}
ENV LD_LIBRARY_PATH=${CUDA_HOME}/lib64:${LD_LIBRARY_PATH}

COPY requirements.txt .

RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir -r requirements.txt

USER 1000
