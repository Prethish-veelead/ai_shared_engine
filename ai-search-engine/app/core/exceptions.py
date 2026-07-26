"""Domain exceptions (framework-free — no FastAPI import here on purpose).
The HTTP handler that turns these into JSON lives in app/api/error_handlers.py.
"""


class AppError(Exception):
    """Base class for all expected application errors."""

    status_code = 500
    code = "internal_error"

    def __init__(self, message: str):
        self.message = message
        super().__init__(message)


class BotNotFoundError(AppError):
    status_code = 404
    code = "bot_not_found"


class ConfigError(AppError):
    status_code = 500
    code = "config_error"


class UpstreamError(AppError):
    """Azure OpenAI / SharePoint / Qdrant failed."""

    status_code = 502
    code = "upstream_error"
