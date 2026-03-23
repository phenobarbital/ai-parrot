"""Read-only system health monitoring tool.

Exposes host-level metrics (CPU, RAM, disk, network, processes, Docker
containers) to the LLM without any write or exec capabilities.

Security guarantees:
- Uses psutil Python API, never shell commands (except read-only ``docker ps``).
- Reports process *counts* and top consumers by name only — no PIDs exposed.
- Reports open file descriptor *count*, never file paths or contents.
- Does not expose environment variables or secrets.
- Docker: only ``docker ps`` (list running containers), no exec/run/stop.

Example:
    from parrot.tools.system_health import SystemHealthTool

    tool = SystemHealthTool()
    result = await tool.execute(category="all")
    print(result.result)
"""

import asyncio
import platform
import time
from enum import Enum
from typing import Any, Dict, List

import psutil
from pydantic import Field

from ..abstract import AbstractTool, AbstractToolArgsSchema, ToolResult


class HealthCategory(str, Enum):
    """Available health-check categories."""

    ALL = "all"
    CPU = "cpu"
    MEMORY = "memory"
    DISK = "disk"
    NETWORK = "network"
    PROCESSES = "processes"
    SYSTEM = "system"
    DOCKER = "docker"
    GPU = "gpu"


class SystemHealthArgs(AbstractToolArgsSchema):
    """Arguments for the system health tool."""

    category: HealthCategory = Field(
        default=HealthCategory.ALL,
        description=(
            "Category of health metrics to retrieve. "
            "Use 'all' for a full snapshot, or pick a specific category: "
            "cpu, memory, disk, network, processes, system, docker, gpu."
        ),
    )


class SystemHealthTool(AbstractTool):
    """Read-only system health monitor.

    Returns a structured snapshot of host metrics so the agent can
    reason about resource usage, capacity, and running services
    without any ability to modify the system.

    Categories:
    - **cpu**: core count, per-core and average usage, load averages.
    - **memory**: total / available / used RAM and swap.
    - **disk**: per-partition usage (mount, total, used, free, percent).
    - **network**: per-interface bytes sent/received, packets, errors.
    - **processes**: total count, top 10 by CPU and top 10 by memory (name only).
    - **system**: hostname, platform, uptime, open-fd count, thread count.
    - **docker**: list of running containers (name, image, status, ports).
    - **gpu**: per-GPU utilization, temperature, VRAM usage (NVIDIA via pynvml, PyTorch fallback).
    """

    name: str = "system_health"
    description: str = (
        "Retrieve read-only system health metrics: CPU, memory, disk, "
        "network, processes, Docker containers, and GPU. "
        "Use the 'category' argument to request a specific section or 'all'."
    )
    args_schema: type[AbstractToolArgsSchema] = SystemHealthArgs

    # ── core execution ──────────────────────────────────────────

    async def _execute(self, **kwargs: Any) -> ToolResult:
        """Collect and return health metrics for the requested category."""
        category = kwargs.get("category", HealthCategory.ALL)
        if isinstance(category, str):
            category = HealthCategory(category)

        collectors = {
            HealthCategory.CPU: self._collect_cpu,
            HealthCategory.MEMORY: self._collect_memory,
            HealthCategory.DISK: self._collect_disk,
            HealthCategory.NETWORK: self._collect_network,
            HealthCategory.PROCESSES: self._collect_processes,
            HealthCategory.SYSTEM: self._collect_system,
            HealthCategory.DOCKER: self._collect_docker,
            HealthCategory.GPU: self._collect_gpu,
        }

        if category == HealthCategory.ALL:
            data: Dict[str, Any] = {}
            for cat, fn in collectors.items():
                try:
                    data[cat.value] = await self._safe_collect(fn)
                except Exception as exc:
                    data[cat.value] = {"error": str(exc)}
            return ToolResult(
                result=data,
                metadata={"category": "all"},
            )

        fn = collectors[category]
        result = await self._safe_collect(fn)
        return ToolResult(
            result=result,
            metadata={"category": category.value},
        )

    async def _safe_collect(self, fn):
        """Run a collector; if it's sync, offload to the default executor."""
        if asyncio.iscoroutinefunction(fn):
            return await fn()
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(None, fn)

    # ── collectors (all read-only) ──────────────────────────────

    def _collect_cpu(self) -> Dict[str, Any]:
        """CPU core count, per-core usage, average, and load averages."""
        per_core = psutil.cpu_percent(interval=0.5, percpu=True)
        return {
            "physical_cores": psutil.cpu_count(logical=False),
            "logical_cores": psutil.cpu_count(logical=True),
            "usage_per_core_pct": per_core,
            "usage_avg_pct": round(sum(per_core) / len(per_core), 1) if per_core else 0.0,
            "load_avg_1m_5m_15m": list(psutil.getloadavg()),
        }

    def _collect_memory(self) -> Dict[str, Any]:
        """RAM and swap usage."""
        vm = psutil.virtual_memory()
        sw = psutil.swap_memory()
        return {
            "ram": {
                "total_gb": round(vm.total / (1024**3), 2),
                "available_gb": round(vm.available / (1024**3), 2),
                "used_gb": round(vm.used / (1024**3), 2),
                "percent": vm.percent,
            },
            "swap": {
                "total_gb": round(sw.total / (1024**3), 2),
                "used_gb": round(sw.used / (1024**3), 2),
                "percent": sw.percent,
            },
        }

    def _collect_disk(self) -> List[Dict[str, Any]]:
        """Per-partition disk usage."""
        partitions = []
        for part in psutil.disk_partitions(all=False):
            try:
                usage = psutil.disk_usage(part.mountpoint)
            except PermissionError:
                continue
            partitions.append({
                "device": part.device,
                "mountpoint": part.mountpoint,
                "fstype": part.fstype,
                "total_gb": round(usage.total / (1024**3), 2),
                "used_gb": round(usage.used / (1024**3), 2),
                "free_gb": round(usage.free / (1024**3), 2),
                "percent": usage.percent,
            })
        return partitions

    def _collect_network(self) -> Dict[str, Any]:
        """Per-interface byte/packet counters."""
        counters = psutil.net_io_counters(pernic=True)
        result: Dict[str, Any] = {}
        for iface, stats in counters.items():
            result[iface] = {
                "bytes_sent_mb": round(stats.bytes_sent / (1024**2), 2),
                "bytes_recv_mb": round(stats.bytes_recv / (1024**2), 2),
                "packets_sent": stats.packets_sent,
                "packets_recv": stats.packets_recv,
                "errors_in": stats.errin,
                "errors_out": stats.errout,
            }
        return result

    def _collect_processes(self) -> Dict[str, Any]:
        """Process count and top consumers (name only, no PIDs)."""
        procs: List[Dict[str, Any]] = []
        for p in psutil.process_iter(["name", "cpu_percent", "memory_percent"]):
            try:
                info = p.info
                procs.append({
                    "name": info.get("name", "unknown"),
                    "cpu_pct": info.get("cpu_percent", 0.0) or 0.0,
                    "mem_pct": round(info.get("memory_percent", 0.0) or 0.0, 2),
                })
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                continue

        top_cpu = sorted(procs, key=lambda x: x["cpu_pct"], reverse=True)[:10]
        top_mem = sorted(procs, key=lambda x: x["mem_pct"], reverse=True)[:10]

        return {
            "total_count": len(procs),
            "top_by_cpu": top_cpu,
            "top_by_memory": top_mem,
        }

    def _collect_system(self) -> Dict[str, Any]:
        """Hostname, platform, uptime, fd/thread counts."""
        boot = psutil.boot_time()
        uptime_secs = time.time() - boot
        hours, remainder = divmod(int(uptime_secs), 3600)
        minutes, seconds = divmod(remainder, 60)

        # Open file descriptor count (Linux)
        try:
            open_fds = len(psutil.Process().open_files())
        except (psutil.AccessDenied, AttributeError):
            open_fds = None

        return {
            "hostname": platform.node(),
            "platform": platform.platform(),
            "python_version": platform.python_version(),
            "uptime": f"{hours}h {minutes}m {seconds}s",
            "uptime_seconds": int(uptime_secs),
            "open_file_descriptors": open_fds,
            "total_threads": psutil.Process().num_threads(),
            "cpu_count_logical": psutil.cpu_count(logical=True),
        }

    async def _collect_docker(self) -> Dict[str, Any]:
        """List running Docker containers (read-only via ``docker ps``)."""
        try:
            proc = await asyncio.create_subprocess_exec(
                "docker", "ps", "--format",
                '{"name":"{{.Names}}","image":"{{.Image}}",'
                '"status":"{{.Status}}","ports":"{{.Ports}}"}',
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, stderr = await asyncio.wait_for(
                proc.communicate(), timeout=10.0
            )
        except FileNotFoundError:
            return {"available": False, "reason": "docker CLI not found"}
        except asyncio.TimeoutError:
            return {"available": False, "reason": "docker ps timed out"}
        except Exception as exc:
            return {"available": False, "reason": str(exc)}

        if proc.returncode != 0:
            err = stderr.decode(errors="replace").strip()
            return {"available": False, "reason": err or "docker ps failed"}

        import json as _json

        containers: List[Dict[str, str]] = []
        for line in stdout.decode(errors="replace").strip().splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                containers.append(_json.loads(line))
            except _json.JSONDecodeError:
                continue

        return {
            "available": True,
            "running_count": len(containers),
            "containers": containers,
        }

    def _collect_gpu(self) -> Dict[str, Any]:
        """GPU utilization, temperature, and VRAM usage.

        Attempts detection in order:
        1. pynvml (NVIDIA Management Library) — most complete
        2. torch.cuda (PyTorch) — VRAM only, no utilization/temperature
        3. Falls back gracefully if no GPU is detected
        """
        # Attempt 1: NVIDIA Management Library (full metrics)
        try:
            import pynvml

            pynvml.nvmlInit()
            driver_version = pynvml.nvmlSystemGetDriverVersion()
            device_count = pynvml.nvmlDeviceGetCount()

            gpus: List[Dict[str, Any]] = []
            for i in range(device_count):
                handle = pynvml.nvmlDeviceGetHandleByIndex(i)
                name = pynvml.nvmlDeviceGetName(handle)
                if isinstance(name, bytes):
                    name = name.decode("utf-8")

                mem_info = pynvml.nvmlDeviceGetMemoryInfo(handle)

                gpu_data: Dict[str, Any] = {
                    "index": i,
                    "name": name,
                    "vram_total_mb": round(mem_info.total / (1024**2)),
                    "vram_used_mb": round(mem_info.used / (1024**2)),
                    "vram_free_mb": round(mem_info.free / (1024**2)),
                    "vram_percent": round(
                        mem_info.used / mem_info.total * 100, 1
                    ) if mem_info.total > 0 else 0.0,
                }

                # Utilization rates (may not be available on all GPUs)
                try:
                    util = pynvml.nvmlDeviceGetUtilizationRates(handle)
                    gpu_data["gpu_utilization_pct"] = util.gpu
                    gpu_data["memory_utilization_pct"] = util.memory
                except pynvml.NVMLError:
                    gpu_data["gpu_utilization_pct"] = None
                    gpu_data["memory_utilization_pct"] = None

                # Temperature
                try:
                    temp = pynvml.nvmlDeviceGetTemperature(
                        handle, pynvml.NVML_TEMPERATURE_GPU
                    )
                    gpu_data["temperature_c"] = temp
                except pynvml.NVMLError:
                    gpu_data["temperature_c"] = None

                # Power usage
                try:
                    power_mw = pynvml.nvmlDeviceGetPowerUsage(handle)
                    gpu_data["power_watts"] = round(power_mw / 1000, 1)
                except pynvml.NVMLError:
                    gpu_data["power_watts"] = None

                gpus.append(gpu_data)

            pynvml.nvmlShutdown()

            return {
                "available": True,
                "source": "pynvml",
                "driver_version": driver_version,
                "device_count": device_count,
                "gpus": gpus,
            }

        except ImportError:
            pass  # pynvml not installed, try next
        except Exception:
            pass  # NVML init failed (no NVIDIA driver), try next

        # Attempt 2: PyTorch CUDA (VRAM only, no utilization/temp)
        try:
            import torch

            if torch.cuda.is_available():
                device_count = torch.cuda.device_count()
                gpus = []
                for i in range(device_count):
                    props = torch.cuda.get_device_properties(i)
                    mem_alloc = torch.cuda.memory_allocated(i)
                    mem_reserved = torch.cuda.memory_reserved(i)
                    total = props.total_mem

                    gpus.append({
                        "index": i,
                        "name": props.name,
                        "vram_total_mb": round(total / (1024**2)),
                        "vram_allocated_mb": round(mem_alloc / (1024**2)),
                        "vram_reserved_mb": round(mem_reserved / (1024**2)),
                        "vram_free_mb": round(
                            (total - mem_reserved) / (1024**2)
                        ),
                        "vram_percent": round(
                            mem_reserved / total * 100, 1
                        ) if total > 0 else 0.0,
                        "gpu_utilization_pct": None,
                        "temperature_c": None,
                    })

                return {
                    "available": True,
                    "source": "torch.cuda",
                    "driver_version": None,
                    "device_count": device_count,
                    "gpus": gpus,
                }

        except ImportError:
            pass  # PyTorch not installed
        except Exception:
            pass  # CUDA not available

        return {
            "available": False,
            "reason": (
                "No GPU detected. Install pynvml (pip install pynvml) for "
                "NVIDIA GPUs, or ensure PyTorch with CUDA is available."
            ),
        }
