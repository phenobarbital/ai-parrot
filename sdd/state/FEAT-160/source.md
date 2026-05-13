---
kind: inline
jira_key: null
fetched_at: 2026-05-11T21:30:00Z
summary_oneline: Add CloudSploit --config CONFIG file support to ContainerSecurityToolkit run_scan
---

# CloudSploit configuration

## Abstract

Github repository: https://github.com/aquasecurity/cloudsploit

Current configuration of CloudSploit requires passing directly all credentials, region, etc, add support for config:

```
--config CONFIG
```

with `config` user expect to configure which configuration been applied to run_scan, add into Input args of run_scan the configuration file, if no configuration file is provided then use default credentials, else use the configuration file.
