"""
Security utilities for AI-Parrot.

Includes prompt injection detection, query validation, vault credential
utilities relocated from parrot.handlers in FEAT-203, and the shared
command-sanitizer engine relocated from parrot_tools in FEAT-252.
"""
from .prompt_injection import (
    PromptInjectionDetector,
    SecurityEventLogger,
    ThreatLevel,
    PromptInjectionException
)
from .query_validator import (
    QueryLanguage,
    QueryValidator,
)
from .vault_utils import (
    load_vault_keys,
    store_vault_credential,
    retrieve_vault_credential,
    delete_vault_credential,
    oauth2_vault_name,
    VAULT_CRED_COLLECTION,
)
from .credentials_utils import (
    encrypt_credential,
    decrypt_credential,
)
from .command_sanitizer import (
    SecurityLevel,
    CommandVerdict,
    ValidationResult,
    CommandRule,
    CommandSecurityError,
    SecurityPolicy,
    CommandSanitizer,
)

__all__ = [
    'PromptInjectionDetector',
    'SecurityEventLogger',
    'ThreatLevel',
    'PromptInjectionException',
    'QueryLanguage',
    'QueryValidator',
    'load_vault_keys',
    'store_vault_credential',
    'retrieve_vault_credential',
    'delete_vault_credential',
    'oauth2_vault_name',
    'VAULT_CRED_COLLECTION',
    'encrypt_credential',
    'decrypt_credential',
    # Command sanitizer engine (FEAT-252)
    'SecurityLevel',
    'CommandVerdict',
    'ValidationResult',
    'CommandRule',
    'CommandSecurityError',
    'SecurityPolicy',
    'CommandSanitizer',
]
