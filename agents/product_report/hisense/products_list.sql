SELECT DISTINCT p.model 
FROM hisense.products p
JOIN hisense.customer_satisfaction cs ON p.model_sku = cs.sku
JOIN hisense.products_evaluations pe ON p.model_sku = cs.sku
JOIN hisense.products_compliant pc ON p.model_sku = cs.sku
WHERE p.specifications is not null and cs.customer_satisfaction is not null
GROUP BY p.model