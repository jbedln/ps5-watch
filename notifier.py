"""Push notifications via ntfy.sh (JSON publish: UTF-8 safe titles, emojis, click link)."""
import logging

import requests

log = logging.getLogger("ps5watch")
PRIORITY = {"min": 1, "low": 2, "default": 3, "high": 4, "urgent": 5}


class Notifier:
    def __init__(self, cfg: dict):
        n = cfg.get("ntfy") or {}
        self.server = (n.get("server") or "https://ntfy.sh").rstrip("/")
        self.topic = n.get("topic") or ""
        self.enabled = bool(self.topic) and "CHANGE_ME" not in self.topic

    def send(self, title: str, message: str, url: str | None = None,
             priority: str = "default", tags: str = ""):
        log.info("NOTIF [%s] %s — %s %s", priority, title, message, url or "")
        if not self.enabled:
            log.warning("ntfy topic not set in config.yaml: notification only logged")
            return
        body = {"topic": self.topic, "title": title, "message": message,
                "priority": PRIORITY.get(priority, 3)}
        if tags:
            body["tags"] = [t for t in tags.split(",") if t]
        if url:
            body["click"] = url
            body["actions"] = [{"action": "view", "label": "Ouvrir", "url": url}]
        try:
            requests.post(self.server, json=body, timeout=10).raise_for_status()
        except Exception as e:  # a failed push must never stop the monitor
            log.error("ntfy failed: %s", e)
