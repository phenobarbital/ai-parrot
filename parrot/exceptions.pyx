# cython: language_level=3, embedsignature=True, boundscheck=False, wraparound=True, initializedcheck=False
# Copyright (C) 2018-present Jesus Lara
#
cdef class ParrotError(Exception):
    """Base class for other exceptions"""

    def __init__(self, object message, *args, **kwargs):
        super().__init__(message)
        if hasattr(message, 'message'):
            self.message = message.message
        else:
            self.message = str(message)
        self.stacktrace = None
        if 'stacktrace' in kwargs:
            self.stacktrace = kwargs['stacktrace']
        self.args = kwargs

    def __repr__(self):
        return f"{self.message}"

    def __str__(self):
        return f"{self.message}"

    def get(self):
        """Return the message of the exception."""
        return self.message


cdef class ConfigError(ParrotError):
    pass


cdef class SpeechGenerationError(ParrotError):
    """Capture Errors related to speech generation."""
    pass


cdef class DriverError(ParrotError):
    """Capture Errors related to driver operations."""
    pass

cdef class ToolError(ParrotError):
    """Capture Errors related to tool operations."""
    pass
