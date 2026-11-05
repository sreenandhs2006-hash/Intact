"""Linux network lab: server in its own network namespace, joined to the client by a veth pair.

    client (root ns, 10.77.0.1) --vi-cli==veth==vi-srv0-- server (netns "vi-srv", 10.77.0.2)
                  netem: upload profile           netem: download profile

Needs root, iproute2 and the sch_netem kernel module. Every command and its output is
appended to an action log so the run can be audited afterwards.
"""
import json
import shlex
import subprocess
import time

NS = "vi-srv"
CLI_IF, SRV_IF = "vi-cli", "vi-srv0"
CLI_IP, SRV_IP = "10.77.0.1", "10.77.0.2"


class NetLab:
    def __init__(self, action_log=None, dry_run=False):
        self.action_log = action_log
        self.dry_run = dry_run
        self.commands = []  # every command issued (used by tests in dry-run mode)

    def log(self, event, **fields):
        if self.action_log:
            with open(self.action_log, "a", encoding="utf-8") as f:
                f.write(json.dumps({"t": round(time.time(), 3), "event": event, **fields}) + "\n")

    def sh(self, *cmd, check=True):
        self.commands.append(list(cmd))
        if self.dry_run:
            return ""
        p = subprocess.run(cmd, capture_output=True, text=True)
        self.log("cmd", cmd=shlex.join(cmd), rc=p.returncode, out=p.stdout.strip()[-500:], err=p.stderr.strip()[-500:])
        if check and p.returncode != 0:
            raise RuntimeError(f"{shlex.join(cmd)} failed: {p.stderr.strip()}")
        return p.stdout

    def ns(self, *cmd, check=True):
        return self.sh("ip", "netns", "exec", NS, *cmd, check=check)

    def up(self):
        self.down()
        self.sh("ip", "netns", "add", NS)
        self.sh("ip", "link", "add", CLI_IF, "type", "veth", "peer", "name", SRV_IF)
        self.sh("ip", "link", "set", SRV_IF, "netns", NS)
        self.sh("ip", "addr", "add", f"{CLI_IP}/24", "dev", CLI_IF)
        self.sh("ip", "link", "set", CLI_IF, "up")
        self.ns("ip", "addr", "add", f"{SRV_IP}/24", "dev", SRV_IF)
        self.ns("ip", "link", "set", SRV_IF, "up")
        self.ns("ip", "link", "set", "lo", "up")
        # veth offloads merge packets into 64 KB super-packets, which would make netem's
        # per-packet loss and rate meaningless; turn them off on both ends.
        self.sh("ethtool", "-K", CLI_IF, "tso", "off", "gso", "off", "gro", "off", check=False)
        self.ns("ethtool", "-K", SRV_IF, "tso", "off", "gso", "off", "gro", "off", check=False)

    def down(self):
        self.sh("ip", "link", "del", CLI_IF, check=False)
        self.sh("ip", "netns", "del", NS, check=False)

    def set_profile(self, profile):
        self.sh("tc", "qdisc", "replace", "dev", CLI_IF, "root", "netem", *profile.netem_upload())
        self.ns("tc", "qdisc", "replace", "dev", SRV_IF, "root", "netem", *profile.netem_download())
        self.log("profile", name=profile.name, rate_kbit=profile.rate_kbit, rtt_ms=profile.rtt_ms,
                 loss_pct=profile.loss_pct)

    def show(self):
        return {"client_side": self.sh("tc", "-s", "qdisc", "show", "dev", CLI_IF, check=False),
                "server_side": self.ns("tc", "-s", "qdisc", "show", "dev", SRV_IF, check=False)}
