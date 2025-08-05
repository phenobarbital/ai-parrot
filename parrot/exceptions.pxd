# cython: language_level=3, embedsignature=True, boundscheck=False, wraparound=True, initializedcheck=False
# Copyright (C) 2018-present Jesus Lara
#
cdef class ParrotError(Exception):
    """Base class for other exceptions"""
    pass

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
