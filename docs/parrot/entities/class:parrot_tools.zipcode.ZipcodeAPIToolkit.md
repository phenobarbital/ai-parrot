---
type: Wiki Entity
title: ZipcodeAPIToolkit
id: class:parrot_tools.zipcode.ZipcodeAPIToolkit
tags:
- entity
timestamp: '2026-07-14T22:20:21+00:00'
summary: Toolkit for interacting with ZipcodeAPI service.
relates_to:
- concept: class:parrot.tools.toolkit.AbstractToolkit
  rel: extends
---

# ZipcodeAPIToolkit

Defined in [`parrot_tools.zipcode`](../summaries/mod:parrot_tools.zipcode.md).

```python
class ZipcodeAPIToolkit(AbstractToolkit)
```

Toolkit for interacting with ZipcodeAPI service.

Provides methods for:
- Getting zipcode location information
- Calculating distance between zipcodes
- Finding zipcodes within a radius
- Finding zipcodes for a city/state

## Methods

- `async def get_zipcode_location(self, zipcode: Union[str, int], unit: str='degrees') -> Dict[str, Any]` — Get geographical information for a zipcode including city, state, latitude, longitude, and timezone.
- `async def calculate_zipcode_distance(self, zipcode1: Union[str, int], zipcode2: Union[str, int], unit: str='mile') -> Dict[str, Any]` — Calculate the distance between two zipcodes.
- `async def find_zipcodes_in_radius(self, zipcode: Union[str, int], radius: int=5, unit: str='mile') -> Dict[str, Any]` — Find all zipcodes within a given radius of a center zipcode.
- `async def get_city_zipcodes(self, city: str, state: str) -> Dict[str, Any]` — Get all zipcodes for a given city and state.
- `async def get_multiple_locations(self, zipcodes: List[Union[str, int]], unit: str='degrees') -> Dict[str, Any]` — Get location information for multiple zipcodes.
- `async def validate_zipcode(self, zipcode: Union[str, int]) -> Dict[str, Any]` — Validate if a zipcode exists and return basic info.
