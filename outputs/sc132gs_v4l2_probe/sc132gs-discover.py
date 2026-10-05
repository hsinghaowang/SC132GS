#!/usr/bin/env python3
"""Resolve stable SC132GS roles through enabled media-controller links."""

import argparse
import re
import subprocess
import sys
from pathlib import Path

ENTITY = re.compile(r"^- entity \d+: (.+?) \(\d+ pads?, \d+ links?(?:, [^)]+)?\)")
NODE = re.compile(r"^\s*device node name (/dev/\S+)")
LINK = re.compile(r'^\s*-> "([^"]+)":\d+ \[([^]]+)\]')
SENSORS = {"cam0": re.compile(r"^sc132gs \S+-0032$"),
           "cam1": re.compile(r"^sc132gs \S+-0030$")}


def parse_topology(output):
    nodes = {}
    edges = {}
    current = None
    for line in output.splitlines():
        match = ENTITY.match(line)
        if match:
            current = match.group(1)
            if current in edges:
                raise ValueError(f"duplicate media entity: {current}")
            edges[current] = set()
            continue
        if current is None:
            continue
        match = NODE.match(line)
        if match:
            nodes[current] = match.group(1)
        match = LINK.match(line)
        if match and "ENABLED" in match.group(2).split(","):
            edges[current].add(match.group(1))
    return nodes, edges


def resolve(output, requested="pair"):
    nodes, edges = parse_topology(output)
    result = {}
    roles = SENSORS if requested == "pair" else {requested: SENSORS[requested]}
    for role, pattern in roles.items():
        sensors = [name for name in edges if pattern.fullmatch(name)]
        if len(sensors) != 1:
            raise ValueError(f"{role}: expected one sensor entity, found {len(sensors)}")
        pending = sensors[:]
        visited = set()
        video_nodes = set()
        while pending:
            name = pending.pop()
            if name in visited:
                continue
            visited.add(name)
            node = nodes.get(name, "")
            if re.fullmatch(r"/dev/video\d+", node):
                video_nodes.add(node)
            pending.extend(edges.get(name, ()))
        if len(video_nodes) != 1:
            raise ValueError(f"{role}: expected one enabled video path, found {sorted(video_nodes)}")
        result[role] = video_nodes.pop()
    if requested == "pair" and result["cam0"] == result["cam1"]:
        raise ValueError("both camera roles resolve to the same video node")
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("role", choices=("cam0", "cam1", "pair", "media"))
    parser.add_argument("--media", help="explicit /dev/mediaN; otherwise scan all media devices")
    args = parser.parse_args()
    media = [Path(args.media)] if args.media else sorted(Path("/dev").glob("media[0-9]*"))
    matches = []
    for device in media:
        probe = subprocess.run(("media-ctl", "-d", str(device), "-p"),
                               text=True, capture_output=True, check=False)
        if probe.returncode:
            if args.media:
                raise ValueError(f"media-ctl failed for {device}: {probe.stderr.strip()}")
            continue
        try:
            if args.role == "media":
                _, edges = parse_topology(probe.stdout)
                if not all(sum(bool(pattern.fullmatch(name)) for name in edges) == 1
                           for pattern in SENSORS.values()):
                    raise ValueError("both SC132GS sensor entities are required")
                matches.append((device, {}))
            else:
                matches.append((device, resolve(probe.stdout, args.role)))
        except ValueError:
            if args.media:
                raise
    if len(matches) != 1:
        raise ValueError(f"expected one SC132GS media graph for {args.role}, found {len(matches)}")
    result = matches[0][1]
    if args.role == "media":
        print(matches[0][0])
    elif args.role == "pair":
        print(result["cam0"], result["cam1"])
    else:
        print(result[args.role])


if __name__ == "__main__":
    try:
        main()
    except (OSError, ValueError) as error:
        print(f"sc132gs-discover: {error}", file=sys.stderr)
        sys.exit(1)
