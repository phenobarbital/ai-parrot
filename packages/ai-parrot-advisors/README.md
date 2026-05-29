# AI-Parrot Advisors

Async-first Product Advisor and selection matching components for AI-Parrot.

## Features
- **ProductCatalog**: Hybrid search (semantic + structured) for product matching.
- **ProductAdvisorMixin**: Easily add recommendation capabilities to any Agent.
- **QuestionGenerator**: Automatically generate discriminant questions to narrow down selections.
- **SelectionStateManager**: Managed selection state with Redis persistence and Undo/Redo support.

## Installation

```bash
pip install ai-parrot-advisors
```

## Usage

Inherit from `ProductAdvisorMixin` to give your agent advisor powers:

```python
from parrot.advisors import ProductAdvisorMixin
from parrot.bots import Agent

class ShoppingAgent(ProductAdvisorMixin, Agent):
    async def configure(self):
        await super().configure()
        await self.configure_advisor()
```
