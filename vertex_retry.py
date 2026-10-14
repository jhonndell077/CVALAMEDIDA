"""Bounded retries for temporary capacity, server and deadline errors."""
import logging
import random
import time
import httpx

REQUEST_TIMEOUT_MS = 75000
TOTAL_BUDGET_SECONDS = 180


def http_options():
    from google.genai import types
    # Avoid multiplying the SDK's retries by our own; stay within the HTTP function budget.
    return types.HttpOptions(timeout=REQUEST_TIMEOUT_MS, retry_options=types.HttpRetryOptions(attempts=1))


def thinking_config(model):
    from google.genai import types
    return types.ThinkingConfig(thinking_level="LOW") if model.startswith("gemini-3") else None


def generate_content(client, **kwargs):
    from google.genai.errors import APIError
    started = time.monotonic()
    for attempt in range(3):
        call_kwargs = dict(kwargs)
        config = call_kwargs.get("config")
        if config is not None:
            options = http_options()
            options.timeout = min(REQUEST_TIMEOUT_MS, max(1000, int((TOTAL_BUDGET_SECONDS - (time.monotonic() - started)) * 1000)))
            call_kwargs["config"] = config.model_copy(update={"http_options": options})
        try:
            response = client.models.generate_content(**call_kwargs)
            logging.getLogger(__name__).info("Vertex completed attempt=%s elapsed=%.1fs", attempt + 1, time.monotonic() - started)
            return response
        except (APIError, httpx.TimeoutException, TimeoutError) as error:
            code = getattr(error, "code", "timeout")
            if (isinstance(error, APIError) and code not in {429, 500, 503, 504}) or attempt == 2:
                raise
            delay = 2 ** (attempt + 1) + random.uniform(0, 1)
            if time.monotonic() - started + delay + 1 >= TOTAL_BUDGET_SECONDS:
                raise
            logging.getLogger(__name__).warning("Vertex temporary error %s; retry %s/2 in %.1fs", code, attempt + 1, delay)
            time.sleep(delay)
