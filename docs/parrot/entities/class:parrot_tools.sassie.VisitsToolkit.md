---
type: Wiki Entity
title: VisitsToolkit
id: class:parrot_tools.sassie.VisitsToolkit
tags:
- entity
timestamp: '2026-07-14T22:20:21+00:00'
summary: Toolkit for managing employee-related operations in Sassie Survey Project.
---

# VisitsToolkit

Defined in [`parrot_tools.sassie`](../summaries/mod:parrot_tools.sassie.md).

```python
class VisitsToolkit(BaseNextStop)
```

Toolkit for managing employee-related operations in Sassie Survey Project.

This toolkit provides tools to:
- visits_survey: Get visit survey data for an specified Client.
- get_visit_questions: Get visit questions and answers for a specific client.
- get_product_information: Get basic product information.
- get_retailer: Get retailer evaluation data.

## Methods

- `async def visits_survey(self, program: str, client: str, question: str, **kwargs) -> List[EvaluationRecord]` — Fetch visit survey data for a specified client.
- `async def get_visit_questions(self, program: str, client: str, question: str) -> Dict[str, List[Dict[str, Any]]]` — Get visit information for a specific store, focusing on questions and answers.
- `async def get_product_information(self, model: str, product_name: Optional[str]=None, output_format: str='structured', structured_obj: Optional[ProductInfo]=ProductInfo) -> ProductInfo` — Retrieve product information for a given Epson product Model.
- `async def get_retailer(self, program: str, retailer: str, output_format: str='structured', structured_obj: Optional[RetailerEvaluation]=RetailerEvaluation) -> RetailerEvaluation` — Retrieve retailer evaluation data for a given retailer name.
