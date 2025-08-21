# Agent Viewer

A web-based VNC client for managing and accessing Docker containers running agent environments with desktop GUI. This system provides seamless browser-to-container desktop sharing without requiring VNC client software or port forwarding.

## Features

- 🖥️ **Web-based VNC Client**: Access agent containers directly in your browser
- 🐳 **Docker Container Management**: Start, stop, and manage multiple agent containers
- 🔄 **Automatic Connection**: No manual URL or credential entry required
- 🔒 **Interaction Control**: Toggle between read-only and interactive modes
- 🌐 **Multi-Container Support**: Run and switch between multiple agent sessions
- 📱 **Responsive Design**: Clean, modern UI that works on desktop and mobile
- ⚡ **Real-time Switching**: Instantly switch between containers without page refresh

## Architecture

```
Browser (localhost:8001)
    ↓ HTTP API calls
Backend API Server (localhost:8123)
    ↓ Docker commands
Chrome Containers (chrome-gui image)
    ↓ VNC protocol (ports 5900+)
WebSocket Proxy (localhost:8124)
    ↓ WebSocket connection
Browser noVNC Client
```

## Quick Start

### Prerequisites

- Docker with `chrome-gui` image available (for agent environments)
- Python 3.8+ with pip
- Chrome container launch script at `/work1/opaida/docker-chrome-vnc/run-chrome-gui.sh`

### Installation

1. **Clone or navigate to the project directory:**
   ```bash
   cd /work1/opaida/vnc-client
   ```

2. **Install Python dependencies:**
   ```bash
   python3 -m pip install --user websockets
   ```

3. **Start the server:**
   ```bash
   # Start the API server, WebSocket proxy, and web client
   python3 server.py
   ```

4. **Open your browser:**
   ```
   http://localhost:8123
   ```

## Usage

### Starting Your First Container

1. Open the web interface at `http://localhost:8123`
2. Click **"Start Container"** to create a new agent session
3. The system will automatically:
   - Start a Docker container with agent environment
   - Set up VNC server
   - Create WebSocket proxy
   - Connect you to the desktop

### Managing Multiple Containers

- **Create More**: Click "Start Container" multiple times for additional agent sessions
- **Switch Between**: Click any container button to instantly switch to that desktop
- **Stop Containers**: Click the red "Stop" button next to any container
- **Refresh List**: Click "Refresh Containers" to update the container list

### Interaction Modes

- **🔒 Read Only** (default): View the desktop but cannot interact
- **🖱️ Interactive**: Full mouse and keyboard control
- **Toggle Anytime**: Click the interaction button to switch modes instantly

## Container Management

### Container List

The interface shows all running containers with:
- Container ID (first 8 characters)
- VNC port number
- Connect button (click to switch to that container)
- Stop button (click to terminate the container)

### Automatic Discovery

The system automatically discovers:
- Existing containers when the server starts
- New containers as they're created
- Stopped containers (removes them from the list)

## Configuration

### Default Ports

- **Web Client & API Server**: 8123 (unified server)
- **WebSocket Proxy**: 8124
- **Container VNC Ports**: 5900+ (auto-assigned)
- **Container Debug Ports**: 9222+ (auto-assigned)

### Environment Variables

```bash
# Optional: Override default API server settings
export API_HOST=127.0.0.1  # Default: 127.0.0.1
export API_PORT=8123       # Default: 8123
```

### Container Settings

- **Default VNC Password**: `hyperaccs`
- **Display Numbers**: :99+ (auto-assigned)
- **Container Isolation**: Each container uses isolated `/tmp` and display

## API Reference

### HTTP Endpoints

- `GET /health` - Server health check
- `GET /api/containers` - List all running containers
- `POST /api/containers/start` - Start a new container
- `POST /api/containers/{id}/stop` - Stop a specific container
- `GET /api/containers/cleanup` - Clean up stopped containers

### WebSocket Endpoint

- `ws://localhost:8124/vnc/{containerId}` - VNC connection proxy

For detailed API documentation, see [API_DOCUMENTATION.md](API_DOCUMENTATION.md).

## Troubleshooting

### Common Issues

**"No containers running" after starting containers:**
- Check if Docker is running: `docker ps`
- Verify the chrome-gui image exists: `docker images | grep chrome-gui`
- Check server logs for error messages

**Grey screen when connecting to container:**
- Wait a few seconds for the container to fully start
- Try refreshing the container list
- Check if the container is still running: `docker ps`

**WebSocket connection failed:**
- Ensure the API server is running on port 8123
- Check if port 8124 is available for WebSocket proxy
- Verify no firewall is blocking the connections

**Container won't start:**
- Check available system resources (memory, disk space)
- Verify the launch script exists and is executable
- Check Docker daemon status: `systemctl status docker`

### Debug Mode

Enable detailed logging by checking the server console output:
```bash
python3 server.py
# Look for DEBUG messages showing container discovery and connections
```

### Port Conflicts

If default ports are in use, modify the startup commands:
```bash
# Use different ports
API_PORT=8124 python3 server.py
python3 -m http.server 8002 --directory web
```

## Development

### Project Structure

```
/work1/opaida/vnc-client/
├── server.py              # Backend API and WebSocket proxy
├── web/
│   ├── index.html         # Frontend web client
│   └── vendor/noVNC/      # Vendored noVNC library
├── README.md              # This file
└── API_DOCUMENTATION.md   # Detailed API reference
```

### Key Components

- **Backend Server**: Python HTTP server with WebSocket proxy
- **Frontend Client**: HTML/JavaScript using noVNC library
- **Container Management**: Docker integration for Chrome containers
- **WebSocket Proxy**: Bridges browser WebSocket to VNC TCP connections

### Adding Features

1. **Backend Changes**: Modify `server.py` for new API endpoints
2. **Frontend Changes**: Update `web/index.html` for UI improvements
3. **Container Integration**: Extend Docker container management

## Security Notes

⚠️ **Development Setup**: This system is designed for local development and testing.

**Security Considerations:**
- All services bind to localhost only
- No authentication implemented
- CORS allows all origins
- Containers run with default privileges

**For Production Use:**
- Add proper authentication
- Implement HTTPS/WSS
- Restrict CORS origins
- Use container security best practices
- Add network isolation

## Contributing

1. Fork the repository
2. Create a feature branch
3. Make your changes
4. Test with multiple containers
5. Submit a pull request

## License

This project is for development and testing purposes. Please ensure compliance with Docker and noVNC licensing terms.

## Support

For issues and questions:
1. Check the troubleshooting section above
2. Review server logs for error messages
3. Verify Docker container status
4. Check API documentation for endpoint details

---

**Happy agent viewing! 🚀**
