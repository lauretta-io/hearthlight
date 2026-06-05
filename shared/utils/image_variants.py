from __future__ import annotations

from typing import Iterable

from .local_worker_runtime import (
    WORKER_RUNTIME_DOCKER,
    WORKER_RUNTIME_HYBRID_LOCAL_MLX,
)

IMAGE_VARIANT_CPU = "cpu"
IMAGE_VARIANT_CUDA = "cuda"
IMAGE_VARIANT_MLX = "mlx"
IMAGE_VARIANTS = (IMAGE_VARIANT_CPU, IMAGE_VARIANT_CUDA, IMAGE_VARIANT_MLX)

LOCAL_BUILDABLE_SERVICES = ("rabbitmq", "webapp", "ingestor", "association", "anomaly")
CORE_IMAGE_SERVICES = ("rabbitmq", "webapp")
PIPELINE_IMAGE_SERVICES = ("ingestor", "association", "anomaly")


def resolve_image_variant(*, use_cuda: bool, worker_runtime: str) -> str:
    if use_cuda:
        return IMAGE_VARIANT_CUDA
    if worker_runtime == WORKER_RUNTIME_HYBRID_LOCAL_MLX:
        return IMAGE_VARIANT_MLX
    return IMAGE_VARIANT_CPU


def default_image_services_for_variant(variant: str) -> list[str]:
    if variant == IMAGE_VARIANT_MLX:
        return list(CORE_IMAGE_SERVICES)
    return list(LOCAL_BUILDABLE_SERVICES)


def build_local_image_name(service: str, variant: str) -> str:
    return f"hearthlight-{service}:{variant}"


def build_published_image_name(namespace: str, service: str, tag: str, variant: str) -> str:
    return f"{namespace}/hearthlight-{service}:{tag}-{variant}"


def normalize_selected_services(services: Iterable[str] | None, *, variant: str) -> list[str]:
    allowed = set(default_image_services_for_variant(variant))
    selected = list(services or [])
    if not selected:
        return sorted(allowed)
    return [service for service in selected if service in allowed]
