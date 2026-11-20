#!/usr/bin/env python3
"""PS5 Pro (2 To, CFI-7021) stock watcher + checkout assistant.

  python main.py                 watch all enabled sites, buy per config `mode`
  python main.py --check-once    one pass, prints a table, never buys
  python main.py --dry-run       watch the test product (DualSense), go up to the
                                 final pay button, never click it
  python main.py --login         open every site in the profile so you can log in
  python main.py --reset-lock    clear the "already bought" lock
"""
from __future__ import annotations

import argparse
import json
import logging
import random
import re
import os
import sys
import time
from logging.handlers import RotatingFileHandler
from pathlib import Path

import yaml
from playwright.sync_api import sync_playwright

import adapters
from adapters.base import Blocked, detect_blocker
from notifier import Notifier

ROOT = Path(__file__).resolve().parent
log = logging.getLogger("ps5watch")

USED_RE = re.compile(r"occasion|reconditionn|seconde main|used|refurb|comme neuf|très bon état", re.I)
BLOCK_MSG = {
    "captcha": "CAPTCHA affiché",
    "queue": "File d'attente (Queue-it)",
    "login": "Page de connexion : tu n'es plus connecté",
    "3ds": "3-D Secure : valide le paiement sur ton téléphone",
}


# ---------------------------------------------------------------- setup

def load_config(path: Path) -> dict:
    cfg = yaml.safe_load(path.read_text("utf-8"))
    local = path.with_name("config.local.yaml")   # private bits (ntfy topic), not in git
    if local.exists():
        for k, v in (yaml.safe_load(local.read_text("utf-8")) or {}).items():
            if isinstance(v, dict) and isinstance(cfg.get(k), dict):
                cfg[k].update(v)
            else:
                cfg[k] = v
    if os.environ.get("NTFY_TOPIC"):              # GitHub Actions secret
        cfg.setdefault("ntfy", {})["topic"] = os.environ["NTFY_TOPIC"]
    cfg["_root"] = path.parent
    p = cfg.setdefault("poll", {})
    p["min_seconds"] = max(120, int(p.get("min_seconds", 120)))       # hard floor
    p["max_seconds"] = max(p["min_seconds"], int(p.get("max_seconds", 240)))
    if cfg.get("mode") not in ("assist", "auto"):
        cfg["mode"] = "assist"
    return cfg


def rel(cfg, key, default) -> Path:
    p = Path(cfg.get(key, default))
    return p if p.is_absolute() else cfg["_root"] / p


def setup_logging(cfg):
    d = rel(cfg, "logs_dir", "./logs")
    d.mkdir(parents=True, exist_ok=True)
    fmt = logging.Formatter("%(asctime)s %(levelname)-7s %(message)s", "%Y-%m-%d %H:%M:%S")
    fh = RotatingFileHandler(d / "ps5watch.log", maxBytes=5_000_000, backupCount=5, encoding="utf-8")
    fh.setFormatter(fmt)
    sh = logging.StreamHandler(sys.stdout)
    sh.setFormatter(fmt)
    log.setLevel(logging.INFO)
    log.handlers[:] = [fh, sh]


class State:
    def __init__(self, path: Path):
        self.path = path
        self.d = json.loads(path.read_text()) if path.exists() else {}
        self.d.setdefault("last", {})
        self.d.setdefault("paused_until", {})

    def save(self):
        self.path.write_text(json.dumps(self.d, indent=2, ensure_ascii=False))

    @property
    def purchased(self):
        return self.d.get("purchased")

    def lock(self, site, url, how):
        self.d["purchased"] = {"site": site, "url": url, "how": how, "at": time.strftime("%Y-%m-%d %H:%M:%S")}
        self.save()


def open_browser(p, cfg, headless: bool | None = None):
    b = cfg.get("browser") or {}
    prof = Path(b.get("profile_dir", "./profile"))
    prof = prof if prof.is_absolute() else cfg["_root"] / prof
    prof.mkdir(parents=True, exist_ok=True)
    ctx = p.chromium.launch_persistent_context(
        str(prof),
        headless=b.get("headless", False) if headless is None else headless,
        locale=b.get("locale", "fr-FR"),
        timezone_id=b.get("timezone", "Europe/Paris"),
        # no fixed viewport: the page follows the real window size
        # (a fixed one renders cut-off / shifted pages when the window differs)
        no_viewport=True,
        args=["--disable-blink-features=AutomationControlled",
              "--window-size=1400,950"],
    )
    page = ctx.pages[0] if ctx.pages else ctx.new_page()
    page.set_default_timeout(20000)
    return ctx, page


# ---------------------------------------------------------------- rules

def validate(r: dict, adapter, cfg, test: bool) -> tuple[bool, str]:
    """Return (buyable, reason). All rules from the brief live here."""
    if not r.get("in_stock"):
        return False, "rupture"
    price = r.get("price")
    if price is None:
        return False, "prix introuvable"
    if price > float(cfg["max_price"]):
        return False, f"prix {price:.2f} > max {cfg['max_price']}"
    seller = r.get("seller") or ""
    if not seller:
        return False, "vendeur introuvable"
    if not re.search(adapter.seller_ok, seller, re.I):
        return False, f"vendeur refusé : {seller[:60]}"
    if r.get("condition") == "used" or USED_RE.search(" ".join(str(r.get(k) or "") for k in ("seller", "title"))):
        return False, "pas neuf"
    return True, "OK"


# ---------------------------------------------------------------- buying

def human_solves(page, adapter, b, url, cfg, notifier) -> bool:
    """CAPTCHA on screen: ask the human to solve it in the window, wait for it to go away.
    Never solves it itself."""
    minutes = int(cfg.get("captcha_wait_minutes", 10))
    if minutes <= 0:
        return False
    log.warning("%s CAPTCHA -> j'attends que tu le résolves (%d min max)", adapter.name, minutes)
    notifier.send(f"{adapter.label} : CAPTCHA à résoudre",
                  f"Résous-le dans la fenêtre Chromium du script. J'attends {minutes} min.",
                  None, "high", "warning")
    end = time.time() + minutes * 60
    while time.time() < end:
        time.sleep(5)
        if page.is_closed():
            return False
        try:
            if detect_blocker(page, adapter.login_patterns) is None:
                log.info("%s CAPTCHA résolu, je reprends", adapter.name)
                time.sleep(3)
                return True
        except Exception:
            pass
    return False


def wait_for_human(page, adapter, minutes=30) -> str:
    """Assist hand-off. Returns 'ordered' | 'closed' | 'timeout'."""
    end = time.time() + minutes * 60
    sel = adapter.final_button_selector
    while time.time() < end:
        if page.is_closed():
            return "closed"
        try:
            if adapter.is_confirmation(page):
                return "ordered"
            # final button gone and no blocker on screen => the order most likely went through
            if sel and page.locator(sel).count() == 0:
                time.sleep(5)
                if not page.is_closed() and page.locator(sel).count() == 0:
                    return "ordered"
        except Exception:
            pass
        time.sleep(3)
    return "timeout"


def buy(adapter, page, r, cfg, state: State, notifier: Notifier, dry_run: bool) -> bool:
    """Returns True if the watcher must stop (bought, or dry-run done)."""
    mode = "dry-run" if dry_run else cfg["mode"]
    log.info("ACHAT %s (%s) %s", adapter.label, mode, r["url"])
    try:
        adapter.add_to_cart(page)
        btn = adapter.checkout(page)
    except Blocked as b:
        notifier.send(f"{adapter.label} : {BLOCK_MSG.get(b.kind, b.kind)}",
                      "Achat en pause, à toi de jouer dans la fenêtre.", page.url, "urgent", "warning")
        status = wait_for_human(page, adapter)
        if status == "ordered" and not dry_run:
            state.lock(adapter.name, r["url"], "manual-after-block")
            notifier.send("Commande passée ✅", f"{adapter.label}. Le script s'arrête.", page.url, "high", "tada")
            return True
        return dry_run
    except Exception as e:
        log.exception("checkout failed on %s", adapter.name)
        notifier.send(f"{adapter.label} : checkout planté",
                      f"{type(e).__name__}: {str(e)[:200]}. Fini à la main ?", page.url, "urgent", "x")
        status = wait_for_human(page, adapter, 15)
        if status == "ordered" and not dry_run:
            state.lock(adapter.name, r["url"], "manual-after-error")
            return True
        return False

    total = adapter.order_total(page)
    if total and total > float(cfg["max_price"]):
        notifier.send(f"{adapter.label} : total trop cher", f"{total:.2f} € > {cfg['max_price']} €. Annulé.",
                      page.url, "high", "no_entry")
        return False

    if dry_run:
        notifier.send(f"[DRY-RUN] {adapter.label} prêt", f"Arrivé au bouton final (total {total or '?'} €). "
                      "Rien n'a été payé. Pense à vider le panier.", page.url, "default", "test_tube")
        log.info("DRY-RUN OK on %s: final button found, not clicked", adapter.name)
        return True

    if mode == "auto":
        log.info("AUTO: clicking final button on %s", adapter.name)
        state.lock(adapter.name, r["url"], "auto-click")       # lock first: never two orders
        btn.click()
        time.sleep(5)
        try:
            adapter.ensure_ok(page, in_checkout=True)
            notifier.send("Commande envoyée ✅", f"{adapter.label}, {total or r['price']} €. Script arrêté.",
                          page.url, "high", "tada")
        except Blocked as b:
            notifier.send(f"{adapter.label} : {BLOCK_MSG.get(b.kind, b.kind)}",
                          "Commande cliquée, il reste ta validation. Script arrêté.", page.url, "urgent", "warning")
            wait_for_human(page, adapter)
        return True

    # assist
    notifier.send(f"PS5 Pro prête chez {adapter.label} 🎮",
                  f"{total or r['price']} €. Tout est rempli : clique sur le bouton final dans la fenêtre.",
                  page.url, "urgent", "rotating_light")
    status = wait_for_human(page, adapter)
    log.info("assist hand-off on %s ended: %s", adapter.name, status)
    if status == "ordered":
        state.lock(adapter.name, r["url"], "assist")
        notifier.send("Commande passée ✅", f"{adapter.label}. Le script coupe tout.", None, "high", "tada")
        return True
    notifier.send(f"{adapter.label} : pas validé", f"Hand-off terminé ({status}). Je reprends la veille.",
                  None, "default", "hourglass")
    return False


# ---------------------------------------------------------------- modes

def build_adapters(cfg, only: list[str] | None):
    names = only or cfg.get("enabled_sites") or adapters.ALL_SITES
    out = []
    for n in names:
        try:
            out.append(adapters.load(n, cfg))
        except ModuleNotFoundError:
            log.warning("adapter %s not found, skipped", n)
    return out


def fmt_row(cols, widths):
    return "  ".join(str(c)[:w].ljust(w) for c, w in zip(cols, widths))


def check_once(cfg, only, test, headless):
    rows = []
    with sync_playwright() as p:
        ctx, page = open_browser(p, cfg, headless)
        for a in build_adapters(cfg, only):
            url = a.test_url if test else a.url
            t0 = time.time()
            try:
                r = a.check(page, url)
                ok, why = validate(r, a, cfg, test)
                stock = {True: "EN STOCK", False: "rupture", None: "?"}[r.get("in_stock")]
                price = f"{r['price']:.2f} €" if r.get("price") else "-"
                rows.append((a.label, stock, price, r.get("seller") or "-", "OUI" if ok else "non", why))
            except Blocked as b:
                rows.append((a.label, "BLOQUÉ", "-", "-", "non", f"{b.kind}: {b.detail[:60]}"))
            except Exception as e:
                rows.append((a.label, "ERREUR", "-", "-", "non", f"{type(e).__name__}: {str(e).splitlines()[0][:70]}"))
            log.info("check-once %s: %s (%.1fs)", a.name, rows[-1], time.time() - t0)
            time.sleep(random.uniform(1.5, 4))
        ctx.close()
    widths = (20, 9, 10, 30, 7, 60)
    print()
    print(fmt_row(("SITE", "STOCK", "PRIX", "VENDEUR", "ACHAT?", "NOTE"), widths))
    print(fmt_row(["-" * w for w in widths], widths))
    for r in rows:
        print(fmt_row(r, widths))
    print()


def cloud(cfg, only):
    """One pass for GitHub Actions: no account, no buying. Push only when a site turns
    into a valid offer (stock + price <= max + sold by the retailer). Silent otherwise."""
    st_path = rel(cfg, "cloud_state_file", "./cloud_state.json")
    st = json.loads(st_path.read_text()) if st_path.exists() else {}
    notifier = Notifier(cfg)
    readable = 0
    adapters = build_adapters(cfg, only)
    with sync_playwright() as p:
        ctx, page = open_browser(p, cfg, False)
        for a in adapters:
            try:
                r = a.check(page, a.url)
                ok, why = validate(r, a, cfg, False)
                readable += 1
            except Blocked as b:
                log.info("cloud %s bloqué (%s)", a.name, b.kind)
                continue
            except Exception as e:
                log.info("cloud %s erreur: %s", a.name, str(e).splitlines()[0][:150])
                if page.is_closed():
                    page = ctx.new_page()
                continue
            log.info("cloud %-11s stock=%s prix=%s vendeur=%s -> %s", a.name, r.get("in_stock"),
                     r.get("price"), r.get("seller"), why)
            if ok and not st.get(a.name):
                notifier.send(f"STOCK {cfg.get('product', 'PS5 Pro')} chez {a.label}",
                              f"{r['price']:.2f} €, vendu par {r['seller']}. Fonce !",
                              a.url, "urgent", "rotating_light")
            st[a.name] = ok
            time.sleep(random.uniform(2, 5))
        ctx.close()
    today = time.strftime("%Y-%m-%d")
    if st.get("_summary") != today:  # one quiet "still alive" ping per day
        notifier.send("Veille cloud OK", f"{readable}/{len(adapters)} sites lisibles aujourd'hui.",
                      None, "min", "white_check_mark")
        st["_summary"] = today
    st_path.write_text(json.dumps(st, indent=1))


def login(cfg, only):
    with sync_playwright() as p:
        ctx, page = open_browser(p, cfg, headless=False)
        sites = build_adapters(cfg, only)
        for i, a in enumerate(sites):
            pg = page if i == 0 else ctx.new_page()
            try:
                pg.goto(a.home_url or a.url, wait_until="domcontentloaded", timeout=45000)
            except Exception as e:
                print(f"{a.label}: {e}")
        print("\nUn onglet par site est ouvert. Connecte-toi partout, vérifie adresse + carte enregistrées.")
        input("Appuie sur Entrée ici quand c'est fini (le profil est sauvegardé)... ")
        ctx.close()


def watch(cfg, only, dry_run, headless):
    state = State(rel(cfg, "state_file", "./state.json"))
    notifier = Notifier(cfg)
    if state.purchased and not dry_run:
        log.warning("Déjà acheté : %s. Rien à faire (python main.py --reset-lock pour relancer).", state.purchased)
        return
    pause_s = int(cfg.get("blocked_pause_minutes", 30)) * 60
    lo, hi = cfg["poll"]["min_seconds"], cfg["poll"]["max_seconds"]
    bs = cfg["poll"].get("between_sites_seconds", [4, 12])
    sites = build_adapters(cfg, only)
    log.info("START mode=%s dry_run=%s sites=%s max=%.2f", cfg["mode"], dry_run,
             ",".join(a.name for a in sites), cfg["max_price"])
    notifier.send("Veille PS5 Pro lancée", f"{len(sites)} sites, mode {'dry-run' if dry_run else cfg['mode']}.",
                  None, "low", "eyes")

    with sync_playwright() as p:
        ctx, page = open_browser(p, cfg, headless)
        while True:
            for a in sites:
                until = state.d["paused_until"].get(a.name, 0)
                if until > time.time():
                    continue
                url = a.test_url if dry_run else a.url
                if not url:
                    continue
                try:
                    try:
                        r = a.check(page, url)
                    except Blocked as b:
                        # CAPTCHA: a human solves it in the open window, then we read the page again
                        hard = False
                        try:
                            hard = "temporairement restreint" in page.inner_text("body", timeout=3000)
                        except Exception:
                            pass
                        if b.kind != "captcha" or hard or not human_solves(page, a, b, url, cfg, notifier):
                            raise
                        r = a.check(page, url)
                except Blocked as b:
                    site_pause = int(cfg.get("blocked_pause_by_site", {}).get(a.name, pause_s // 60)) * 60
                    state.d["paused_until"][a.name] = time.time() + site_pause
                    already = state.d.setdefault("block_notified", {}).get(a.name)
                    state.d["block_notified"][a.name] = True
                    state.save()
                    log.warning("%s BLOQUÉ (%s) %s -> pause %d min", a.name, b.kind, b.detail, site_pause // 60)
                    if not already:  # one notif per blocking streak, not one every retry
                        notifier.send(f"{a.label} en pause : {BLOCK_MSG.get(b.kind, b.kind)}",
                                      f"Je réessaie toutes les {site_pause // 60} min, sans te renotifier.",
                                      url, "default", "warning")
                    continue
                except Exception as e:
                    log.error("%s erreur: %s", a.name, str(e).splitlines()[0][:200])
                    if page.is_closed():
                        page = ctx.new_page()
                    continue

                state.d.setdefault("block_notified", {}).pop(a.name, None)
                ok, why = validate(r, a, cfg, dry_run)
                prev = state.d["last"].get(a.name)
                now = bool(r.get("in_stock"))
                log.info("%-11s stock=%-5s prix=%-8s vendeur=%-25s -> %s", a.name, r.get("in_stock"),
                         r.get("price"), (r.get("seller") or "-")[:25], why)
                if prev is not None and prev != now:
                    log.warning("CHANGEMENT %s : %s -> %s", a.name, "dispo" if prev else "rupture",
                                "dispo" if now else "rupture")
                state.d["last"][a.name] = now
                state.save()

                if now and not ok and (prev is False or prev is None):
                    log.info("%s dispo mais refusé (%s) : pas de notif", a.name, why)
                if ok:
                    notifier.send(f"STOCK {cfg.get('product', 'PS5 Pro')} chez {a.label}",
                                  f"{r['price']:.2f} €, vendu par {r['seller']}. J'y vais.", url, "urgent",
                                  "rotating_light")
                    if buy(a, page, r, cfg, state, notifier, dry_run):
                        log.info("STOP: %s", "dry-run terminé" if dry_run else "commande passée")
                        if not dry_run or cfg["mode"] == "assist":
                            input("Fenêtre laissée ouverte. Entrée pour fermer le navigateur... ") \
                                if sys.stdin.isatty() else time.sleep(3600)
                        ctx.close()
                        return
                    if page.is_closed():
                        page = ctx.new_page()
                time.sleep(random.uniform(*bs))
            wait = random.uniform(lo, hi)
            log.info("round done, next in %.0fs", wait)
            time.sleep(wait)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--config", default=str(ROOT / "config.yaml"))
    ap.add_argument("--check-once", action="store_true")
    ap.add_argument("--cloud", action="store_true", help="one alert-only pass (GitHub Actions)")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--login", action="store_true")
    ap.add_argument("--reset-lock", action="store_true")
    ap.add_argument("--test", action="store_true", help="with --check-once: use the test product URLs")
    ap.add_argument("--sites", help="comma list, e.g. playstation,amazon")
    ap.add_argument("--headless", action="store_true", help="force headless (check-once only)")
    args = ap.parse_args()

    cfg = load_config(Path(args.config))
    setup_logging(cfg)
    only = [s.strip() for s in args.sites.split(",")] if args.sites else None
    headless = True if args.headless else None

    if args.reset_lock:
        st = State(rel(cfg, "state_file", "./state.json"))
        st.d.pop("purchased", None)
        st.d["paused_until"] = {}
        st.save()
        print("Lock et pauses effacés.")
    elif args.cloud:
        cloud(cfg, only)
    elif args.login:
        login(cfg, only)
    elif args.check_once:
        check_once(cfg, only, args.test, headless)
    else:
        watch(cfg, only, args.dry_run, None)


if __name__ == "__main__":
    main()
