class EmptyStore:
    """
    Empty Store reference, used on bots without Vector Store Support.
    """

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc_value, traceback):
        pass
