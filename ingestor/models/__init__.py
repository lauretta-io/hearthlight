import sys
import tensorrt_bindings

for attr in dir(tensorrt_bindings):
    if not attr.startswith('__'):
        globals()[attr] = getattr(tensorrt_bindings, attr)

sys.modules['tensorrt.tensorrt'] = tensorrt_bindings

__version__ = tensorrt_bindings.__version__

from .detector import Detector
from .tracker import Tracker
from .feature_extractor import FeatureExtractor
from .pose import PoseDetector
from .anomaly import AnomalyDescriber
