"""Typed exception hierarchy for exchange operations.

Enables callers to distinguish transient vs permanent failures
and apply appropriate retry strategies.
"""


class ExchangeError(Exception):
    """Base class for all exchange-related errors."""


class TransientExchangeError(ExchangeError):
    """Temporary failure that may succeed on retry (network, 503, timeout)."""


class RateLimitError(TransientExchangeError):
    """Exchange rate limit hit (429). Caller should backoff and retry."""
    def __init__(self, message: str = "Rate limit exceeded", retry_after: float = 0.0):
        super().__init__(message)
        self.retry_after = retry_after


class PermanentExchangeError(ExchangeError):
    """Non-recoverable failure (invalid pair, auth, insufficient balance)."""


class AuthenticationError(PermanentExchangeError):
    """API key/secret/nonce authentication failure."""


class InsufficientFundsError(PermanentExchangeError):
    """Insufficient balance for the requested order."""


class InvalidOrderError(PermanentExchangeError):
    """Invalid order parameters (bad pair, size below minimum, etc)."""
