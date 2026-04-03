# AWS Cost Optimization — Implementation Playbook

Terraform, AWS CLI, and boto3 examples for the most impactful optimizations.

---

## S3 Lifecycle Policy (Terraform)

```hcl
resource "aws_s3_bucket_lifecycle_configuration" "cost_optimized" {
  bucket = aws_s3_bucket.main.id

  rule {
    id     = "tiered-storage"
    status = "Enabled"

    transition {
      days          = 30
      storage_class = "STANDARD_IA"
    }

    transition {
      days          = 90
      storage_class = "GLACIER"
    }

    transition {
      days          = 180
      storage_class = "DEEP_ARCHIVE"
    }

    expiration {
      days = 730  # 2 years
    }

    noncurrent_version_expiration {
      noncurrent_days = 30
    }
  }
}
```

---

## Budget Alerts (Terraform)

```hcl
resource "aws_budgets_budget" "monthly" {
  name              = "${var.project}-monthly-budget"
  budget_type       = "COST"
  limit_amount      = var.monthly_budget_usd
  limit_unit        = "USD"
  time_period_start = "2024-01-01_00:00"
  time_unit         = "MONTHLY"

  cost_filter {
    name   = "TagKeyValue"
    values = ["user:Project$${var.project}"]
  }

  notification {
    comparison_operator       = "GREATER_THAN"
    threshold                 = 50
    threshold_type            = "PERCENTAGE"
    notification_type         = "ACTUAL"
    subscriber_email_addresses = var.alert_emails
  }

  notification {
    comparison_operator       = "GREATER_THAN"
    threshold                 = 80
    threshold_type            = "PERCENTAGE"
    notification_type         = "ACTUAL"
    subscriber_email_addresses = var.alert_emails
  }

  notification {
    comparison_operator       = "GREATER_THAN"
    threshold                 = 100
    threshold_type            = "PERCENTAGE"
    notification_type         = "FORECASTED"
    subscriber_email_addresses = var.alert_emails
  }
}
```

---

## Cost Anomaly Detection (Terraform)

```hcl
resource "aws_ce_anomaly_monitor" "service" {
  name              = "${var.project}-service-monitor"
  monitor_type      = "DIMENSIONAL"
  monitor_dimension = "SERVICE"
}

resource "aws_ce_anomaly_subscription" "alerts" {
  name = "${var.project}-anomaly-alerts"

  monitor_arn_list = [aws_ce_anomaly_monitor.service.arn]

  frequency = "DAILY"

  threshold_expression {
    dimension {
      key           = "ANOMALY_TOTAL_IMPACT_ABSOLUTE"
      values        = ["100"]  # alert when anomaly > $100
      match_options = ["GREATER_THAN_OR_EQUAL"]
    }
  }

  subscriber {
    type    = "EMAIL"
    address = var.alert_email
  }
}
```

---

## Auto-Scaling with Target Tracking (Terraform)

```hcl
resource "aws_autoscaling_group" "app" {
  name                = "${var.project}-asg"
  min_size            = var.asg_min
  max_size            = var.asg_max
  desired_capacity    = var.asg_desired
  vpc_zone_identifier = var.private_subnet_ids

  mixed_instances_policy {
    launch_template {
      launch_template_specification {
        launch_template_id = aws_launch_template.app.id
        version            = "$Latest"
      }

      override {
        instance_type = "m7g.large"   # Graviton primary
      }
      override {
        instance_type = "m6g.large"   # Graviton fallback
      }
      override {
        instance_type = "m6i.large"   # x86 fallback
      }
    }

    instances_distribution {
      on_demand_base_capacity                  = 1
      on_demand_percentage_above_base_capacity = 25  # 75% Spot
      spot_allocation_strategy                 = "capacity-optimized"
    }
  }

  tag {
    key                 = "Project"
    value               = var.project
    propagate_at_launch = true
  }
}

resource "aws_autoscaling_policy" "cpu_target" {
  name                   = "${var.project}-cpu-target"
  autoscaling_group_name = aws_autoscaling_group.app.name
  policy_type            = "TargetTrackingScaling"

  target_tracking_configuration {
    predefined_metric_specification {
      predefined_metric_type = "ASGAverageCPUUtilization"
    }
    target_value = 65.0
  }
}
```

---

## Tagging All Resources (Terraform)

```hcl
locals {
  common_tags = {
    Environment = var.environment
    Project     = var.project
    CostCenter  = var.cost_center
    Owner       = var.owner_email
    ManagedBy   = "terraform"
  }
}

# Apply to any resource:
resource "aws_instance" "example" {
  ami           = var.ami_id
  instance_type = "m7g.medium"
  tags          = merge(local.common_tags, { Name = "web-server" })
}
```

---

## Cost Explorer Query (boto3)

```python
"""Query last 30 days cost grouped by service."""
import datetime
import boto3

def get_monthly_cost_by_service() -> list[dict]:
    """Return cost breakdown by AWS service for the last 30 days."""
    client = boto3.client("ce")
    end = datetime.date.today()
    start = end - datetime.timedelta(days=30)

    response = client.get_cost_and_usage(
        TimePeriod={"Start": start.isoformat(), "End": end.isoformat()},
        Granularity="MONTHLY",
        Metrics=["UnblendedCost"],
        GroupBy=[{"Type": "DIMENSION", "Key": "SERVICE"}],
    )

    results = []
    for group in response["ResultsByTime"][0]["Groups"]:
        service = group["Keys"][0]
        amount = float(group["Metrics"]["UnblendedCost"]["Amount"])
        if amount > 0.01:
            results.append({"service": service, "cost_usd": round(amount, 2)})

    return sorted(results, key=lambda x: x["cost_usd"], reverse=True)
```

---

## Right-Sizing Check (AWS CLI)

```bash
# List EC2 instances with low CPU (< 20% average over 7 days)
for id in $(aws ec2 describe-instances \
  --query 'Reservations[].Instances[].InstanceId' --output text); do
  avg=$(aws cloudwatch get-metric-statistics \
    --namespace AWS/EC2 \
    --metric-name CPUUtilization \
    --dimensions Name=InstanceId,Value="$id" \
    --start-time "$(date -d '7 days ago' -u +%Y-%m-%dT%H:%M:%S)" \
    --end-time "$(date -u +%Y-%m-%dT%H:%M:%S)" \
    --period 604800 \
    --statistics Average \
    --query 'Datapoints[0].Average' --output text 2>/dev/null)
  if [ "$avg" != "None" ] && [ "$(echo "$avg < 20" | bc -l)" -eq 1 ]; then
    echo "LOW CPU: $id — avg ${avg}%"
  fi
done
```

---

## Idle Resource Cleanup (AWS CLI)

```bash
# Unattached EBS volumes
aws ec2 describe-volumes \
  --filters Name=status,Values=available \
  --query 'Volumes[].{ID:VolumeId,Size:Size,Created:CreateTime}' \
  --output table

# Unused Elastic IPs
aws ec2 describe-addresses \
  --query 'Addresses[?AssociationId==`null`].{IP:PublicIp,AllocId:AllocationId}' \
  --output table

# Old snapshots (> 90 days)
aws ec2 describe-snapshots --owner-ids self \
  --query "Snapshots[?StartTime<='$(date -d '90 days ago' -u +%Y-%m-%dT%H:%M:%S)'].\
{ID:SnapshotId,Size:VolumeSize,Date:StartTime}" \
  --output table
```

---

## Lambda Power Tuning (Step Functions)

Deploy the open-source [aws-lambda-power-tuning](https://github.com/alexcasalboni/aws-lambda-power-tuning) state machine:

```bash
# Deploy via SAR (Serverless Application Repository)
aws serverlessrepo create-cloud-formation-change-set \
  --application-id arn:aws:serverlessrepo:us-east-1:451282441545:applications/aws-lambda-power-tuning \
  --stack-name lambda-power-tuning \
  --capabilities CAPABILITY_IAM

# Then invoke with your function ARN:
# { "lambdaARN": "arn:aws:lambda:...:my-function", "powerValues": [128,256,512,1024,2048], "num": 50 }
```

---

## VPC Endpoints for S3 / DynamoDB (Terraform)

Eliminates NAT Gateway data processing charges for these services:

```hcl
resource "aws_vpc_endpoint" "s3" {
  vpc_id       = var.vpc_id
  service_name = "com.amazonaws.${var.region}.s3"
  vpc_endpoint_type = "Gateway"
  route_table_ids   = var.private_route_table_ids
  tags = local.common_tags
}

resource "aws_vpc_endpoint" "dynamodb" {
  vpc_id       = var.vpc_id
  service_name = "com.amazonaws.${var.region}.dynamodb"
  vpc_endpoint_type = "Gateway"
  route_table_ids   = var.private_route_table_ids
  tags = local.common_tags
}
```
