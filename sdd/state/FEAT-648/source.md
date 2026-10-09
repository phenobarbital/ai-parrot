---
kind: inline
jira_key: null
fetched_at: 2026-10-09T20:44:30Z
summary_oneline: Fill products_found for every product-detecting planogram type (Endcap etc.), not only ink_wall
---

# Source (inline)

Slug requested: `products_found_endcap`

> Ahora que incorporamos "products_found" como columna en el planogram
> (ai-parrot-pipelines, PlanogramCompliance) para el planogram_type ink_wall, la
> idea es agregar también para otros planogram, por ejemplo para el Endcap, donde
> con imágenes de referencia buscamos impresoras, pues llenar products_found con
> idéntica estructura para saber si una impresora se encontró (o no), en general
> para un planogram que detecta productos, "products_found" debería siempre
> llenarse con los productos encontrados (o no)
