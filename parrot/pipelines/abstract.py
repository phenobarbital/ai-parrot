from abc import ABC, abstractmethod
from typing import Any, Dict, Optional
from pydantic import BaseModel, Field
from navconfig.logging import logging
from datamodel.parsers.json import JSONContent  # pylint: disable=E0611
from ..clients import SUPPORTED_CLIENTS


class AbstractPipeline(ABC):
    """Abstract base class for all pipelines."""
    def __init__(
        self,
        llm: Any = None,
        llm_provider: str = "claude",
        llm_model: Optional[str] = None,
        **kwargs: Any
    ):
        """
        Initialize the 3-step pipeline

        Args:
            llm_provider: LLM provider for identification
            llm_model: Specific LLM model
            api_key: API key
            detection_model: Object detection model to use
        """
        self.llm = llm
        self.llm_provider = None
        self.logger = logging.getLogger(f'parrot.pipelines.{self.__class__.__name__}')
        self._json  = JSONContent()
        if not llm:
            self.llm_provider = llm_provider.lower()
            self.llm = self._get_llm(
                llm_provider,
                llm_model,
                **kwargs
            )
        else:
            self.llm_provider = llm.client_name.lower()

    def _get_llm(
        self,
        provider: str,
        model: Optional[str] = None,
        **kwargs: Any
    ) -> Any:
        """
        Get the LLM client based on provider and model

        Args:
            provider: LLM provider name
            model: Specific model to use
            **kwargs: Additional parameters for client initialization

        Returns:
            Initialized LLM client
        """
        if provider not in SUPPORTED_CLIENTS:
            raise ValueError(f"Unsupported LLM provider: {provider}")

        client_class = SUPPORTED_CLIENTS[provider]
        client = client_class(model=model, **kwargs)
        self.llm_provider = client.client_name.lower()
        return client

    @abstractmethod
    async def run(self, *args: Any, **kwargs: Any) -> Dict[str, Any]:
        """
        Run the pipeline with the provided arguments

        Args:
            *args: Positional arguments for the pipeline
            **kwargs: Keyword arguments for the pipeline

        Returns:
            Dictionary with results of the pipeline execution
        """
        raise NotImplementedError("Subclasses must implement this method")
