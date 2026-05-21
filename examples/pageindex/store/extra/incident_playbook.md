# Incident Response Playbook (AWS / SOC 2)

## Detection
Open an incident as soon as Amazon GuardDuty, AWS Security Hub, or an internal alert from CloudWatch indicates a confirmed unauthorised access to a production AWS account or to customer data stored in S3, RDS, or DynamoDB.

## Containment
Within 30 minutes of confirmation, revoke compromised IAM credentials, rotate access keys, and isolate affected EC2 instances by attaching a quarantine security group. Snapshot the instance volumes for forensic analysis before terminating.

## Notification timeline
SOC 2 CC2.3 requires that material security incidents are communicated to internal stakeholders without undue delay. Notify the CISO and the SOC 2 control owner within 4 hours; notify affected customers per contractual SLAs (typically 72 hours for material breaches).
