from collections import defaultdict
from contextlib import contextmanager
import logging
import time

try:
    import torch

    if not torch.cuda.is_available():
        raise ImportError

    def time_synchronized():
        torch.cuda.synchronize()
        return time.time()

except ImportError:

    def time_synchronized():
        return time.time()


class LoopTimer:
    def __init__(self, logger=None, log_interval=None, task=None, abbrev=None):
        self.timings = defaultdict(float)
        self.total_count = 0
        self.count = 0
        self.separate_counts = defaultdict(int)
        self.last_time = 0
        self.start_time = 0
        self.last_report = 0
        self.log_interval = log_interval
        self.logger = logger or logging.getLogger(__name__)
        self.task = task
        self.abbrev = abbrev if abbrev else ""

    def start(self):
        self.start_time = time_synchronized()
        self.last_report = self.start_time
        self.last_time = self.start_time

    def mark(self):
        self.last_time = time_synchronized()

    def time(self, name, separate_count=False):
        elapsed = time_synchronized() - self.last_time
        self.timings[name] += elapsed
        self.mark()
        if separate_count:
            self.separate_counts[name] += 1
        return elapsed

    def loop(self):
        self.count += 1
        self.total_count += 1
        self.mark()
        if self.log_interval and (self.last_time - self.last_report) > self.log_interval:
            self.report()
            self.last_report = self.last_time

    @contextmanager
    def timing(self, name):
        self.mark()
        yield
        self.time(name)

    def report(self, reset=True):
        if not self.timings:
            return
        report_strs = [f"{self.abbrev} Frame ID: {self.total_count}"]
        report_strs.append(f"FPS: {self.count / (self.last_time - self.start_time):.1f}")
        for name, total_time in self.timings.items():
            count = self.separate_counts[name] if name in self.separate_counts else self.count
            avg_time = total_time / count if count > 0 else 0
            report_strs.append(f"{name}: {avg_time*1000:.0f}ms")
        report_str = " | ".join(report_strs)
        self.logger.debug(report_str, extra={"task": self.task})
        if reset:
            self.split()

    def split(self):
        self.timings.clear()
        self.separate_counts.clear()
        self.count = 0
        self.start()

    def reset(self):
        self.split()
        self.total_count = 0
