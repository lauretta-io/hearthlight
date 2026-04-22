import base64
import binascii

import cv2
import numpy as np


def decode_base64(b64_image, max_bytes=10 * 1024 * 1024):
    try:
        image_bytes = base64.b64decode(b64_image, validate=True)
    except (binascii.Error, ValueError) as exc:
        raise ValueError("invalid base64 image payload") from exc
    if len(image_bytes) > max_bytes:
        raise ValueError("image payload exceeds size limit")
    image_array = np.frombuffer(image_bytes, dtype=np.uint8)
    image = cv2.imdecode(image_array, cv2.IMREAD_COLOR)
    if image is None:
        raise ValueError("decoded payload is not a valid image")
    return image


def encode_base64(crop):
    success, buffer = cv2.imencode(".png", crop)
    if not success:
        return None
    base64_string = base64.b64encode(buffer).decode("utf-8")
    return base64_string
