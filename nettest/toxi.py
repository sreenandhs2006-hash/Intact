"""Minimal client for Toxiproxy's HTTP API (https://github.com/Shopify/toxiproxy).

The upload client talks to the proxy; the proxy forwards to the server across the
netem-shaped link. Toxics used:
- reset_peer (timeout 0): every connection is reset (TCP RST) -> "connection reset by peer"
- timeout   (timeout 0): data is silently dropped, connection hangs -> exercises stall detection
- proxy disabled: all connections closed, new ones refused -> temporary disconnection
"""
import httpx

API = "http://127.0.0.1:8474"
PROXY = "vi"
LISTEN = "127.0.0.1:18000"


class Toxi:
    def __init__(self, api=API, log=None):
        self.http = httpx.Client(base_url=api, timeout=5)
        self.log = log or (lambda *a, **k: None)

    def create_proxy(self, upstream):
        self.http.delete(f"/proxies/{PROXY}")
        r = self.http.post("/proxies", json={"name": PROXY, "listen": LISTEN, "upstream": upstream, "enabled": True})
        r.raise_for_status()
        self.log("toxi_proxy", listen=LISTEN, upstream=upstream)

    def reset(self):
        """No toxics, proxy enabled."""
        for t in self.http.get(f"/proxies/{PROXY}/toxics").json():
            self.http.delete(f"/proxies/{PROXY}/toxics/{t['name']}")
        self.set_enabled(True)

    def set_enabled(self, enabled):
        r = self.http.post(f"/proxies/{PROXY}", json={"enabled": enabled})
        r.raise_for_status()
        self.log("toxi_enabled", enabled=enabled)

    def add(self, name, kind, stream="upstream", **attributes):
        r = self.http.post(f"/proxies/{PROXY}/toxics",
                           json={"name": name, "type": kind, "stream": stream, "toxicity": 1.0,
                                 "attributes": attributes})
        r.raise_for_status()
        self.log("toxi_add", name=name, type=kind, stream=stream, attributes=attributes)

    def remove(self, name):
        self.http.delete(f"/proxies/{PROXY}/toxics/{name}")
        self.log("toxi_remove", name=name)

    def version(self):
        try:
            return self.http.get("/version").text.strip()
        except httpx.HTTPError:
            return None
