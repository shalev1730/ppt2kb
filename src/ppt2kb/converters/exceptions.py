# Adapted from ppt2desc (MIT, (c) 2025 Adam Łucek) - src/converters/exceptions.py


class LibreOfficeNotFoundError(Exception):
    """Raised when LibreOffice is not found at the given path."""


class ConversionError(Exception):
    """General error for file conversion issues."""
