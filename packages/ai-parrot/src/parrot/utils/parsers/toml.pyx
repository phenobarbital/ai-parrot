# cython: language_level=3, embedsignature=True, boundscheck=False, wraparound=False, initializedcheck=False
# Copyright (C) 2018-present Jesus Lara
#
"""
Parsing a TOML file.
"""
import pytomlpp
import aiofiles


cdef class TOMLParser:
    async def parse(self, object filename):
        try:
            content = None
            async with aiofiles.open(filename) as f:
                content = await f.read()
            return pytomlpp.loads(content)
        except Exception as err:
            raise RuntimeError(
                f'Error parsing TOML content: {err!s}.'
            )
