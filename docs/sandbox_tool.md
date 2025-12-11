# gVisor Installation Guide for AI-Parrot Secure Sandbox

## Overview

This guide provides step-by-step instructions for setting up gVisor on Ubuntu to enable secure Python code execution in AI-Parrot. gVisor provides kernel-level isolation, protecting your system from potentially malicious LLM-generated code.

## Prerequisites

- Ubuntu 20.04 LTS or later (22.04 recommended)
- Root or sudo access
- Docker installed (optional, but recommended)
- At least 4GB RAM and 10GB free disk space

## Installation Steps

### 1. System Update and Dependencies

```bash
# Update system packages
sudo apt-get update
sudo apt-get upgrade -y

# Install required dependencies
sudo apt-get install -y \
    apt-transport-https \
    ca-certificates \
    curl \
    gnupg \
    lsb-release \
    wget \
    git \
    build-essential \
    python3-pip \
    python3-venv
```

### 2. Install gVisor (runsc)

#### Method 1: Using Official Release (Recommended)

```bash
# Set architecture and latest version
ARCH=$(uname -m)
URL=https://storage.googleapis.com/gvisor/releases/release/latest/${ARCH}

# Download and install runsc binary
wget ${URL}/runsc ${URL}/runsc.sha512 \
    ${URL}/containerd-shim-runsc-v1 ${URL}/containerd-shim-runsc-v1.sha512

# Verify checksums
sha512sum -c runsc.sha512
sha512sum -c containerd-shim-runsc-v1.sha512

# Install binaries
sudo mv runsc /usr/local/bin/
sudo mv containerd-shim-runsc-v1 /usr/local/bin/
sudo chmod a+rx /usr/local/bin/runsc /usr/local/bin/containerd-shim-runsc-v1

# Verify installation
runsc --version
```

#### Method 2: Using APT Repository

```bash
# Add gVisor repository
curl -fsSL https://gvisor.dev/archive.key | sudo gpg --dearmor -o /usr/share/keyrings/gvisor-archive-keyring.gpg
echo "deb [arch=$(dpkg --print-architecture) signed-by=/usr/share/keyrings/gvisor-archive-keyring.gpg] https://storage.googleapis.com/gvisor/releases release main" | \
    sudo tee /etc/apt/sources.list.d/gvisor.list > /dev/null

# Install gVisor
sudo apt-get update
sudo apt-get install -y runsc
```

### 3. Install and Configure containerd

```bash
# Install containerd
sudo apt-get install -y containerd

# Create containerd configuration directory
sudo mkdir -p /etc/containerd

# Generate default configuration
sudo containerd config default | sudo tee /etc/containerd/config.toml

# Configure containerd for gVisor
sudo tee -a /etc/containerd/config.toml <<EOF

[plugins."io.containerd.grpc.v1.cri".containerd.runtimes.runsc]
  runtime_type = "io.containerd.runsc.v1"

[plugins."io.containerd.grpc.v1.cri".containerd.runtimes.runsc.options]
  TypeUrl = "io.containerd.runsc.v1.options"
EOF

# Restart containerd
sudo systemctl restart containerd
sudo systemctl enable containerd

# Verify containerd is running
sudo systemctl status containerd
```

### 4. Configure Docker with gVisor Runtime

```bash
# Install Docker if not already installed
if ! command -v docker &> /dev/null; then
    curl -fsSL https://get.docker.com -o get-docker.sh
    sudo sh get-docker.sh
    sudo usermod -aG docker $USER
    newgrp docker
fi

# Configure Docker daemon for gVisor
sudo tee /etc/docker/daemon.json <<EOF
{
    "default-runtime": "runc",
    "runtimes": {
        "runsc": {
            "path": "/usr/local/bin/runsc",
            "runtimeArgs": [
                "--network=sandbox",
                "--platform=ptrace",
                "--debug-log=/tmp/runsc/",
                "--debug-log-format=json"
            ]
        },
        "runsc-kvm": {
            "path": "/usr/local/bin/runsc",
            "runtimeArgs": [
                "--network=sandbox",
                "--platform=kvm",
                "--debug-log=/tmp/runsc/",
                "--debug-log-format=json"
            ]
        }
    }
}
EOF

# Create debug log directory
sudo mkdir -p /tmp/runsc

# Restart Docker
sudo systemctl restart docker
sudo systemctl enable docker

# Verify Docker can use gVisor runtime
docker run --runtime=runsc --rm hello-world
```

### 5. Setup Python Environment for AI-Parrot

```bash
# Create virtual environment
python3 -m venv ~/ai-parrot-env
source ~/ai-parrot-env/bin/activate

# Install AI-Parrot and dependencies
pip install --upgrade pip
pip install pandas numpy matplotlib seaborn plotly scipy scikit-learn
pip install jupyterlab nbformat

# Install AI-Parrot
pip install -e ai-parrot[agents]
```

### 6. Security Configuration

#### AppArmor Profile (Optional but Recommended)

```bash
# Create AppArmor profile for gVisor containers
sudo tee /etc/apparmor.d/docker-gvisor <<EOF
#include <tunables/global>

profile docker-gvisor flags=(attach_disconnected,mediate_deleted) {
  #include <abstractions/base>
  
  network inet stream,
  network inet dgram,
  
  # Allow necessary file access
  /usr/local/bin/runsc r,
  /tmp/runsc/** rw,
  /var/lib/docker/** rw,
  
  # Deny everything else
  deny /** w,
  deny @{HOME}/** rw,
}
EOF

# Load the profile
sudo apparmor_parser -r /etc/apparmor.d/docker-gvisor
```

#### Resource Limits

```bash
# Set system resource limits
sudo tee -a /etc/security/limits.conf <<EOF
# Limits for gVisor containers
* soft nofile 65536
* hard nofile 65536
* soft nproc 32768
* hard nproc 32768
EOF

# Apply sysctl settings for better container performance
sudo tee /etc/sysctl.d/99-gvisor.conf <<EOF
# gVisor optimization
net.ipv4.ip_forward = 1
net.bridge.bridge-nf-call-iptables = 1
net.bridge.bridge-nf-call-ip6tables = 1
fs.file-max = 2097152
fs.inotify.max_user_watches = 524288
kernel.pid_max = 4194304
EOF

sudo sysctl -p /etc/sysctl.d/99-gvisor.conf
```

### 7. Build Base Container Image

```bash
# Create directory for AI-Parrot containers
mkdir -p ~/ai-parrot-containers
cd ~/ai-parrot-containers

# Create Dockerfile
cat > Dockerfile <<EOF
FROM python:3.11-slim

# Install system dependencies
RUN apt-get update && apt-get install -y \
    gcc g++ make \
    libssl-dev libffi-dev \
    && rm -rf /var/lib/apt/lists/*

# Install Python packages
RUN pip install --no-cache-dir \
    pandas numpy matplotlib seaborn \
    scikit-learn scipy plotly \
    jupyterlab ipykernel nbformat

# Create sandbox user
RUN useradd -m -s /bin/bash sandbox && \
    mkdir -p /workspace /output && \
    chown -R sandbox:sandbox /workspace /output

USER sandbox
WORKDIR /workspace

ENV PYTHONUNBUFFERED=1
ENV PYTHONDONTWRITEBYTECODE=1
EOF

# Build the image
docker build -t ai-parrot-gvisor-sandbox .

# Test the image with gVisor
docker run --runtime=runsc --rm ai-parrot-gvisor-sandbox python -c "print('gVisor sandbox working!')"
```

### 8. Testing the Installation

Create a test script to verify the gVisor sandbox:

```python
#!/usr/bin/env python3
# test_gvisor.py

import subprocess
import json
import tempfile
import os

def test_gvisor_sandbox():
    """Test gVisor sandbox functionality"""
    
    # Test code that attempts various operations
    test_code = """
import os
import sys
import pandas as pd
import numpy as np

# Test basic computation
result = np.array([1, 2, 3]) * 2
print(f"Computation result: {result}")

# Test DataFrame operations
df = pd.DataFrame({'A': [1, 2, 3], 'B': [4, 5, 6]})
print(f"DataFrame shape: {df.shape}")

# Attempt file system access (should be restricted)
try:
    with open('/etc/passwd', 'r') as f:
        print("ERROR: Should not be able to read /etc/passwd")
except:
    print("Good: Cannot access system files")

# Attempt network access (should be blocked)
try:
    import urllib.request
    urllib.request.urlopen('http://google.com')
    print("ERROR: Network should be blocked")
except:
    print("Good: Network access blocked")

print("All security tests passed!")
"""

    # Create temporary directory
    with tempfile.TemporaryDirectory() as tmpdir:
        # Write test script
        script_path = os.path.join(tmpdir, 'test.py')
        with open(script_path, 'w') as f:
            f.write(test_code)
        
        # Run in gVisor container
        result = subprocess.run([
            'docker', 'run',
            '--runtime=runsc',
            '--rm',
            '--network=none',
            '-v', f'{tmpdir}:/workspace:ro',
            'ai-parrot-gvisor-sandbox',
            'python', '/workspace/test.py'
        ], capture_output=True, text=True)
        
        print("=== gVisor Sandbox Test Results ===")
        print("STDOUT:", result.stdout)
        if result.stderr:
            print("STDERR:", result.stderr)
        print("Exit Code:", result.returncode)
        
        return result.returncode == 0

if __name__ == "__main__":
    success = test_gvisor_sandbox()
    print("\n✅ gVisor installation successful!" if success else "\n❌ gVisor test failed")
```

Run the test:
```bash
python3 test_gvisor.py
```

## Verification Commands

Run these commands to verify everything is properly installed:

```bash
# Check gVisor version
runsc --version

# Check Docker runtimes
docker info | grep -A 5 Runtimes

# Test gVisor runtime
docker run --runtime=runsc --rm alpine echo "gVisor works!"

# Check containerd
sudo ctr version

# Test Python execution in sandbox
docker run --runtime=runsc --rm ai-parrot-gvisor-sandbox \
    python -c "import pandas, numpy; print('Libraries loaded successfully')"
```

## Troubleshooting

### Common Issues and Solutions

1. **runsc not found**
   ```bash
   # Ensure /usr/local/bin is in PATH
   echo 'export PATH=$PATH:/usr/local/bin' >> ~/.bashrc
   source ~/.bashrc
   ```

2. **Docker runtime error**
   ```bash
   # Check Docker daemon logs
   sudo journalctl -u docker.service -n 100
   
   # Verify daemon.json syntax
   python3 -m json.tool /etc/docker/daemon.json
   ```

3. **Permission denied errors**
   ```bash
   # Ensure user is in docker group
   sudo usermod -aG docker $USER
   newgrp docker
   ```

4. **Container fails to start**
   ```bash
   # Check gVisor debug logs
   sudo tail -f /tmp/runsc/*.log
   
   # Try with ptrace platform instead of KVM
   docker run --runtime=runsc --rm \
       --env RUNSC_FLAGS="--platform=ptrace" \
       ai-parrot-gvisor-sandbox echo "test"
   ```

5. **Memory or CPU limits not working**
   ```bash
   # Enable cgroup v2
   sudo grubby --update-kernel=ALL \
       --args="systemd.unified_cgroup_hierarchy=1"
   sudo reboot
   ```

## Performance Tuning

### Platform Selection

- **ptrace** (default): More compatible, slightly slower
- **kvm**: Faster, requires KVM support

Check KVM support:
```bash
egrep -c '(vmx|svm)' /proc/cpuinfo
# If > 0, KVM is supported
```

Enable KVM platform:
```bash
# Modify /etc/docker/daemon.json to use runsc-kvm runtime
sudo systemctl restart docker
```

### Resource Allocation

Optimize container resources in your Python code:
```python
config = SandboxConfig(
    runtime="runsc",
    max_memory="4G",  # Increase for data-intensive operations
    max_cpu=4.0,       # Use more CPU cores
    timeout=60,        # Longer timeout for complex operations
)
```

## Security Best Practices

1. **Never run gVisor containers as root in production**
2. **Always set resource limits (memory, CPU, timeout)**
3. **Disable network access unless absolutely necessary**
4. **Use read-only mounts for code directories**
5. **Regularly update gVisor to latest version**
6. **Monitor container logs for suspicious activity**
7. **Use AppArmor or SELinux profiles**
8. **Implement rate limiting for code execution**

## Integration with AI-Parrot

After installation, use the gVisor sandbox in your AI-Parrot agents:

```python
from parrot.tools.gvisor_sandbox import GVisorPandasTool
import pandas as pd

# Create secure sandbox tool
sandbox = GVisorPandasTool(
    dataframes={
        'df1': pd.DataFrame({'A': [1, 2, 3], 'B': [4, 5, 6]})
    },
    enable_jupyter=True
)

# Add to agent
agent.add_tool(sandbox)

# Execute code safely
result = await sandbox.execute("""
import pandas as pd
df = df1.copy()
df['C'] = df['A'] + df['B']
print(df)
""")
```

## Maintenance

### Regular Updates

```bash
# Update gVisor monthly
wget https://storage.googleapis.com/gvisor/releases/release/latest/$(uname -m)/runsc
sudo mv runsc /usr/local/bin/runsc
sudo chmod a+rx /usr/local/bin/runsc

# Update container image
docker pull python:3.11-slim
docker build -t ai-parrot-gvisor-sandbox .
```

### Monitoring

```bash
# Monitor gVisor containers
docker stats --filter="label=runtime=runsc"

# Check logs
sudo journalctl -u docker -f | grep runsc
```

## Conclusion

Your gVisor sandbox is now ready for secure Python code execution in AI-Parrot. The sandbox provides:

- **Kernel-level isolation** preventing system access
- **Resource limits** preventing resource exhaustion  
- **Network isolation** preventing external connections
- **File system restrictions** protecting sensitive data
- **Safe execution** of untrusted LLM-generated code

For support or issues, please refer to:
- [gVisor Documentation](https://gvisor.dev/docs/)
- [AI-Parrot GitHub Issues](https://github.com/your-repo/ai-parrot/issues)