import time
import functools
from typing import Type, Union, Callable, TypeVar, Any
import logging

logger = logging.getLogger(__name__)
T = TypeVar("T")


def with_exponential_backoff(
    max_tries: int = 5,
    exceptions: Union[Type[Exception], tuple[Type[Exception], ...]] = Exception,
    base_delay: float = 1.0,
    max_delay: float = 60.0,
):
    """
    Decorator that implements exponential backoff for retrying functions.

    Args:
        max_tries (int): Maximum number of attempts before giving up
        exceptions (Exception or tuple): Exception(s) to catch and retry on
        base_delay (float): Initial delay in seconds
        max_delay (float): Maximum delay between retries in seconds

    Usage:
        @with_exponential_backoff(max_tries=3)
        def my_function():
            # potentially failing code here
    """

    def decorator(func: Callable[..., T]) -> Callable[..., T]:
        @functools.wraps(func)
        def wrapper(*args: Any, **kwargs: Any) -> T:
            num_tries = 0
            while num_tries < max_tries:
                try:
                    return func(*args, **kwargs)
                except exceptions:
                    num_tries += 1
                    if num_tries == max_tries:
                        logger.exception(f"function {func.__name__} failed {max_tries} times.")
                        raise
                    delay = min(base_delay * (2 ** (num_tries - 1)), max_delay)
                    logger.warning(
                        f"function {func.__name__} failed on attempt {num_tries}/{max_tries}, "
                        f"retrying in {delay} seconds..."
                    )
                    time.sleep(delay)
            raise RuntimeError("Unexpected end of retry loop")

        return wrapper

    return decorator
