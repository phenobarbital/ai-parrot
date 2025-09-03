SELECT p.product_name as name, '' as description, p.model, p.image_url as picture_url, p.brand, p.price as pricing, customer_satisfaction, product_evaluation, product_compliant, specifications, pe.avg_rating as review_average, pe.num_reviews as reviews FROM google.products p
JOIN google.customer_satisfaction cs USING (sku)
JOIN google.products_evaluation pe  USING (sku)
JOIN google.products_compliant pc USING (sku)
WHERE p.model = '{model}' and p.specifications is not null and cs.customer_satisfaction is not null
GROUP BY p.product_name, p.model, p.image_url, p.brand, p.price, customer_satisfaction, product_evaluation, product_compliant, specifications, pe.avg_rating, pe.num_reviews
