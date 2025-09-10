SELECT p.product_name as name, '' as description, p.model, p.picture_url, p.brand, p.pricing, customer_satisfaction, product_evaluation, product_compliant, specifications, pe.avg_rating as review_average, pe.num_reviews as reviews
FROM hisense.products p
JOIN hisense.customer_satisfaction cs ON p.model_sku = cs.sku
JOIN hisense.products_evaluations pe ON p.model_sku = cs.sku
JOIN hisense.products_compliant pc ON p.model_sku = cs.sku
WHERE p.model = $1
GROUP BY p.product_name, p.model, p.picture_url, p.brand, p.pricing, customer_satisfaction, product_evaluation, product_compliant, specifications, pe.avg_rating, pe.num_reviews
LIMIT 1
