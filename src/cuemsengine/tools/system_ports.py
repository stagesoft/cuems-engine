import subprocess
import re
from typing import Dict, Optional

def get_used_ports_with_pid(user: str = None) -> Dict[int, int]:
    """
    Recover all used ports using the 'ss' command.
    Returns a dictionary with PID as key and port as value.
    
    Args:
        user (str): The user to filter ports by
        If no user is provided, all used ports will be returned.

    Returns:
        Dict[int, int]: Dictionary mapping PID to port
        
    Example:
        >>> ports = get_used_ports_with_pid()
        >>> print(ports)
        {1234: 8080, 5678: 9090}
    """
    try:
        # Run 'ss -tulnp' to get all listening ports with process info
        result = subprocess.run(
            ['ss', '-tulnp'], 
            capture_output=True, 
            text=True, 
            check=True
        )
        
        # Parse the output to extract PIDs and ports
        pid_port_dict = {}
        pid = None
        port = None

        for line in result.stdout.strip().split('\n')[1:]:  # Skip header line
            if line.strip():
                if user and user not in line:
                    continue
                # Parse the ss output format
                parts = line.split()
                for part in parts:
                    if user and user not in part:
                        continue
                    if "pid=" in part:
                        pid_match = re.search(r'pid=(\d+)', part)
                        if pid_match:
                            pid = int(pid_match.group(1))
                            pid_port_dict[pid] = port
                    elif ":" in part:
                        try:
                            port = int(part.split(':')[-1])
                        except (ValueError, IndexError):
                            continue
                    else:
                        continue
                if pid and port:
                    pid_port_dict[pid] = port
                pid = None
                port = None
                            
        return pid_port_dict
        
    except subprocess.CalledProcessError as e:
        # Handle case where 'ss' command is not available or fails
        print(f"Warning: Could not execute 'ss' command: {e}")
        return {}
    except Exception as e:
        print(f"Error getting used ports: {e}")
        return {}


def get_port_by_pid(target_pid: int) -> Optional[int]:
    """
    Get the port used by a specific PID.
    
    Args:
        target_pid (int): The process ID to look up
        
    Returns:
        Optional[int]: The port number if found, None otherwise
        
    Example:
        >>> port = get_port_by_pid(1234)
        >>> print(port)
        8080
    """
    ports = get_used_ports_with_pid()
    return ports.get(target_pid)


def get_pid_by_port(target_port: int) -> Optional[int]:
    """
    Get the PID using a specific port.
    
    Args:
        target_port (int): The port number to look up
        
    Returns:
        Optional[int]: The process ID if found, None otherwise
        
    Example:
        >>> pid = get_pid_by_port(8080)
        >>> print(pid)
        1234
    """
    ports = get_used_ports_with_pid()
    # Reverse lookup: find PID by port
    for pid, port in ports.items():
        if port == target_port:
            return pid
    return None


def is_port_in_use(port: int) -> bool:
    """
    Check if a specific port is in use.
    
    Args:
        port (int): The port number to check
        
    Returns:
        bool: True if port is in use, False otherwise
        
    Example:
        >>> if is_port_in_use(8080):
        ...     print("Port 8080 is in use")
        ... else:
        ...     print("Port 8080 is available")
    """
    ports = get_used_ports_with_pid()
    return port in ports.values()
