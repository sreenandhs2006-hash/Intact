"""Network strength profiles - MY definition of "network strength", stated explicitly.

| Strength | Bandwidth (upload) | Latency (round trip) | Packet loss (each direction) |
|----------|--------------------|----------------------|------------------------------|
| 100%     | 20 Mbit/s          | 20 ms                | 0%                           |
| 60%      | 5 Mbit/s           | 80 ms                | 1%                           |
| 20%      | 500 kbit/s         | 400 ms               | 5%                           |

How they are applied with tc netem on the veth pair between client and server:
- latency is a ROUND TRIP: half is added in each direction;
- loss is applied independently in each direction (data and ACKs);
- bandwidth limits the upload direction (client -> server), which is what an upload needs;
- netem's queue is capped at ~1 s of traffic at that rate (plus packets held for the delay),
  so a slow profile does not hide a huge buffer (bufferbloat) that real radios would not have.
"""
from dataclasses import dataclass


@dataclass(frozen=True)
class Profile:
    name: str
    rate_kbit: int
    rtt_ms: int
    loss_pct: float

    def queue_limit(self):
        pps = self.rate_kbit * 1000 / 8 / 1500           # full-size packets per second
        return max(64, int(pps * (1.0 + self.rtt_ms / 2000)))

    def netem_upload(self):
        """netem arguments for the client -> server direction."""
        return ["delay", f"{self.rtt_ms // 2}ms", "rate", f"{self.rate_kbit}kbit",
                "loss", f"{self.loss_pct}%", "limit", str(self.queue_limit())]

    def netem_download(self):
        """netem arguments for the server -> client direction (responses, ACKs)."""
        return ["delay", f"{self.rtt_ms // 2}ms", "loss", f"{self.loss_pct}%",
                "limit", str(self.queue_limit())]


PROFILES = {
    "100": Profile("100", 20_000, 20, 0),
    "60": Profile("60", 5_000, 80, 1),
    "20": Profile("20", 500, 400, 5),
}
