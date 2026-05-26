# SPDX-FileCopyrightText: 2026 Stagelab Coop SCCL
# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileContributor: Adrià Masip <adria@stagelab.coop>

#!/usr/bin/env python3

from cuemsengine.tools.system_ports import get_used_ports_with_pid


def main():
    from json import dumps
    from sys import argv

    show_help = "--help" in argv
    json_output = "--json" in argv
    user = argv[1] if len(argv) > 1 else None

    if show_help:
        print("Port Recovery Utility")
        print("-" * 30)
        print(f"Usage: {argv[0]} [user] [--json] [--help]")
        print("If --json is provided, the output will be in JSON format.")
        print("If --help is provided, the help message will be displayed.")
        print("-" * 30)
        print("Python documentation:")
        print(get_used_ports_with_pid.__doc__)
        exit(0)

    try:
        used_ports = get_used_ports_with_pid(user)
    except Exception as e:
        print(f"Error getting used ports: {e}")
        exit(1)

    if json_output:
        print(dumps(used_ports, indent=4, default=str))
        exit(0)

    if user:
        print(f"Getting used ports for user containing: {user}")
    else:
        print("Getting all used ports")
    if used_ports:
        print(f"Found {len(used_ports)} processes using ports:")
        for pid, port in sorted(used_ports.items()):
            print(f"  PID {pid}: Port {port}")
    else:
        print("No used ports found.")


if __name__ == "__main__":
    main()
