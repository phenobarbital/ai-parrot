# IT Troubleshooting Manual

## 1. Account & Access

### 1.1 Password Reset
Employees can self-reset their corporate password through the SSO portal at
https://sso.acme.example/reset.

Requirements:
- Employee ID (8-digit number on the badge).
- Access to the registered backup phone for the SMS code.

If the SMS code never arrives the employee should escalate via the
help desk so a manual reset can be issued.

### 1.2 MFA Lock-out
If multi-factor authentication is failing after five attempts the
account is locked for 15 minutes. Anything beyond that is a manual
unlock by IT.

### 1.3 VPN Access
The corporate VPN client is GlobalProtect 6.x. Configuration profile is
pushed via MDM. If the profile is missing, run:

    glprotect --refresh-config

## 2. Workstation Issues

### 2.1 Laptop Will Not Boot
1. Hold the power button for 10 seconds, release, then press again.
2. If the screen stays blank, attempt the safe-boot key combination
   (F2 + Power on most fleet machines).
3. If still blank, file a ticket — hardware swap likely needed.

### 2.2 Slow Performance
Common causes: disk near full, Chrome with 80+ tabs, security scan
running. Restart fixes 70% of cases.

### 2.3 Email Won't Open
Outlook profile corruption is the leading cause. Steps:
1. Quit Outlook.
2. Control Panel → Mail → Show Profiles → Remove the profile.
3. Reopen Outlook; it rebuilds the profile.

If the issue persists after rebuild, capture the error code shown on
launch — it tells whether the issue is the local profile or the Exchange
server.

## 3. Production Incidents

### 3.1 Severity Levels
- **Sev-1**: Customer-impacting outage, data loss, or security breach.
- **Sev-2**: Internal service degraded, no direct customer impact.
- **Sev-3**: Single-user productivity issue.

Sev-1 always requires escalation to the on-call director regardless of
business hours. Sev-2 escalates during business hours; Sev-3 stays with
first-line support.

### 3.2 Service Down Reporting
For any "production down" report, capture:
- Service name (e.g. order-service, payments-api).
- First-noticed timestamp.
- Approximate user impact (employees blocked, customers affected,
  revenue per hour).
- Whether checkout, login, or payments are affected — these always
  trigger Sev-1 handling.

## 4. Security Incidents

### 4.1 Suspected Phishing
Forward the email to phishing@acme.example. Do not click links or open
attachments.

### 4.2 Data Loss / Exfiltration
Any suspicion of data exfiltration, lost device with corporate data, or
leaked credentials is Sev-1 — escalate immediately. Do not attempt to
remediate on your own.
