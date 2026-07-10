---
id: F008
query: BaseRenderer abstract signature
type: read
path: packages/ai-parrot/src/parrot/outputs/formats/base.py
lines: 448-465
---

Abstract render() signature:
  async def render(self, response, environment='terminal', export_format='html',
                   include_code=False, **kwargs) -> Tuple[Any, Optional[Any]]

Note: default environment is 'terminal', not 'default' as spec's A2UIRenderer claims.
Spec's A2UIRenderer.render() signature differs from BaseRenderer's — needs alignment.
