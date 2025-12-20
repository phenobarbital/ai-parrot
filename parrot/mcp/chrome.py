import os
import subprocess
import time
import socket
import logging
import requests
from typing import Optional
from pathlib import Path


class ChromeManager:
    """Manages a headless Chrome instance for MCP tools."""

    def __init__(self, port: int = 9222, logger: Optional[logging.Logger] = None):
        self.port = port
        self.logger = logger or logging.getLogger("ChromeManager")
        self.process: Optional[subprocess.Popen] = None

    def is_port_open(self, host: str, port: int) -> bool:
        """Check if a port is open."""
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.settimeout(1)
            return s.connect_ex((host, port)) == 0

    def is_chrome_running(self) -> bool:
        """Check if Chrome is running and responding on the debugging port."""
        if not self.is_port_open("127.0.0.1", self.port):
            return False
        
        try:
            response = requests.get(f"http://127.0.0.1:{self.port}/json/version", timeout=1)
            return response.status_code == 200
        except requests.RequestException:
            return False

    def start(self) -> bool:
        """Start headless Chrome if not already running."""
        if self.is_chrome_running():
            self.logger.info(f"Chrome is already running on port {self.port}")
            return True

        self.logger.info("Starting headless Chrome...")
        
        # Determine Chrome executable
        chrome_bins = [
            "google-chrome",
            "google-chrome-stable",
            "chromium",
            "chromium-browser",
            "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome" # MacOS
        ]
        
        chrome_bin = None
        for bin_name in chrome_bins:
            if shutil_which(bin_name):
                chrome_bin = bin_name
                break
        
        if not chrome_bin:
             # Fallback check for manual paths if which fails (common on some setups)
             pass 

        # Build command
        # Using array format for subprocess
        cmd = [
            "google-chrome", # Defaulting to google-chrome, relying on path
            "--headless=new",
            f"--remote-debugging-port={self.port}",
            "--disable-gpu",
            "--no-sandbox",
            "--disable-dev-shm-usage",
            "--remote-allow-origins=*"
        ]

        try:
            # check if google-chrome exists
            try:
                subprocess.run(["google-chrome", "--version"], capture_output=True, check=True)
            except (subprocess.CalledProcessError, FileNotFoundError):
                # Try finding valid binary
                found = False
                import shutil
                for b in ["google-chrome-stable", "chromium", "chromium-browser"]:
                    if shutil.which(b):
                        cmd[0] = b
                        found = True
                        break
                if not found:
                     self.logger.warning("Could not find chrome binary in PATH. Assuming 'google-chrome'.")

            self.process = subprocess.Popen(
                cmd,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                start_new_session=True # Detach from parent
            )
            
            # Wait for it to come up
            for _ in range(10):
                time.sleep(1)
                if self.is_chrome_running():
                    self.logger.info("Chrome started successfully.")
                    return True
            
            self.logger.error("Timeout waiting for Chrome to start.")
            return False
            
        except Exception as e:
            self.logger.error(f"Failed to start Chrome: {e}")
            return False

    def stop(self):
        """Stop the managed Chrome process."""
        if self.process:
            self.logger.info("Stopping Chrome process...")
            self.process.terminate()
            try:
                self.process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self.process.kill()
            self.process = None

def shutil_which(pgm):
    import shutil
    return shutil.which(pgm)
