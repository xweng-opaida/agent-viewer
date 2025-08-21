#!/usr/bin/env python3
import json
import os
import re
import socket
import subprocess
import sys
import threading
import asyncio
import websockets
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse


PROXIES = {}
LOCK = threading.Lock()
WEBSOCKET_SERVER = None


def find_free_tcp_port(preferred_start: int | None = None, preferred_end: int | None = None) -> int:
    if preferred_start is not None:
        # Try a range starting at preferred_start
        end_port = preferred_end if preferred_end is not None else preferred_start + 200
        for port in range(preferred_start, end_port):
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
                try:
                    s.bind(("127.0.0.1", port))
                    return port
                except OSError:
                    continue
    # Fallback: let OS pick
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def choose_display(start: int = 99, limit: int = 199) -> str:
    try:
        ps_out = subprocess.run(["ps", "-ef"], capture_output=True, text=True, check=True).stdout
    except Exception:
        ps_out = ""
    used = set(int(m.group(1)) for m in re.finditer(r"Xvfb\s+:(\d+)", ps_out))
    for n in range(start, limit + 1):
        if n not in used:
            return f":{n}"
    # Fallback if everything appears used
    return f":{start}"


async def websocket_proxy_handler(websocket):
    """Handle WebSocket connections and proxy to VNC servers"""
    try:
        # Get the path from the websocket request object
        path = websocket.request.path
        
        # Parse the path to get container ID: /vnc/{container_id}
        path_parts = path.split('/')
        if len(path_parts) < 3 or path_parts[1] != 'vnc':
            await websocket.close(1008, "Invalid path format. Use /vnc/{container_id}")
            return
        
        container_id = path_parts[2]
        
        with LOCK:
            if container_id not in PROXIES:
                await websocket.close(1008, f"Container {container_id} not found")
                return
            
            vnc_port = PROXIES[container_id]["vncPort"]
        
        print(f"DEBUG: WebSocket proxy connecting to VNC port {vnc_port}", file=sys.stderr)
        
        # Connect to the VNC server
        reader, writer = await asyncio.open_connection('localhost', vnc_port)
        
        # Create tasks for bidirectional data transfer
        async def forward_to_vnc():
            try:
                async for message in websocket:
                    if isinstance(message, bytes):
                        writer.write(message)
                    else:
                        writer.write(message.encode('utf-8'))
                    await writer.drain()
            except Exception as e:
                print(f"DEBUG: Error forwarding to VNC: {e}", file=sys.stderr)
            finally:
                try:
                    writer.close()
                    await writer.wait_closed()
                except:
                    pass
        
        async def forward_from_vnc():
            try:
                while True:
                    data = await reader.read(4096)
                    if not data:
                        break
                    await websocket.send(data)
            except Exception as e:
                print(f"DEBUG: Error forwarding from VNC: {e}", file=sys.stderr)
            finally:
                try:
                    await websocket.close()
                except:
                    pass
        
        # Start both forwarding tasks
        await asyncio.gather(
            forward_to_vnc(),
            forward_from_vnc(),
            return_exceptions=True
        )
        
    except Exception as e:
        print(f"DEBUG: WebSocket proxy error: {e}", file=sys.stderr)
        try:
            await websocket.close(1011, f"Internal error: {str(e)}")
        except:
            pass


def discover_existing_containers():
    """Discover all existing chrome-gui containers and their VNC ports"""
    try:
        # Find all running chrome-gui containers (only running ones)
        result = subprocess.run([
            "docker", "ps", "--filter", "ancestor=chrome-gui", "--filter", "status=running",
            "--format", "{{.ID}}"
        ], capture_output=True, text=True, check=True)
        
        container_ids = result.stdout.strip().split('\n') if result.stdout.strip() else []
        discovered = {}
        
        for container_id in container_ids:
            if not container_id:
                continue
                
            try:
                # Double-check container is actually running
                status_result = subprocess.run([
                    "docker", "inspect", container_id, "--format", "{{.State.Running}}"
                ], capture_output=True, text=True, timeout=2)
                
                if status_result.stdout.strip() != "true":
                    print(f"DEBUG: Container {container_id[:8]}... is not running, skipping", file=sys.stderr)
                    continue
                
                # Get container logs to find VNC port
                logs_result = subprocess.run([
                    "docker", "logs", container_id
                ], capture_output=True, text=True, timeout=5)
                
                # Look for VNC port in logs
                import re
                port_match = re.search(r"Listening for VNC connections on TCP port (\d+)", logs_result.stdout)
                if port_match:
                    vnc_port = int(port_match.group(1))
                    discovered[container_id] = {"vncPort": vnc_port}
                    print(f"DEBUG: Discovered existing container {container_id[:8]}... on VNC port {vnc_port}", file=sys.stderr)
                else:
                    print(f"DEBUG: Container {container_id[:8]}... has no VNC port in logs", file=sys.stderr)
                    
            except Exception as e:
                print(f"DEBUG: Could not get info for container {container_id[:8]}...: {e}", file=sys.stderr)
                
        return discovered
    except Exception as e:
        print(f"DEBUG: Could not discover existing containers: {e}", file=sys.stderr)
        return {}


def start_container_and_proxy():
    debug_port = find_free_tcp_port(9222)
    vnc_port = find_free_tcp_port(5900)
    display = choose_display()
    
    # Log the port assignment for debugging
    print(f"DEBUG: Using ports - debug:{debug_port}, vnc:{vnc_port}, display:{display}", file=sys.stderr)

    script_path = "/work1/opaida/docker-chrome-vnc/run-chrome-gui.sh"
    if not os.path.exists(script_path):
        raise RuntimeError(f"Launch script not found: {script_path}")

    # Run the container launch script; returns JSON
    result = subprocess.run([
        "/bin/bash", script_path, str(debug_port), str(vnc_port), display
    ], capture_output=True, text=True, check=True)

    try:
        payload = json.loads(result.stdout.strip())
    except json.JSONDecodeError as e:
        raise RuntimeError(f"Failed to parse launcher output: {result.stdout}\n{result.stderr}") from e

    container_id = payload.get("containerId")
    ws_endpoint = payload.get("wsEndpoint")
    if not container_id:
        raise RuntimeError("Launcher did not return containerId")

    # Wait for the new container's VNC server to start and find its specific port
    # The container script should tell us the actual port, but let's also detect it
    actual_vnc_port = None
    
    # First, try to get the port from the container logs
    try:
        import time
        time.sleep(1)  # Give the container a moment to start VNC
        logs_result = subprocess.run([
            "docker", "logs", container_id
        ], capture_output=True, text=True, timeout=5)
        
        # Look for "Listening for VNC connections on TCP port XXXX"
        import re
        port_match = re.search(r"Listening for VNC connections on TCP port (\d+)", logs_result.stdout)
        if port_match:
            actual_vnc_port = int(port_match.group(1))
            print(f"DEBUG: Found VNC port {actual_vnc_port} from container logs", file=sys.stderr)
    except Exception as e:
        print(f"DEBUG: Could not get port from container logs: {e}", file=sys.stderr)
    
    # Fallback: scan for newly opened ports
    if not actual_vnc_port:
        print("DEBUG: Scanning for new VNC port...", file=sys.stderr)
        for port in range(5900, 5920):  # Check a reasonable range
            try:
                with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                    s.settimeout(0.1)
                    if s.connect_ex(("localhost", port)) == 0:
                        # Check if this port wasn't in our existing proxies
                        port_in_use = any(meta.get("vncPort") == port for meta in PROXIES.values())
                        if not port_in_use:
                            actual_vnc_port = port
                            print(f"DEBUG: Found new VNC port {actual_vnc_port} by scanning", file=sys.stderr)
                            break
            except:
                pass
    
    # Final fallback to requested port
    if not actual_vnc_port:
        actual_vnc_port = vnc_port
        print(f"DEBUG: Using fallback VNC port {actual_vnc_port}", file=sys.stderr)
    else:
        print(f"DEBUG: Using detected VNC port {actual_vnc_port}", file=sys.stderr)
    
    with LOCK:
        PROXIES[container_id] = {"vncPort": actual_vnc_port}

    return {
        "containerId": container_id,
        "wsEndpoint": ws_endpoint,
        "vncPort": actual_vnc_port,
        "debugPort": debug_port,
        "display": display,
    }


class Handler(BaseHTTPRequestHandler):
    server_version = "VNCClientAPI/0.1"

    def _set_cors(self):
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type, Authorization")

    def do_OPTIONS(self):
        self.send_response(204)
        self._set_cors()
        self.end_headers()

    def do_GET(self):
        if self.path == "/health":
            self.send_response(200)
            self._set_cors()
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps({"ok": True}).encode())
            return
        if self.path == "/api/containers":
            # Refresh container list by discovering all existing containers
            discovered = discover_existing_containers()
            with LOCK:
                # Replace tracked containers with only currently running ones
                PROXIES.clear()
                PROXIES.update(discovered)
                data = {
                    cid: {"vncPort": meta["vncPort"]}
                    for cid, meta in PROXIES.items()
                }
            self.send_response(200)
            self._set_cors()
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps(data).encode())
            return
        if self.path == "/api/containers/cleanup":
            # Clean up stopped containers from our tracking
            try:
                result = subprocess.run([
                    "docker", "ps", "--filter", "ancestor=chrome-gui", 
                    "--format", "{{.ID}}"
                ], capture_output=True, text=True, check=True)
                
                running_ids = set(result.stdout.strip().split('\n')) if result.stdout.strip() else set()
                running_ids.discard('')  # Remove empty strings
                
                with LOCK:
                    # Remove containers that are no longer running
                    stopped_containers = [cid for cid in PROXIES.keys() if cid not in running_ids]
                    for cid in stopped_containers:
                        del PROXIES[cid]
                        print(f"DEBUG: Removed stopped container {cid[:8]}... from tracking", file=sys.stderr)
                
                self.send_response(200)
                self._set_cors()
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(json.dumps({"removed": stopped_containers}).encode())
                return
            except Exception as e:
                self.send_response(500)
                self._set_cors()
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(json.dumps({"error": str(e)}).encode())
                return

        # Serve static files from the web directory
        if self.path == "/" or self.path.startswith("/"):
            try:
                # Get the directory where this script is located
                script_dir = os.path.dirname(os.path.abspath(__file__))
                
                # Map root to index.html
                if self.path == "/":
                    file_path = os.path.join(script_dir, "web", "index.html")
                else:
                    file_path = os.path.join(script_dir, "web" + self.path)
                
                # Security: prevent directory traversal
                if ".." in file_path:
                    self.send_response(403)
                    self.end_headers()
                    return
                
                # Determine content type based on file extension
                content_type = "text/plain"
                if file_path.endswith(".html"):
                    content_type = "text/html"
                elif file_path.endswith(".js"):
                    content_type = "application/javascript"
                elif file_path.endswith(".css"):
                    content_type = "text/css"
                elif file_path.endswith(".png"):
                    content_type = "image/png"
                elif file_path.endswith(".jpg") or file_path.endswith(".jpeg"):
                    content_type = "image/jpeg"
                elif file_path.endswith(".ico"):
                    content_type = "image/x-icon"
                
                with open(file_path, "rb") as f:
                    content = f.read()
                
                self.send_response(200)
                self.send_header("Content-Type", content_type)
                self.end_headers()
                self.wfile.write(content)
                return
            except FileNotFoundError:
                # If file not found, serve index.html for SPA routing
                try:
                    script_dir = os.path.dirname(os.path.abspath(__file__))
                    index_path = os.path.join(script_dir, "web", "index.html")
                    with open(index_path, "rb") as f:
                        content = f.read()
                    self.send_response(200)
                    self.send_header("Content-Type", "text/html")
                    self.end_headers()
                    self.wfile.write(content)
                    return
                except FileNotFoundError:
                    pass
            except Exception as e:
                self.log_message(f"Error serving static file: {e}")

        self.send_response(404)
        self._set_cors()
        self.end_headers()

    def do_POST(self):
        if self.path.startswith("/api/containers/") and self.path.endswith("/stop"):
            # Stop a specific container
            container_id = self.path.split("/")[3]  # Extract container ID from path
            try:
                # First check if container exists and is running
                status_result = subprocess.run([
                    "docker", "inspect", container_id, "--format", "{{.State.Running}}"
                ], capture_output=True, text=True, timeout=2)
                
                if status_result.returncode == 0 and status_result.stdout.strip() == "true":
                    # Container exists and is running, stop it
                    subprocess.run(["docker", "stop", container_id], check=True, timeout=10)
                    print(f"DEBUG: Successfully stopped container {container_id[:8]}...", file=sys.stderr)
                else:
                    # Container doesn't exist or is already stopped
                    print(f"DEBUG: Container {container_id[:8]}... was already stopped or doesn't exist", file=sys.stderr)
                
                # Always remove from tracking regardless
                with LOCK:
                    if container_id in PROXIES:
                        del PROXIES[container_id]
                        print(f"DEBUG: Removed container {container_id[:8]}... from tracking", file=sys.stderr)
                
                self.send_response(200)
                self._set_cors()
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(json.dumps({"stopped": container_id}).encode())
                return
            except Exception as e:
                # Even if stopping failed, remove from tracking
                with LOCK:
                    if container_id in PROXIES:
                        del PROXIES[container_id]
                        print(f"DEBUG: Removed failed container {container_id[:8]}... from tracking", file=sys.stderr)
                
                self.send_response(200)  # Return success even if container was already gone
                self._set_cors()
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(json.dumps({"stopped": container_id, "note": "Container was already stopped or removed"}).encode())
                return
        if self.path == "/api/containers/start":
            try:
                self.log_message("Starting container...")
                resp = start_container_and_proxy()
                self.log_message(f"Container started: {resp['containerId']}")
                self.send_response(200)
                self._set_cors()
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(json.dumps(resp).encode())
            except subprocess.CalledProcessError as e:
                self.log_message(f"Launcher failed: {e.stdout} {e.stderr}")
                self.send_response(500)
                self._set_cors()
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(json.dumps({
                    "error": "launcher_failed",
                    "stdout": e.stdout,
                    "stderr": e.stderr,
                }).encode())
            except Exception as e:
                self.log_message(f"Unexpected error: {e}")
                self.send_response(500)
                self._set_cors()
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(json.dumps({"error": str(e)}).encode())
            return

        self.send_response(404)
        self._set_cors()
        self.end_headers()


async def start_websocket_server():
    """Start the WebSocket proxy server"""
    global WEBSOCKET_SERVER
    WEBSOCKET_SERVER = await websockets.serve(
        websocket_proxy_handler, 
        "127.0.0.1", 
        8124  # WebSocket server on port 8124
    )
    print(f"WebSocket proxy server listening on ws://127.0.0.1:8124", file=sys.stderr)
    await WEBSOCKET_SERVER.wait_closed()


def main():
    host = os.environ.get("API_HOST", "127.0.0.1")
    port = int(os.environ.get("API_PORT", "8123"))
    
    # Discover existing containers on startup
    print("DEBUG: Discovering existing containers...", file=sys.stderr)
    discovered = discover_existing_containers()
    with LOCK:
        PROXIES.update(discovered)
    print(f"DEBUG: Found {len(discovered)} existing containers", file=sys.stderr)
    
    # Start WebSocket server in a separate thread
    def run_websocket_server():
        asyncio.run(start_websocket_server())
    
    websocket_thread = threading.Thread(target=run_websocket_server, daemon=True)
    websocket_thread.start()
    
    httpd = ThreadingHTTPServer((host, port), Handler)
    print(f"API listening on http://{host}:{port}", file=sys.stderr)
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()


