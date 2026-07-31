"""Unit tests for the 'nova' LLMFactory registration (FEAT-315, TASK-1810).

No real AWS credentials or network access required — ``NovaClient``
construction does not require them (lazy ``aioboto3``/Pre-Alpha SDK
imports).
"""
from parrot.clients.factory import LLMFactory, SUPPORTED_CLIENTS
from parrot.clients.nova import NovaClient


def test_nova_key_registered_lazy():
    assert "nova" in SUPPORTED_CLIENTS
    assert callable(SUPPORTED_CLIENTS["nova"])
    assert not isinstance(SUPPORTED_CLIENTS["nova"], type)


def test_create_default():
    client = LLMFactory.create("nova")
    assert isinstance(client, NovaClient)
    assert client._translate_model(None) == "us.amazon.nova-2-lite-v1:0"


def test_create_with_model():
    client = LLMFactory.create("nova:nova-micro")
    assert client.model == "nova-micro"


def test_nova_not_in_provider_backend():
    from parrot.clients.factory import PROVIDER_BACKEND
    assert "nova" not in PROVIDER_BACKEND
