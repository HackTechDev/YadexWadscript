"""Error types shared across the wadscript pipeline.

Every error carries the source line it originates from so the CLI can
report `file:line: error: message` and never has to guess.
"""


class WsError(Exception):
    """Base class. `line` is 1-indexed, or None if not tied to a specific line."""

    def __init__(self, message, line=None):
        super().__init__(message)
        self.message = message
        self.line = line

    def format(self, filename):
        if self.line is not None:
            return f"{filename}:{self.line}: error: {self.message}"
        return f"{filename}: error: {self.message}"


class WsParseError(WsError):
    pass


class WsValidationError(WsError):
    pass
