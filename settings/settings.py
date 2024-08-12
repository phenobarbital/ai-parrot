"""
Settings Configuration for Parrot-AI.

Basic Configuration.
"""
from navconfig import config, BASE_DIR
from navconfig.logging import logging


logging.getLogger(name='sentence_transformers').setLevel(logging.WARNING)

AUTHENTICATION_BACKENDS = (
    'navigator_auth.backends.AzureAuth',
    'navigator_auth.backends.APIKeyAuth',
    'navigator_auth.backends.TokenAuth',
    'navigator_auth.backends.TrocToken',
    'navigator_auth.backends.ADFSAuth',
    'navigator_auth.backends.Oauth2Provider',
    'navigator_auth.backends.BasicAuth'
)

# Azure Bot:
MS_TENANT_ID = config.get('MS_TENANT_ID')
MS_CLIENT_ID = config.get('MS_CLIENT_ID')
MS_CLIENT_SECRET = config.get('MS_CLIENT_SECRET')

# New Bot:
NEW_CLIENT_ID = config.get('NEW_CLIENT_ID')
NEW_CLIENT_SECRET = config.get('NEW_CLIENT_SECRET')

# Other Bots:
BOSE_CLIENT_ID = config.get('BOSE_CLIENT_ID')
BOSE_CLIENT_SECRET = config.get('BOSE_CLIENT_SECRET')
ODOO_CLIENT_ID = config.get('ODOO_CLIENT_ID')
ODOO_CLIENT_SECRET = config.get('ODOO_CLIENT_SECRET')
ASKBRETT_CLIENT_ID = config.get('ASKBRETT_CLIENT_ID')
ASKBRETT_CLIENT_SECRET = config.get('ASKBRETT_CLIENT_SECRET')
TROCERS_CLIENT_ID = config.get('TROCERS_CLIENT_ID')
TROCERS_CLIENT_SECRET = config.get('TROCERS_CLIENT_SECRET')
BOTTROCDEV_CLIENT_ID = config.get('BOTTROCDEV_CLIENT_ID')
BOTTROCDEV_CLIENT_SECRET = config.get('BOTTROCDEV_CLIENT_SECRET')
ATTBOT_CLIENT_ID = config.get('ATTBOT_CLIENT_ID')
ATTBOT_CLIENT_SECRET = config.get('ATTBOT_CLIENT_SECRET')


# ScyllaDB Configuration:
SCYLLADB_HOST = config.get('SCYLLADB_HOST', fallback='localhost')
SCYLLADB_PORT = int(config.get('SCYLLADB_PORT', fallback=9042))
SCYLLADB_USERNAME = config.get('SCYLLADB_USERNAME', fallback='navigator')
SCYLLADB_PASSWORD = config.get('SCYLLADB_PASSWORD', fallback='navigator')
SCYLLADB_KEYSPACE = config.get('SCYLLADB_KEYSPACE', fallback='navigator')
