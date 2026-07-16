---
type: Wiki Entity
title: AzureKeyVaultSigner
id: class:parrot.security.audit_ledger.AzureKeyVaultSigner
tags:
- entity
timestamp: '2026-07-16T08:34:12+00:00'
summary: Azure Key Vault backed KMS signer for production environments.
relates_to:
- concept: class:parrot.security.audit_ledger.AbstractKMSSigner
  rel: extends
---

# AzureKeyVaultSigner

Defined in [`parrot.security.audit_ledger`](../summaries/mod:parrot.security.audit_ledger.md).

```python
class AzureKeyVaultSigner(AbstractKMSSigner)
```

Azure Key Vault backed KMS signer for production environments.

Uses the ``azure-keyvault-keys`` SDK to sign and verify entry bytes
with an asymmetric key stored in Azure Key Vault (RSA-PSS / EC).

.. note::
    This class requires the ``azure-keyvault-keys`` and
    ``azure-identity`` packages.  Import is guarded — if the packages
    are not installed a clear :class:`ImportError` is raised at
    instantiation time (not at module import time), so environments
    that use only :class:`LocalHMACSigner` are unaffected.

Args:
    vault_url: Azure Key Vault URL (e.g. ``"https://myvault.vault.azure.net/"``).
    key_name: Name of the key in the vault.
    key_version: Optional key version.  Defaults to the latest version.
    credential: An ``azure.identity`` credential object.  When ``None``,
        :class:`azure.identity.DefaultAzureCredential` is used.
    algorithm: Signing algorithm.  Defaults to ``"RS256"``.

## Methods

- `async def sign(self, data: bytes) -> str` — Sign *data* using the Azure Key Vault key.
- `async def verify(self, data: bytes, signature: str) -> bool` — Verify *signature* against *data* using the Azure Key Vault key.
