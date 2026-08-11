"""Domain exceptions — mapped to HTTP status codes in the error handler."""


class ReviewAIError(Exception):
    """Base exception."""
    def __init__(self, message: str, code: str = "INTERNAL_ERROR"):
        self.message = message
        self.code = code
        super().__init__(message)


class NotFoundError(ReviewAIError):
    def __init__(self, resource: str, id: str):
        super().__init__(f"{resource} '{id}' not found.", code="NOT_FOUND")


class ValidationError(ReviewAIError):
    def __init__(self, message: str):
        super().__init__(message, code="VALIDATION_ERROR")


class ConflictError(ReviewAIError):
    def __init__(self, message: str):
        super().__init__(message, code="CONFLICT")


class IntegrationError(ReviewAIError):
    def __init__(self, service: str, message: str):
        super().__init__(f"{service}: {message}", code="INTEGRATION_ERROR")


class AgentError(ReviewAIError):
    def __init__(self, agent: str, message: str):
        super().__init__(f"Agent '{agent}' failed: {message}", code="AGENT_ERROR")


class PermissionError(ReviewAIError):
    def __init__(self, action: str):
        super().__init__(f"Not permitted: {action}", code="PERMISSION_DENIED")
