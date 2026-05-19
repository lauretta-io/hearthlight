import os
import zipfile
import shutil
from pathlib import Path

"""
to add a model, add a key that can be used in the config to identify it, a link to download the model
from Google Drive, and the path where the model should be saved to.
"""

MODEL_REGISTRY = {
    "rtmo-s": {
        "url": "https://drive.google.com/file/d/1qj2lbe5Ml7ZPi6nlFAZmrCHwekGg0GKi/view?usp=sharing",
        "path": "src/shared/weights/rtmo-s.onnx",
    },
    "rtdetr-r50-08-02-2024": {
        "url": "https://drive.google.com/file/d/1kj3IrKxPrb5bTfOIogXen7KslNSxaDz7/view?usp=sharing",
        "path": "src/shared/weights/checkpoint0095.onnx",
    },
    "dfine-x-11-05-2024": {
        "url": "https://drive.google.com/file/d/1FqqvzXbakuCHiUAVjVclLX4hnvSEFVSk/view?usp=sharing",
        "path": "src/shared/weights/finetune_0.9997_0.4833.onnx",        
    },
    "transformer_120": {
        "url": "https://drive.google.com/file/d/1e9SqmuoolPXH4IAuXXteSFdRK0ywHAW0/view?usp=sharing",
        "path": "src/shared/weights/transformer_120.pth",
    },
    "yolov8_tray_650": {
        "url": "https://drive.google.com/file/d/1HliG8PvkmdRuyWJ_cn5YTvn5mw_44ROB/view?usp=sharing",
        "path": "src/shared/weights/yolo8_tray_650.pt",
    },
    "stgcnpp_8xb16-joint-u100-80e_ntu60-xsub-keypoint-2d": {
        "url": "https://drive.google.com/file/d/1Z54FxS54Y8ciY5ZuYXiI7KMOxDsp2v1f/view?usp=sharing",
        "path": "src/shared/weights/stgcnpp_8xb16-joint-u100-80e_ntu60-xsub-keypoint-2d_20221228-86e1e77a.pth",
    },
    "fashionformer_r101_3x": {
        "url": "https://drive.google.com/file/d/1jL2X1YRGrP8lWjhx9wgG4Vu33oj8wSRn/view?usp=sharing",
        "path": "src/shared/weights/fashionformer_r101_3x.pth",
    },
}


def get_model_weights(model_name):
    """
    get model weights from Google Drive or local storage using gdown
    """
    if model_name not in MODEL_REGISTRY:
        print(
            f"model {model_name} not found in registry. Checking if it refers to a local file"
        )
        if os.path.exists(model_name):
            print(f"path exists. loading model from {model_name}")
            return model_name
        raise ValueError(f"path {model_name} does not exist")

    path = Path(MODEL_REGISTRY[model_name]["path"])
    if path.exists():
        print(f"model {model_name} already exists at {path}")
        return str(path)

    print(f"specified path {path} does not exist. downloading model to {path}")

    try:
        import gdown
    except ModuleNotFoundError as exc:
        raise ModuleNotFoundError(
            "gdown is required to download model weights"
        ) from exc

    url = MODEL_REGISTRY[model_name]["url"]
    path.parent.mkdir(parents=True, exist_ok=True)
    temp_path = path.parent / f"temp_{model_name}{path.suffix}"
    try:
        # fuzzy=True to handle virus scan warning
        success = gdown.download(
            url=url, output=str(temp_path), fuzzy=True, quiet=False
        )

        if not success:
            raise Exception("download failed: gdown failed to download file")

        # Verify we got an actual file and not an HTML page
        if temp_path.stat().st_size < 1_000_000:  # Less than 1MB is probably HTML
            with open(temp_path, encoding="utf-8", errors="ignore") as f:
                content_preview = f.read(100)
                if "<html" in content_preview.lower():
                    raise Exception(
                        "download failed: likely received HTML page instead of weights file."
                    )

        if zipfile.is_zipfile(temp_path):
            expected_extension = path.suffix
            with zipfile.ZipFile(temp_path) as zf:
                weight_file = None
                for name in zf.namelist():
                    if name.endswith(expected_extension):
                        weight_file = name
                        break

                if weight_file is None:
                    raise ValueError(
                        f"download failed: could not find {expected_extension} file in zip"
                    )

                with zf.open(weight_file) as source, path.open("wb") as destination:
                    shutil.copyfileobj(source, destination)

                temp_path.unlink()
        else:
            shutil.move(temp_path, path)

    except Exception as e:
        if temp_path.exists():
            temp_path.unlink()
        raise Exception(f"Error downloading model: {str(e)}")

    return str(path)


if __name__ == "__main__":
    get_model_weights("transreid_120")
