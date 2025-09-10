SELECT DISTINCT p.model 
FROM google.products p
JOIN google.customer_satisfaction cs USING (sku)
JOIN google.products_evaluation pe USING (sku)
JOIN google.products_compliant pc USING (sku)
WHERE p.specifications is not null and cs.customer_satisfaction is not null
GROUP BY p.model