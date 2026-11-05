"""Network test scenarios.

Each scenario starts on a base profile; steps fire when the upload reaches a given
fraction of the file (read from the client's own log), so faults always land
mid-transfer whatever the link speed. A step is a list of actions run in order:
  ("profile", "20")          switch netem profile
  ("wait", seconds)
  ("disable",) / ("enable",) Toxiproxy: cut all connections and refuse new ones / restore
  ("toxic", name, type)      add a Toxiproxy toxic   ("untoxic", name) remove it
  ("kill_client",) ("start_client",) ("kill_server",) ("start_server",)   SIGKILL / restart
"""

SCENARIOS = {
    "stable_100": {"description": "100% strength throughout", "base": "100", "steps": []},
    "stable_60": {"description": "60% strength throughout", "base": "60", "steps": []},
    "stable_20": {"description": "20% strength throughout", "base": "20", "steps": []},
    "fluctuating": {
        "description": "strength changes mid-transfer 100 -> 60 -> 20 -> 60 -> 20 -> 100",
        "base": "100",
        "steps": [(0.15, [("profile", "60")]), (0.30, [("profile", "20")]), (0.50, [("profile", "60")]),
                  (0.65, [("profile", "20")]), (0.80, [("profile", "100")])],
    },
    "interruption": {
        "description": "60% link; at 30% the connection is cut for 10 s (all sockets closed, new ones refused)",
        "base": "60",
        "steps": [(0.30, [("disable",), ("wait", 10), ("enable",)])],
    },
    "network_switch": {
        "description": "Wi-Fi-like 100% link; at 40% all connections drop for 3 s and the link comes back "
                       "as a cellular-like 20% link (approximation: the client IP does not change)",
        "base": "100",
        "steps": [(0.40, [("disable",), ("wait", 3), ("profile", "20"), ("enable",)])],
    },
    "resets": {
        "description": "60% link; at 25%, 50%, 75% every connection is reset (TCP RST) for 2 s",
        "base": "60",
        "steps": [(p, [("toxic", "rst", "reset_peer"), ("wait", 2), ("untoxic", "rst")]) for p in (0.25, 0.50, 0.75)],
    },
    "timeouts": {
        "description": "60% link; at 30% and 60% data is silently dropped for 30 s (hung connection, "
                       "longer than the client's 20 s stall timeout)",
        "base": "60",
        "steps": [(p, [("toxic", "hang", "timeout"), ("wait", 30), ("untoxic", "hang")]) for p in (0.30, 0.60)],
    },
    "client_restart": {
        "description": "60% link; at 40% the client process is killed (SIGKILL) and restarted 2 s later",
        "base": "60",
        "steps": [(0.40, [("kill_client",), ("wait", 2), ("start_client",)])],
    },
    "server_restart": {
        "description": "60% link; at 40% the server process is killed (SIGKILL) and restarted 3 s later",
        "base": "60",
        "steps": [(0.40, [("kill_server",), ("wait", 3), ("start_server",)])],
    },
}
