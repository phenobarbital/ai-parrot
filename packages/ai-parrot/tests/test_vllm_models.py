"""Unit tests for vLLM Pydantic models."""

import pytest
from pydantic import BaseModel, ValidationError

from parrot.models.vllm import (
    VLLMConfig,
    VLLMSamplingParams,
    VLLMLoRARequest,
    VLLMGuidedParams,
    VLLMBatchRequest,
    VLLMBatchResponse,
    VLLMServerInfo,
    pydantic_to_guided_json,
)


# ---- VLLMConfig Tests ----

class TestVLLMConfig:
    """Tests for VLLMConfig model."""

    def test_default_values(self):
        """Default values are correct."""
        config = VLLMConfig()
        assert config.base_url == "http://localhost:8000/v1"
        assert config.api_key is None
        assert config.timeout == 120

    def test_custom_values(self):
        """Custom values are set correctly."""
        config = VLLMConfig(
            base_url="http://custom:9000/v1",
            api_key="secret-key",
            timeout=60
        )
        assert config.base_url == "http://custom:9000/v1"
        assert config.api_key == "secret-key"
        assert config.timeout == 60

    def test_timeout_validation(self):
        """Timeout must be >= 1."""
        with pytest.raises(ValidationError):
            VLLMConfig(timeout=0)

        with pytest.raises(ValidationError):
            VLLMConfig(timeout=-1)


# ---- VLLMSamplingParams Tests ----

class TestVLLMSamplingParams:
    """Tests for VLLMSamplingParams model."""

    def test_default_values(self):
        """Default values are correct."""
        params = VLLMSamplingParams()
        assert params.top_k == -1
        assert params.min_p == 0.0
        assert params.repetition_penalty == 1.0
        assert params.length_penalty == 1.0
        assert params.presence_penalty == 0.0
        assert params.frequency_penalty == 0.0

    def test_custom_values(self):
        """Custom values are set correctly."""
        params = VLLMSamplingParams(
            top_k=50,
            min_p=0.1,
            repetition_penalty=1.2,
            length_penalty=0.8
        )
        assert params.top_k == 50
        assert params.min_p == 0.1
        assert params.repetition_penalty == 1.2
        assert params.length_penalty == 0.8

    def test_min_p_validation(self):
        """min_p must be between 0.0 and 1.0."""
        with pytest.raises(ValidationError):
            VLLMSamplingParams(min_p=-0.1)

        with pytest.raises(ValidationError):
            VLLMSamplingParams(min_p=1.5)

    def test_to_extra_body_empty_for_defaults(self):
        """to_extra_body returns empty dict for default values."""
        params = VLLMSamplingParams()
        assert params.to_extra_body() == {}

    def test_to_extra_body_includes_non_defaults(self):
        """to_extra_body includes only non-default values."""
        params = VLLMSamplingParams(
            top_k=50,
            min_p=0.1,
            repetition_penalty=1.2
        )
        extra = params.to_extra_body()
        assert extra["top_k"] == 50
        assert extra["min_p"] == 0.1
        assert extra["repetition_penalty"] == 1.2
        assert "length_penalty" not in extra  # Still default


# ---- VLLMLoRARequest Tests ----

class TestVLLMLoRARequest:
    """Tests for VLLMLoRARequest model."""

    def test_required_lora_name(self):
        """lora_name is required."""
        request = VLLMLoRARequest(lora_name="my-adapter")
        assert request.lora_name == "my-adapter"
        assert request.lora_int_id is None
        assert request.lora_local_path is None

    def test_all_fields(self):
        """All fields can be set."""
        request = VLLMLoRARequest(
            lora_name="adapter1",
            lora_int_id=42,
            lora_local_path="/path/to/adapter"
        )
        assert request.lora_name == "adapter1"
        assert request.lora_int_id == 42
        assert request.lora_local_path == "/path/to/adapter"

    def test_to_extra_body_minimal(self):
        """to_extra_body with only required fields."""
        request = VLLMLoRARequest(lora_name="my-lora")
        extra = request.to_extra_body()
        assert extra == {"lora_request": {"lora_name": "my-lora"}}

    def test_to_extra_body_full(self):
        """to_extra_body with all optional fields."""
        request = VLLMLoRARequest(
            lora_name="adapter",
            lora_int_id=5,
            lora_local_path="/adapters/v1"
        )
        extra = request.to_extra_body()
        assert extra["lora_request"]["lora_name"] == "adapter"
        assert extra["lora_request"]["lora_int_id"] == 5
        assert extra["lora_request"]["lora_local_path"] == "/adapters/v1"


# ---- VLLMGuidedParams Tests ----

class TestVLLMGuidedParams:
    """Tests for VLLMGuidedParams model."""

    def test_default_all_none(self):
        """All fields default to None."""
        params = VLLMGuidedParams()
        assert params.guided_json is None
        assert params.guided_regex is None
        assert params.guided_choice is None
        assert params.guided_grammar is None

    def test_guided_json_only(self):
        """Single constraint: guided_json."""
        schema = {"type": "object", "properties": {"name": {"type": "string"}}}
        params = VLLMGuidedParams(guided_json=schema)
        assert params.guided_json == schema

    def test_guided_regex_only(self):
        """Single constraint: guided_regex."""
        params = VLLMGuidedParams(guided_regex=r"\d{3}-\d{4}")
        assert params.guided_regex == r"\d{3}-\d{4}"

    def test_guided_choice_only(self):
        """Single constraint: guided_choice."""
        params = VLLMGuidedParams(guided_choice=["yes", "no", "maybe"])
        assert params.guided_choice == ["yes", "no", "maybe"]

    def test_guided_grammar_only(self):
        """Single constraint: guided_grammar."""
        params = VLLMGuidedParams(guided_grammar="root ::= 'hello' | 'world'")
        assert params.guided_grammar == "root ::= 'hello' | 'world'"

    def test_mutually_exclusive_validation(self):
        """Only one constraint can be specified."""
        with pytest.raises(ValidationError):
            VLLMGuidedParams(
                guided_json={"type": "object"},
                guided_regex=r"\d+"
            )

        with pytest.raises(ValidationError):
            VLLMGuidedParams(
                guided_choice=["a", "b"],
                guided_grammar="root ::= 'x'"
            )

    def test_to_extra_body_empty(self):
        """to_extra_body returns empty dict when no constraint."""
        params = VLLMGuidedParams()
        assert params.to_extra_body() == {}

    def test_to_extra_body_json(self):
        """to_extra_body with guided_json."""
        schema = {"type": "string"}
        params = VLLMGuidedParams(guided_json=schema)
        assert params.to_extra_body() == {"guided_json": schema}

    def test_to_extra_body_regex(self):
        """to_extra_body with guided_regex."""
        params = VLLMGuidedParams(guided_regex=r"[A-Z]+")
        assert params.to_extra_body() == {"guided_regex": r"[A-Z]+"}

    def test_to_extra_body_choice(self):
        """to_extra_body with guided_choice."""
        params = VLLMGuidedParams(guided_choice=["option1", "option2"])
        assert params.to_extra_body() == {"guided_choice": ["option1", "option2"]}

    def test_to_extra_body_grammar(self):
        """to_extra_body with guided_grammar."""
        params = VLLMGuidedParams(guided_grammar="root ::= 'test'")
        assert params.to_extra_body() == {"guided_grammar": "root ::= 'test'"}


# ---- VLLMBatchRequest Tests ----

class TestVLLMBatchRequest:
    """Tests for VLLMBatchRequest model."""

    def test_required_prompt(self):
        """prompt is required."""
        request = VLLMBatchRequest(prompt="Hello, world!")
        assert request.prompt == "Hello, world!"
        assert request.model is None
        assert request.temperature == 0.7
        assert request.max_tokens is None

    def test_all_fields(self):
        """All fields can be set."""
        schema = {"type": "object"}
        sampling = VLLMSamplingParams(top_k=50)
        request = VLLMBatchRequest(
            prompt="Test prompt",
            model="llama3:8b",
            temperature=0.5,
            max_tokens=100,
            guided_json=schema,
            lora_adapter="my-lora",
            sampling_params=sampling
        )
        assert request.prompt == "Test prompt"
        assert request.model == "llama3:8b"
        assert request.temperature == 0.5
        assert request.max_tokens == 100
        assert request.guided_json == schema
        assert request.lora_adapter == "my-lora"
        assert request.sampling_params.top_k == 50

    def test_temperature_validation(self):
        """temperature must be between 0.0 and 2.0."""
        with pytest.raises(ValidationError):
            VLLMBatchRequest(prompt="test", temperature=-0.1)

        with pytest.raises(ValidationError):
            VLLMBatchRequest(prompt="test", temperature=2.5)


# ---- VLLMBatchResponse Tests ----

class TestVLLMBatchResponse:
    """Tests for VLLMBatchResponse model."""

    def test_default_values(self):
        """Default values are correct."""
        response = VLLMBatchResponse()
        assert response.responses == []
        assert response.errors == {}
        assert response.total_requests == 0
        assert response.successful == 0
        assert response.failed == 0
        assert response.total_tokens == 0

    def test_successful_batch(self):
        """Batch with successful responses."""
        response = VLLMBatchResponse(
            responses=["Response 1", "Response 2", "Response 3"],
            total_requests=3,
            successful=3,
            failed=0,
            total_tokens=150
        )
        assert len(response.responses) == 3
        assert response.successful == 3
        assert response.failed == 0

    def test_partial_failure(self):
        """Batch with some failures."""
        response = VLLMBatchResponse(
            responses=["Response 1", None, "Response 3"],
            errors={1: "Model not found"},
            total_requests=3,
            successful=2,
            failed=1
        )
        assert response.responses[0] == "Response 1"
        assert response.responses[1] is None
        assert response.errors[1] == "Model not found"
        assert response.failed == 1


# ---- VLLMServerInfo Tests ----

class TestVLLMServerInfo:
    """Tests for VLLMServerInfo model."""

    def test_default_all_none(self):
        """All fields default to None."""
        info = VLLMServerInfo()
        assert info.version is None
        assert info.model_id is None
        assert info.gpu_memory_utilization is None
        assert info.max_model_len is None
        assert info.tensor_parallel_size is None

    def test_all_fields(self):
        """All fields can be set."""
        info = VLLMServerInfo(
            version="0.4.0",
            model_id="meta-llama/Llama-3.1-8B-Instruct",
            gpu_memory_utilization=0.9,
            max_model_len=8192,
            tensor_parallel_size=2
        )
        assert info.version == "0.4.0"
        assert info.model_id == "meta-llama/Llama-3.1-8B-Instruct"
        assert info.gpu_memory_utilization == 0.9
        assert info.max_model_len == 8192
        assert info.tensor_parallel_size == 2


# ---- pydantic_to_guided_json Tests ----

class TestPydanticToGuidedJson:
    """Tests for pydantic_to_guided_json helper."""

    def test_simple_model(self):
        """Convert simple Pydantic model to JSON schema."""

        class Person(BaseModel):
            name: str
            age: int

        schema = pydantic_to_guided_json(Person)
        assert schema["type"] == "object"
        assert "properties" in schema
        assert "name" in schema["properties"]
        assert "age" in schema["properties"]
        assert schema["properties"]["name"]["type"] == "string"
        assert schema["properties"]["age"]["type"] == "integer"

    def test_nested_model(self):
        """Convert nested Pydantic model to JSON schema."""

        class Address(BaseModel):
            street: str
            city: str

        class Person(BaseModel):
            name: str
            address: Address

        schema = pydantic_to_guided_json(Person)
        assert "properties" in schema
        assert "name" in schema["properties"]
        assert "address" in schema["properties"]
        # Nested models are referenced via $defs
        assert "$defs" in schema or "address" in schema["properties"]

    def test_optional_fields(self):
        """Convert model with optional fields."""
        from typing import Optional

        class Config(BaseModel):
            name: str
            debug: Optional[bool] = None

        schema = pydantic_to_guided_json(Config)
        assert "properties" in schema
        assert "name" in schema["properties"]
        assert "debug" in schema["properties"]

    def test_list_field(self):
        """Convert model with list field."""
        from typing import List

        class Tags(BaseModel):
            items: List[str]

        schema = pydantic_to_guided_json(Tags)
        assert "properties" in schema
        assert "items" in schema["properties"]
        items_schema = schema["properties"]["items"]
        assert items_schema["type"] == "array"
        assert items_schema["items"]["type"] == "string"

    def test_enum_field(self):
        """Convert model with enum field."""
        from enum import Enum

        class Status(str, Enum):
            ACTIVE = "active"
            INACTIVE = "inactive"

        class Item(BaseModel):
            status: Status

        schema = pydantic_to_guided_json(Item)
        assert "properties" in schema
        assert "status" in schema["properties"]

    def test_model_with_description(self):
        """Convert model with field descriptions."""
        from pydantic import Field

        class Documented(BaseModel):
            name: str = Field(..., description="The item name")
            count: int = Field(default=0, description="Number of items")

        schema = pydantic_to_guided_json(Documented)
        assert "properties" in schema
        # Descriptions should be preserved in schema
        assert schema["properties"]["name"].get("description") == "The item name"
