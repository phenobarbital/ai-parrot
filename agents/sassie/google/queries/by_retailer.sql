SELECT account_name, created_at, weighted_score, retailer_evaluation FROM google.retailer_evaluations
WHERE account_name = '{retailer}'
