# WorkdayToolkit - Multi-WSDL Configuration Guide

## Overview

The WorkdayToolkit now supports multiple WSDL paths for different Workday services. This allows you to interact with various Workday modules (Human Resources, Absence Management, Time Tracking, Staffing, Financial Management, and Recruiting) using a single toolkit instance.

## Supported Services

The toolkit supports the following Workday services:

| Service | Enum Value | Example Methods |
|---------|-----------|-----------------|
| Human Resources | `human_resources` | `wd_get_worker`, `wd_search_workers`, `wd_get_worker_contact`, `wd_get_organization` |
| Absence Management | `absence_management` | `wd_get_time_off_balance`, `wd_get_worker_time_off_balance` |
| Time Tracking | `time_tracking` | *(Placeholder for future implementation)* |
| Staffing | `staffing` | *(Placeholder for future implementation)* |
| Financial Management | `financial_management` | *(Placeholder for future implementation)* |
| Recruiting | `recruiting` | *(Placeholder for future implementation)* |

## Configuration

### Single Service (Legacy/Simple)

If you only need Human Resources functionality, you can use the simple configuration:

```python
toolkit = WorkdayToolkit(
    credentials={
        "client_id": "your-client-id",
        "client_secret": "your-client-secret",
        "token_url": "https://wd2-impl.workday.com/ccx/oauth2/token",
        "wsdl_path": "https://wd2-impl.workday.com/ccx/service/tenant/Human_Resources/v44.2?wsdl",
        "refresh_token": "your-refresh-token"
    },
    tenant_name="your_tenant"
)
```

### Multiple Services (Recommended)

For accessing multiple Workday services, provide the `wsdl_paths` parameter:

```python
toolkit = WorkdayToolkit(
    credentials={
        "client_id": "your-client-id",
        "client_secret": "your-client-secret",
        "token_url": "https://wd2-impl.workday.com/ccx/oauth2/token",
        "refresh_token": "your-refresh-token"
    },
    tenant_name="your_tenant",
    wsdl_paths={
        "human_resources": "https://wd2-impl.workday.com/ccx/service/tenant/Human_Resources/v44.2?wsdl",
        "absence_management": "https://wd2-impl.workday.com/ccx/service/tenant/Absence_Management/v45?wsdl",
        "time_tracking": "https://wd2-impl.workday.com/ccx/service/tenant/Time_Tracking/v44.2?wsdl",
        "staffing": "https://wd2-impl.workday.com/ccx/service/tenant/Staffing/v44.2?wsdl",
        "financial_management": "https://wd2-impl.workday.com/ccx/service/tenant/Financial_Management/v45?wsdl",
        "recruiting": "https://wd2-impl.workday.com/ccx/service/tenant/Recruiting/v44.2?wsdl"
    }
)
```

## How It Works

### Automatic Client Routing

The toolkit automatically selects the appropriate SOAP client based on the method you call. This is managed through the `METHOD_TO_SERVICE_MAP` configuration:

```python
METHOD_TO_SERVICE_MAP = {
    # Human Resources methods
    "wd_get_worker": WorkdayService.HUMAN_RESOURCES,
    "wd_search_workers": WorkdayService.HUMAN_RESOURCES,

    # Absence Management methods
    "wd_get_time_off_balance": WorkdayService.ABSENCE_MANAGEMENT,

    # ... etc
}
```

### Lazy Initialization

Clients are created only when needed:

1. When you call `await toolkit.wd_start()`, only the Human Resources client is initialized (primary service)
2. When you call a method requiring a different service (e.g., `wd_get_time_off_balance`), the Absence Management client is automatically created and cached
3. Subsequent calls to the same service reuse the cached client for performance

### Example Usage

```python
import asyncio
from parrot.tools.workday import WorkdayToolkit

async def main():
    # Initialize toolkit with multiple services
    toolkit = WorkdayToolkit(
        credentials={
            "client_id": "your-client-id",
            "client_secret": "your-client-secret",
            "token_url": "https://wd2-impl.workday.com/ccx/oauth2/token",
            "refresh_token": "your-refresh-token"
        },
        tenant_name="your_tenant",
        wsdl_paths={
            "human_resources": "https://wd2-impl.workday.com/ccx/service/tenant/Human_Resources/v44.2?wsdl",
            "absence_management": "https://wd2-impl.workday.com/ccx/service/tenant/Absence_Management/v45?wsdl"
        }
    )

    # Start the toolkit (initializes Human Resources client)
    await toolkit.wd_start()

    # Get worker information (uses Human Resources client)
    worker = await toolkit.wd_get_worker(worker_id="12345")
    print(f"Worker: {worker}")

    # Get time off balance (automatically creates and uses Absence Management client)
    time_off = await toolkit.wd_get_time_off_balance(worker_id="12345")
    print(f"Time Off Balance: {time_off}")

    # Search for workers (uses Human Resources client - already initialized)
    workers = await toolkit.wd_search_workers(search_text="John")
    print(f"Found {len(workers)} workers")

    # Clean up
    await toolkit.wd_close()

if __name__ == "__main__":
    asyncio.run(main())
```

## WSDL Path Formats

### Common WSDL URL Patterns

Workday WSDL URLs typically follow this format:

```
https://{impl-domain}.workday.com/{tenant}/service/{service_name}/v{version}?wsdl
```

Examples:
- Human Resources: `https://wd2-impl.workday.com/acme_impl/Human_Resources/v44.2?wsdl`
- Absence Management: `https://wd2-impl.workday.com/acme_impl/Absence_Management/v45?wsdl`
- Time Tracking: `https://wd2-impl.workday.com/acme_impl/Time_Tracking/v44.2?wsdl`

### Custom WSDL Files

You can also use custom WSDL files if your organization has specific customizations:

```python
wsdl_paths={
    "human_resources": "https://wd2-impl.workday.com/acme_impl/Human_Resources_Custom/v44.2?wsdl",
    "absence_management": "https://wd2-impl.workday.com/acme_impl/Absence_Management_Custom/v45?wsdl"
}
```

## Method-to-Service Mapping

Here's the current mapping of methods to services:

### Human Resources Service
- `wd_get_worker(worker_id)` - Get detailed worker information
- `wd_search_workers(...)` - Search for workers with filters
- `wd_get_worker_contact(worker_id)` - Get worker contact information
- `wd_get_worker_job_data(worker_id)` - Get job-related data
- `wd_get_organization(org_id)` - Get organization information
- `wd_get_workers_by_organization(org_id)` - Get all workers in an organization
- `wd_get_workers_by_ids(worker_ids)` - Get multiple workers by IDs
- `wd_search_workers_by_name(name)` - Search workers by name
- `wd_get_workers_by_manager(manager_id)` - Get workers reporting to a manager
- `wd_get_inactive_workers(...)` - Get terminated/inactive workers

### Absence Management Service
- `wd_get_time_off_balance(worker_id)` - Get time off plan balances (detailed)
- `wd_get_worker_time_off_balance(worker_id)` - Get time off balance (simple)

## Error Handling

If you call a method that requires a service for which you haven't configured a WSDL path, you'll get a helpful error:

```python
RuntimeError: WSDL path for service 'absence_management' is not configured.
Pass it in 'wsdl_paths' parameter when initializing WorkdayToolkit.
Example: wsdl_paths={'absence_management': 'https://...?wsdl'}
```

## Adding New Services

To add support for new Workday services:

1. Add the service to the `WorkdayService` enum:
   ```python
   class WorkdayService(str, Enum):
       # ... existing services
       NEW_SERVICE = "new_service"
   ```

2. Add methods to the `METHOD_TO_SERVICE_MAP`:
   ```python
   METHOD_TO_SERVICE_MAP = {
       # ... existing mappings
       "wd_get_new_data": WorkdayService.NEW_SERVICE,
   }
   ```

3. Provide the WSDL path when initializing:
   ```python
   wsdl_paths={
       # ... existing paths
       "new_service": "https://wd2-impl.workday.com/tenant/New_Service/v44.2?wsdl"
   }
   ```

## Performance Considerations

- **Client Reuse**: Clients are cached after first initialization, so subsequent calls to the same service are fast
- **Lazy Loading**: Only the services you actually use will create SOAP clients
- **Token Caching**: OAuth2 tokens are cached in Redis with TTL to minimize token refresh calls
- **Connection Pooling**: Each client maintains its own HTTP connection pool via httpx

## Migration from Old API

If you were using the old `absence_wsdl_path` parameter:

### Before:
```python
toolkit = WorkdayToolkit(
    credentials={...},
    tenant_name="your_tenant",
    absence_wsdl_path="https://.../Absence_Management/v45?wsdl"
)
```

### After:
```python
toolkit = WorkdayToolkit(
    credentials={...},
    tenant_name="your_tenant",
    wsdl_paths={
        "human_resources": "https://.../Human_Resources/v44.2?wsdl",
        "absence_management": "https://.../Absence_Management/v45?wsdl"
    }
)
```

The old API is still supported for backward compatibility if you use `credentials["wsdl_path"]` for Human Resources.
