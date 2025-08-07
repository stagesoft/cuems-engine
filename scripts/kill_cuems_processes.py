#!/usr/bin/env python3
"""
CUEMS Process Killer Utility

This script helps kill stubborn CUEMS processes that can't be killed with regular methods.
It uses escalating strategies to terminate processes and their children.
"""

import os
import sys
import signal
import subprocess
import psutil
import time
from pathlib import Path

class CuemsProcessKiller:
    """Utility to kill CUEMS-related processes"""
    
    CUEMS_PATTERNS = [
        'cuems',
        'pytest.*cuems',
        'python.*cuems',
        'audioplayer-cuems',
        'videoplayer-cuems', 
        'dmxplayer-cuems',
        'python.*ControllerEngine',
        'python.*NodeEngine',
        'OssiaServer',
        'EditorWsServer'
    ]
    
    @classmethod
    def find_cuems_processes(cls):
        """Find all CUEMS-related processes"""
        processes = []
        
        for proc in psutil.process_iter(['pid', 'name', 'cmdline', 'status', 'ppid']):
            try:
                cmdline = ' '.join(proc.info['cmdline'] or [])
                name = proc.info['name'] or ''
                
                # Check if process matches CUEMS patterns
                for pattern in cls.CUEMS_PATTERNS:
                    if pattern.lower() in cmdline.lower() or pattern.lower() in name.lower():
                        processes.append({
                            'pid': proc.info['pid'],
                            'name': name,
                            'cmdline': cmdline,
                            'status': proc.info['status'],
                            'ppid': proc.info['ppid'],
                            'process': proc
                        })
                        break
                        
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                continue
                
        return processes
    
    @classmethod
    def get_process_tree(cls, pid):
        """Get all children of a process"""
        try:
            parent = psutil.Process(pid)
            children = parent.children(recursive=True)
            return [parent] + children
        except psutil.NoSuchProcess:
            return []
    
    @classmethod
    def kill_process_gentle(cls, proc, timeout=5):
        """Try to kill process gently first"""
        try:
            print(f"Trying gentle termination of PID {proc.pid}: {proc.name()}")
            proc.terminate()
            
            # Wait for process to terminate
            proc.wait(timeout=timeout)
            print(f"✓ Process {proc.pid} terminated gracefully")
            return True
            
        except psutil.TimeoutExpired:
            print(f"⚠ Process {proc.pid} didn't terminate within {timeout}s")
            return False
        except psutil.NoSuchProcess:
            print(f"✓ Process {proc.pid} already gone")
            return True
        except Exception as e:
            print(f"✗ Error terminating {proc.pid}: {e}")
            return False
    
    @classmethod
    def kill_process_force(cls, proc):
        """Force kill process"""
        try:
            print(f"Force killing PID {proc.pid}: {proc.name()}")
            proc.kill()
            proc.wait(timeout=3)
            print(f"✓ Process {proc.pid} force killed")
            return True
        except psutil.NoSuchProcess:
            print(f"✓ Process {proc.pid} already gone")
            return True
        except Exception as e:
            print(f"✗ Error force killing {proc.pid}: {e}")
            return False
    
    @classmethod
    def kill_with_system_commands(cls, pid):
        """Use system commands as last resort"""
        commands = [
            f"kill {pid}",
            f"kill -INT {pid}",
            f"kill -9 {pid}",
            f"kill -9 -{pid}",  # Kill process group
        ]
        
        for cmd in commands:
            try:
                print(f"Trying system command: {cmd}")
                result = subprocess.run(cmd.split(), capture_output=True, text=True)
                if result.returncode == 0:
                    print(f"✓ System command succeeded: {cmd}")
                    time.sleep(1)  # Give time for kill to take effect
                    
                    # Check if process is gone
                    try:
                        psutil.Process(pid)
                        print(f"⚠ Process {pid} still alive after {cmd}")
                    except psutil.NoSuchProcess:
                        print(f"✓ Process {pid} confirmed dead")
                        return True
                else:
                    print(f"✗ System command failed: {cmd} - {result.stderr}")
            except Exception as e:
                print(f"✗ Error with system command {cmd}: {e}")
        
        return False
    
    @classmethod
    def kill_cuems_processes(cls, force=False, dry_run=False):
        """Kill all CUEMS processes"""
        processes = cls.find_cuems_processes()
        
        if not processes:
            print("No CUEMS processes found")
            return True
        
        print(f"Found {len(processes)} CUEMS processes:")
        for proc_info in processes:
            status = proc_info['status']
            print(f"  PID {proc_info['pid']:>6} [{status:>12}] {proc_info['name']} - {proc_info['cmdline'][:80]}...")
        
        if dry_run:
            print("\n(Dry run - no processes killed)")
            return True
        
        # Group processes by parent-child relationships
        process_trees = {}
        for proc_info in processes:
            pid = proc_info['pid']
            tree = cls.get_process_tree(pid)
            if tree:
                process_trees[pid] = tree
        
        # Kill process trees (children first)
        success_count = 0
        total_processes = sum(len(tree) for tree in process_trees.values())
        
        print(f"\nKilling {total_processes} processes in {len(process_trees)} trees...")
        
        for root_pid, tree in process_trees.items():
            print(f"\n--- Process Tree rooted at PID {root_pid} ---")
            
            # Reverse order to kill children first
            for proc in reversed(tree):
                try:
                    if not proc.is_running():
                        continue
                        
                    success = False
                    
                    if not force:
                        # Try gentle kill first
                        success = cls.kill_process_gentle(proc, timeout=3)
                    
                    if not success:
                        # Force kill
                        success = cls.kill_process_force(proc)
                    
                    if not success:
                        # System commands as last resort
                        success = cls.kill_with_system_commands(proc.pid)
                    
                    if success:
                        success_count += 1
                    else:
                        print(f"✗ Failed to kill process {proc.pid}")
                        
                except psutil.NoSuchProcess:
                    print(f"✓ Process {proc.pid} already gone")
                    success_count += 1
                except Exception as e:
                    print(f"✗ Error handling process {proc.pid}: {e}")
        
        print(f"\n=== Summary ===")
        print(f"Successfully killed: {success_count}/{total_processes} processes")
        
        # Check for any remaining processes
        remaining = cls.find_cuems_processes()
        if remaining:
            print(f"⚠ {len(remaining)} processes still running:")
            for proc_info in remaining:
                print(f"  PID {proc_info['pid']} - {proc_info['name']}")
            return False
        else:
            print("✓ All CUEMS processes terminated")
            return True

def main():
    import argparse
    
    parser = argparse.ArgumentParser(description="Kill CUEMS-related processes")
    parser.add_argument("--force", "-f", action="store_true", 
                       help="Skip gentle termination, go straight to force kill")
    parser.add_argument("--dry-run", "-n", action="store_true",
                       help="Show what would be killed without actually killing")
    parser.add_argument("--list", "-l", action="store_true",
                       help="List CUEMS processes and exit")
    
    args = parser.parse_args()
    
    if args.list:
        processes = CuemsProcessKiller.find_cuems_processes()
        if processes:
            print(f"Found {len(processes)} CUEMS processes:")
            for proc_info in processes:
                status = proc_info['status']
                print(f"  PID {proc_info['pid']:>6} [{status:>12}] {proc_info['name']} - {proc_info['cmdline'][:80]}...")
        else:
            print("No CUEMS processes found")
        return
    
    print("CUEMS Process Killer")
    print("===================")
    
    if args.dry_run:
        print("DRY RUN MODE - No processes will be killed")
    
    success = CuemsProcessKiller.kill_cuems_processes(
        force=args.force, 
        dry_run=args.dry_run
    )
    
    sys.exit(0 if success else 1)

if __name__ == "__main__":
    main() 
