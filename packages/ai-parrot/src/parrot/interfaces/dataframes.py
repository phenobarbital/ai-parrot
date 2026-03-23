class PandasDataframe:
    """
    Mock interface for Pandas Dataframe compatibility.
    """
    def __init__(self, *args, **kwargs):
        pass

    def to_dataframe(self, data):
        """Mock method."""
        return data
