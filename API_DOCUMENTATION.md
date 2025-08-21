# Agent Viewer API Documentation

## Overview

The Agent Viewer system provides a web-based interface for managing and connecting to Docker containers running agent environments with VNC access. The system consists of:

- **Backend API Server**: Python HTTP server on port 8123
- **WebSocket Proxy Server**: WebSocket server on port 8124 for VNC connections
- **Frontend Web Client**: Static HTML/JS client served on port 8123

## Architecture

```
Browser (localhost:8123) 
    ↓ HTTP API calls
Backend API (localhost:8123)
    ↓ Docker commands
Docker Containers (chrome-gui)
    ↓ VNC protocol (ports 5900+)
WebSocket Proxy (localhost:8124)
    ↓ WebSocket
Browser noVNC Client
```

## API Endpoints

### 1. Health Check

**GET** `/health`

Returns server health status.

**Response:**
```json
{
  "ok": true
}
```

**Status Codes:**
- `200 OK`: Server is healthy

---

### 2. List Containers

**GET** `/api/containers`

Discovers and returns all running chrome-gui containers with their VNC ports.

**Response:**
```json
{
  "cc920900fc05": {
    "vncPort": 5908
  },
  "ca38513d7624": {
    "vncPort": 5900
  }
}
```

**Behavior:**
- Scans for all running `chrome-gui` containers
- Extracts VNC port from container logs
- Only returns containers that are actually running
- Refreshes the internal container tracking

**Status Codes:**
- `200 OK`: Successfully retrieved containers

---

### 3. Start New Container

**POST** `/api/containers/start`

Starts a new chrome-gui container and returns connection details.

**Response:**
```json
{
  "containerId": "f7679df5df405f918d2048bce604e7e76a138790b6661343f94d2ad96a646896",
  "wsEndpoint": "ws://localhost:9226/devtools/browser/76f9f2ef-1e49-4c2c-b2c9-a090e2a13e93",
  "vncPort": 5904,
  "debugPort": 9226,
  "display": ":103"
}
```

**Process:**
1. Allocates free ports for debug, VNC, and display
2. Runs `/work1/opaida/docker-chrome-vnc/run-chrome-gui.sh`
3. Waits for container to start VNC server
4. Detects actual VNC port from container logs
5. Adds container to tracking system

**Status Codes:**
- `200 OK`: Container started successfully
- `500 Internal Server Error`: Container start failed

**Error Response:**
```json
{
  "error": "launcher_failed",
  "stdout": "container output",
  "stderr": "error output"
}
```

---

### 4. Stop Container

**POST** `/api/containers/{containerId}/stop`

Stops a specific container and removes it from tracking.

**Parameters:**
- `containerId`: Full Docker container ID

**Response:**
```json
{
  "stopped": "f7679df5df405f918d2048bce604e7e76a138790b6661343f94d2ad96a646896"
}
```

**Behavior:**
- Checks if container exists and is running
- Stops container if running
- Removes from internal tracking
- Returns success even if container was already stopped

**Status Codes:**
- `200 OK`: Container stopped or was already stopped

**Alternative Response (already stopped):**
```json
{
  "stopped": "f7679df5df405f918d2048bce604e7e76a138790b6661343f94d2ad96a646896",
  "note": "Container was already stopped or removed"
}
```

---

### 5. Cleanup Stopped Containers

**GET** `/api/containers/cleanup`

Removes stopped containers from internal tracking.

**Response:**
```json
{
  "removed": [
    "f7679df5df405f918d2048bce604e7e76a138790b6661343f94d2ad96a646896",
    "e3d448e290b2e38a735f0745847d847dfdd822ea8a64d1fefc4e344e67043101"
  ]
}
```

**Status Codes:**
- `200 OK`: Cleanup completed successfully
- `500 Internal Server Error`: Cleanup failed

---

## WebSocket Proxy

### VNC Connection

**WebSocket** `ws://localhost:8124/vnc/{containerId}`

Establishes a WebSocket connection to a specific container's VNC server.

**Parameters:**
- `containerId`: Full Docker container ID

**Protocol:**
- Proxies raw VNC/RFB protocol over WebSocket
- Handles bidirectional data transfer
- Automatically connects to container's VNC port

**Connection Flow:**
1. Client connects to WebSocket endpoint
2. Server validates container ID exists in tracking
3. Server opens TCP connection to container's VNC port
4. Bidirectional proxy between WebSocket and VNC

**Error Responses:**
- `1008`: Invalid path format or container not found
- `1011`: Internal server error

---

## Frontend Integration

### Container Management

The web client provides these features:

1. **Container List**: Displays all running containers
2. **Start Container**: Creates new containers
3. **Connect**: Connects to container VNC
4. **Stop**: Stops specific containers
5. **Interaction Toggle**: Switches between read-only and interactive modes

### WebSocket URLs

Containers are accessed via:
```
ws://localhost:8124/vnc/{containerId}
```

### Default Credentials

All containers use the default VNC password: `hyperaccs`

---

## Container Lifecycle

### 1. Container Creation
```
POST /api/containers/start
→ Docker container starts
→ VNC server starts on allocated port
→ Container added to tracking
```

### 2. Connection
```
Browser connects to ws://localhost:8124/vnc/{containerId}
→ WebSocket proxy connects to container VNC port
→ noVNC client renders desktop
```

### 3. Interaction Modes
- **Read Only**: `rfb.viewOnly = true` (default)
- **Interactive**: `rfb.viewOnly = false` (user can interact)

### 4. Container Termination
```
POST /api/containers/{containerId}/stop
→ Docker container stops
→ Container removed from tracking
→ WebSocket connections closed
```

---

## Error Handling

### Common Error Scenarios

1. **Container Start Failure**
   - Port conflicts
   - Docker daemon issues
   - Script execution errors

2. **WebSocket Connection Issues**
   - Container not running
   - VNC server not ready
   - Network connectivity problems

3. **Container Discovery Issues**
   - Docker command failures
   - Container log parsing errors
   - Permission issues

### Logging

Server provides detailed debug logging:
```
DEBUG: Discovering existing containers...
DEBUG: Found VNC port 5908 from container logs
DEBUG: WebSocket proxy connecting to VNC port 5908
```

---

## Configuration

### Environment Variables

- `API_HOST`: API server host (default: `127.0.0.1`)
- `API_PORT`: API server port (default: `8123`)

### Dependencies

- Docker with `chrome-gui` image
- Python packages: `websockets`, `asyncio`
- Chrome container script: `/work1/opaida/docker-chrome-vnc/run-chrome-gui.sh`

### Port Allocation

- **API Server**: 8123
- **WebSocket Proxy**: 8124
- **Web Client**: 8001 (via separate HTTP server)
- **Container Debug Ports**: 9222+
- **Container VNC Ports**: 5900+
- **Container Displays**: :99+

---

## Security Considerations

1. **Network Binding**: All services bind to localhost only
2. **CORS**: API allows all origins for development
3. **Authentication**: No authentication implemented (development setup)
4. **Container Isolation**: Each container uses isolated `/tmp` and display

---

## Development Notes

### Container Discovery Logic

1. Query Docker for running `chrome-gui` containers
2. Verify each container is actually running
3. Parse container logs for VNC port
4. Update internal tracking dictionary

### WebSocket Proxy Implementation

- Async/await based proxy using Python `websockets` library
- Handles both text and binary WebSocket messages
- Automatic cleanup on connection close
- Error handling for VNC server disconnections

### Frontend State Management

- Container list refreshes on API calls
- Smooth switching between containers
- Proper VNC connection cleanup
- Real-time interaction mode toggling

