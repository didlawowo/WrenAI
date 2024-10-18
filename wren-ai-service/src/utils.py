import asyncio
import functools
import logging
import time
from pathlib import Path

from dotenv import load_dotenv
from langfuse.decorators import langfuse_context

logger = logging.getLogger("wren-ai-service")


class CustomFormatter(logging.Formatter):
    grey = "\x1b[38;20m"
    yellow = "\x1b[33;20m"
    red = "\x1b[31;20m"
    bold_red = "\x1b[31;1m"
    reset = "\x1b[0m"
    format = (
        "%(asctime)s - %(name)s - %(levelname)s - %(message)s (%(filename)s:%(lineno)d)"
    )

    FORMATS = {
        logging.DEBUG: yellow + format + reset,
        logging.INFO: grey + format + reset,
        logging.WARNING: yellow + format + reset,
        logging.ERROR: red + format + reset,
        logging.CRITICAL: bold_red + format + reset,
    }

    def format(self, record):
        log_fmt = self.FORMATS.get(record.levelno)
        formatter = logging.Formatter(log_fmt)
        return formatter.format(record)


def setup_custom_logger(name, level_str: str):
    level_str = level_str.upper()

    if level_str not in logging._nameToLevel:
        raise ValueError(f"Invalid logging level: {level_str}")

    level = logging._nameToLevel[level_str]

    handler = logging.StreamHandler()
    handler.setFormatter(CustomFormatter())

    logger = logging.getLogger(name)
    logger.setLevel(level)
    logger.addHandler(handler)
    return logger


def load_env_vars() -> str:
    # DEPRECATED: This method is deprecated and will be removed in the future
    if Path(".env.dev").exists():
        load_dotenv(".env.dev", override=True)
        return "dev"

    return "prod"


def timer(func):
    @functools.wraps(func)
    def wrapper_timer(*args, **kwargs):
        from src.config import settings

        if settings.enable_timer:
            startTime = time.perf_counter()
            result = func(*args, **kwargs)
            endTime = time.perf_counter()
            elapsed_time = endTime - startTime

            logger.info(
                f"{func.__qualname__} Elapsed time: {elapsed_time:0.4f} seconds"
            )

            return result

        return func(*args, **kwargs)

    return wrapper_timer


def async_timer(func):
    async def process(func, *args, **kwargs):
        assert asyncio.iscoroutinefunction(func)
        return await func(*args, **kwargs)

    @functools.wraps(func)
    async def wrapper_timer(*args, **kwargs):
        from src.config import settings

        if settings.enable_timer:
            startTime = time.perf_counter()
            result = await process(func, *args, **kwargs)
            endTime = time.perf_counter()
            elapsed_time = endTime - startTime

            logger.info(
                f"{func.__qualname__} Elapsed time: {elapsed_time:0.4f} seconds"
            )

            return result

        return await process(func, *args, **kwargs)

    return wrapper_timer


def remove_trailing_slash(endpoint: str) -> str:
    return endpoint.rstrip("/") if endpoint.endswith("/") else endpoint


def init_langfuse():
    from src.config import settings

    langfuse_context.configure(
        enabled=settings.langfuse_enable,
        public_key=settings.langfuse_public_key,
        secret_key=settings.langfuse_secret_key,
        host=settings.langfuse_host,
    )

    logger.info(f"LANGFUSE_ENABLE: {settings.langfuse_enable}")
    logger.info(f"LANGFUSE_HOST: {settings.langfuse_host}")


def trace_metadata(func):
    """
    This decorator is used to add metadata to the current Langfuse trace.
    It should be applied after creating a trace. Here’s an example of how to use it:

    ```python
    @observe(name="Mock")
    @trace_metadata
    async def mock():
        return "Mock"
    ```

    Args:
        func (Callable): the function to decorate

    Returns:
        Callable: the decorated function
    """

    def extract(*args) -> dict:
        request = args[1]  # fix the position of the request object
        metadata = {}

        if hasattr(request, "project_id"):
            metadata["project_id"] = request.project_id
        if hasattr(request, "thread_id"):
            metadata["thread_id"] = request.thread_id
        if hasattr(request, "mdl_hash"):
            metadata["mdl_hash"] = request.mdl_hash
        if hasattr(request, "user_id"):
            metadata["user_id"] = request.user_id

        return metadata

    @functools.wraps(func)
    async def wrapper(*args, **kwargs):
        results = await func(*args, **kwargs)

        addition = {}
        if isinstance(results, dict):
            additional_metadata = results.get("metadata", {})
            addition.update(additional_metadata)

        metadata = extract(*args)
        service_metadata = kwargs.get(
            "service_metadata",
            {
                "pipes_metadata": {},
                "service_version": "",
            },
        )
        langfuse_metadata = {
            **service_metadata.get("pipes_metadata"),
            **addition,
            "mdl_hash": metadata.get("mdl_hash"),
            "project_id": metadata.get("project_id"),
        }
        langfuse_context.update_current_trace(
            user_id=metadata.get("user_id"),
            session_id=metadata.get("thread_id"),
            release=service_metadata.get("service_version"),
            metadata=langfuse_metadata,
        )

        return results

    return wrapper


def remove_sql_summary_duplicates(dicts):
    """
    Removes duplicates from a list of dictionaries based on 'sql' and 'summary' fields.

    Args:
    dicts (list of dict): The list of dictionaries to be deduplicated.

    Returns:
    list of dict: A list of dictionaries after removing duplicates.
    """
    # Convert each dictionary to a tuple of (sql, summary) to make them hashable
    seen = set()
    unique_dicts = []
    for d in dicts:
        identifier = (
            d["sql"],
            d["summary"],
        )  # This assumes 'sql' and 'summary' always exist
        if identifier not in seen:
            seen.add(identifier)
            unique_dicts.append(d)
    return unique_dicts
