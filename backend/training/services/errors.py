"""Service-layer exceptions; the API maps them to HTTP status codes, Streamlit shows them as messages."""


class ServiceError(Exception):
    """Base class for expected, user-facing service errors."""


class NotFoundError(ServiceError):
    """The requested entity does not exist (HTTP 404)."""


class InvalidInputError(ServiceError):
    """The request is well-formed but not acceptable (HTTP 422)."""
