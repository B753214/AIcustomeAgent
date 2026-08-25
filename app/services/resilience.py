from typing import Callable, Any

from tenacity import retry, stop_after_attempt, wait_random_exponential

from app.config import settings


@retry(
    stop=stop_after_attempt(3),
    wait=wait_random_exponential(multiplier=0.5, max=settings.retry_max_wait),
    reraise=True
)
async def ainvoke_with_retry(fn: Callable, *args: Any, **kwargs: Any) -> Any:
    return await fn(*args, **kwargs)