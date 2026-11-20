"""Base adapter: shared logic for every retailer.

Each site module subclasses `Adapter` and sets mostly data (URLs, selectors,
seller rule). Override `parse()` / `add_to_cart()` / `checkout()` only when the
site needs it.
"""
from __future__ import annotations

import json
import logging
import random
import re
import time
from typing import Any

log = logging.getLogger("ps5watch")


class Blocked(Exception):
    """A human is needed (captcha, queue, login, 3-D Secure). Never bypass."""

    def __init__(self, kind: str, detail: str = ""):
        super().__init__(f"{kind}: {detail}")
        self.kind = kind
        self.detail = detail


# ---------------------------------------------------------------- helpers

def parse_price(text: str | None) -> float | None:
    """'899,99 €' / '899€99' / '1 299,00' / '899.99' -> float."""
    if not text:
        return None
    t = text.replace("\xa0", " ").replace(" ", " ")
    m = re.search(r"(\d{1,3}(?:[ .]\d{3})+(?!\d)|\d+)\s*(?:[,.]\s*(\d{2})(?!\d)|€\s*(\d{2}))?", t)
    if not m:
        return None
    whole = re.sub(r"[ .]", "", m.group(1))
    cents = m.group(2) or m.group(3) or "00"
    try:
        return float(f"{whole}.{cents}")
    except ValueError:
        return None


def jsonld_products(page) -> list[dict]:
    """Every schema.org Product found in the page's JSON-LD."""
    out: list[dict] = []

    def walk(node: Any):
        if isinstance(node, list):
            for n in node:
                walk(n)
        elif isinstance(node, dict):
            t = node.get("@type")
            types = [str(x).lower() for x in (t if isinstance(t, list) else [t])]
            if "product" in types or "productgroup" in types:
                out.append(node)
            for k in ("@graph", "mainEntity", "hasVariant", "itemListElement"):
                if k in node:
                    walk(node[k])

    for raw in page.locator('script[type="application/ld+json"]').all_text_contents():
        try:
            walk(json.loads(raw))
        except (json.JSONDecodeError, TypeError):
            continue
    return out


def offer_from_jsonld(products: list[dict]) -> dict:
    """First usable offer -> {in_stock, price, seller, condition}."""
    for p in products:
        offers = p.get("offers")
        if isinstance(offers, dict) and "offers" in offers:  # AggregateOffer
            offers = offers["offers"]
        offers = offers if isinstance(offers, list) else [offers]
        for o in offers:
            if not isinstance(o, dict):
                continue
            avail = str(o.get("availability", ""))
            seller = o.get("seller") or {}
            seller = seller.get("name") if isinstance(seller, dict) else str(seller)
            cond = str(o.get("itemCondition", "") or p.get("itemCondition", ""))
            price = o.get("price") or o.get("lowPrice")
            try:
                price = float(str(price).replace(",", ".")) if price is not None else None
            except ValueError:
                price = None
            return {
                "in_stock": ("InStock" in avail or "LimitedAvailability" in avail
                             or "OnlineOnly" in avail) if avail else None,
                "price": price,
                "seller": seller,
                "condition": ("new" if "NewCondition" in cond else
                              "used" if re.search(r"Used|Refurbished|Damaged", cond) else None),
            }
    return {}


def text_of(page, selector: str | None, timeout: int = 1500) -> str | None:
    if not selector:
        return None
    loc = page.locator(selector).first
    try:
        if loc.count() == 0:
            return None
        return (loc.inner_text(timeout=timeout) or "").strip() or None
    except Exception:
        return None


def visible(page, selector: str | None) -> bool:
    if not selector:
        return False
    try:
        loc = page.locator(selector)
        return any(loc.nth(i).is_visible() for i in range(min(loc.count(), 5)))
    except Exception:
        return False


def human_pause(lo: float = 0.6, hi: float = 1.8):
    time.sleep(random.uniform(lo, hi))


# ---------------------------------------------------------------- blockers

CAPTCHA_FRAMES = (
    "captcha-delivery.com",          # DataDome (Fnac, Darty, Leclerc...)
    "hcaptcha.com",
    "challenges.cloudflare.com",
    "arkoselabs.com", "funcaptcha.com",
    "recaptcha/api2/bframe",
    "recaptcha/enterprise/bframe",
)
CAPTCHA_SELECTORS = (
    "#px-captcha", "#captcha-container", "form[action*='validateCaptcha']",
    "iframe[title='reCAPTCHA']:not([style*='hidden'])",
    "#challenge-running", "#cf-challenge-running",
)
CAPTCHA_TEXT = re.compile(
    r"Saisissez les caract[eè]res|Je ne suis pas un robot|Vérifiez que vous êtes humain|"
    r"Vérification de sécurité|Verify you are human|Press\s*&\s*Hold|Appuyez et maintenez|"
    r"Nous voulons nous assurer que vous n'êtes pas un robot",
    re.I,
)
QUEUE_URL = re.compile(r"queue-it\.net|queue\.playstation|/queue\b|waitingroom|salle-d-attente", re.I)
QUEUE_TEXT = re.compile(r"Vous êtes dans la file d'attente|file d'attente virtuelle|"
                        r"You are now in line|temps d'attente estimé", re.I)
TDS_FRAMES = ("3ds", "acs", "secure3d", "threeds", "challenge", "authentication")
TDS_TEXT = re.compile(r"3[- ]?D ?Secure|authentification forte|Validez (?:votre|le) paiement dans|"
                      r"confirmez (?:le|votre) paiement sur votre (?:application|téléphone)|"
                      r"Code de vérification envoyé", re.I)


def detect_blocker(page, login_patterns: list[str], in_checkout: bool = False) -> tuple[str, str] | None:
    url = page.url
    if QUEUE_URL.search(url):
        return ("queue", url)
    for pat in login_patterns:
        if re.search(pat, url, re.I):
            return ("login", url)
    for f in page.frames:
        fu = f.url or ""
        if any(s in fu for s in CAPTCHA_FRAMES) and f is not page.main_frame:
            # DataDome / reCAPTCHA can leave a hidden iframe on a page that loaded fine.
            try:
                if f.frame_element().is_visible():
                    return ("captcha", fu[:120])
            except Exception:
                pass
        elif any(s in fu for s in CAPTCHA_FRAMES):
            return ("captcha", fu[:120])
        if in_checkout and any(s in fu.lower() for s in TDS_FRAMES) and f is not page.main_frame:
            try:
                if f.frame_element().is_visible():
                    return ("3ds", fu[:120])
            except Exception:
                pass
    for sel in CAPTCHA_SELECTORS:
        if visible(page, sel):
            return ("captcha", sel)
    try:
        body = page.locator("body").inner_text(timeout=2000)[:20000]
    except Exception:
        body = ""
    # Bot walls that render a fake page instead of a captcha (Akamai / DataDome on headless).
    title = ""
    try:
        title = page.title()
    except Exception:
        pass
    if re.search(r"^(Access Denied|Invalid URL|Attention Required)", title, re.I) or \
            re.search(r"^\s*(Access Denied|Invalid URL)\b", body[:300], re.I):
        return ("captcha", f"bot wall: {title or body[:60]}")
    if CAPTCHA_TEXT.search(body):
        return ("captcha", CAPTCHA_TEXT.search(body).group(0))
    if QUEUE_TEXT.search(body):
        return ("queue", QUEUE_TEXT.search(body).group(0))
    if in_checkout and TDS_TEXT.search(body):
        return ("3ds", TDS_TEXT.search(body).group(0))
    return None


# ---------------------------------------------------------------- adapter

class Adapter:
    # identity
    name = "base"                 # short id used in config / CLI
    label = "Base"                # display name

    # URLs
    url = ""                      # PS5 Pro 2 To CFI-7021 product page
    test_url = ""                 # DualSense (or any in-stock item) for --dry-run
    home_url = ""                 # used by `main.py --login`
    settle_ms = 0                 # extra wait after load (client-side stock check)

    # seller rule: the seller text must match this regex (case-insensitive)
    seller_ok = r".*"
    seller_selector: str | None = None
    default_seller: str | None = None   # site sells only its own stock (no marketplace)

    # stock / price
    price_selector: str | None = None
    add_to_cart_selector: str | None = None   # visible & enabled => in stock
    out_of_stock_text = re.compile(
        r"Rupture de stock|Indisponible|Épuisé|Produit épuisé|Momentanément indisponible|"
        r"Plus disponible|Actuellement indisponible|Bientôt disponible|Me prévenir|"
        r"M'alerter|Être alerté|Prévenez-moi|Out of stock|Victime de son succès|Non disponible",
        re.I)
    out_of_stock_scope: str | None = None     # selector to limit the text search (buybox)
    cookie_reject_selectors: tuple[str, ...] = (
        "#onetrust-reject-all-handler", "button#didomi-notice-disagree-button",
        "button:has-text('Tout refuser')", "button:has-text('Continuer sans accepter')",
        "#sp-cc-rejectall-link", "button:has-text('Refuser')",
    )

    # login / confirmation URL patterns
    login_patterns: list[str] = [r"/login", r"/connexion", r"/signin", r"/identification"]
    confirmation_patterns: list[str] = [r"confirmation", r"thank-?you", r"merci", r"order-?complete"]

    # checkout (declarative): list of ("goto", url) | ("click", selector) | ("wait", seconds)
    cart_url = ""
    checkout_steps: list[tuple[str, Any]] = []
    final_button_selector = ""     # the "Payer / Commander" button. NEVER clicked in assist / dry-run.
    total_selector: str | None = None   # order total on the last page, checked against max price

    def __init__(self, cfg: dict):
        self.cfg = cfg
        site_cfg = (cfg.get("sites") or {}).get(self.name) or {}
        self.url = site_cfg.get("url", self.url)
        self.test_url = site_cfg.get("test_url", self.test_url)

    # ---------------------------------------------------------------- navigation
    def goto(self, page, url: str):
        page.goto(url, wait_until="domcontentloaded", timeout=45000)
        try:
            page.wait_for_load_state("networkidle", timeout=8000)
        except Exception:
            pass
        if self.settle_ms:
            page.wait_for_timeout(self.settle_ms)
        self.reject_cookies(page)
        self.ensure_ok(page)

    def reject_cookies(self, page):
        for sel in self.cookie_reject_selectors:
            try:
                b = page.locator(sel).first
                if b.count() and b.is_visible():
                    b.click(timeout=2000)
                    human_pause(0.3, 0.8)
                    return
            except Exception:
                continue

    def ensure_ok(self, page, in_checkout: bool = False):
        hit = detect_blocker(page, self.login_patterns, in_checkout)
        if hit:
            raise Blocked(*hit)

    # ---------------------------------------------------------------- monitor
    def check(self, page, url: str | None = None) -> dict:
        url = url or self.url
        self.goto(page, url)
        data = {"in_stock": None, "price": None, "seller": None, "condition": None}
        data.update({k: v for k, v in self.parse(page).items() if v is not None})
        return {"site": self.name, "url": url, **data}

    def parse(self, page) -> dict:
        """Default: JSON-LD first, then selectors / text as fallback and as veto."""
        d = offer_from_jsonld(jsonld_products(page))
        price = parse_price(text_of(page, self.price_selector))
        if price:
            d["price"] = price
        seller = text_of(page, self.seller_selector)
        if seller:
            d["seller"] = seller
        if not d.get("seller") and self.default_seller:
            d["seller"] = self.default_seller

        btn_ok = self.add_to_cart_ready(page)
        scope = text_of(page, self.out_of_stock_scope, 2000) if self.out_of_stock_scope else None
        oos = bool(self.out_of_stock_text.search(scope)) if scope else False

        # Every known signal must agree (JSON-LD, buy button, out-of-stock text).
        signals = []
        if d.get("in_stock") is not None:
            signals.append(bool(d["in_stock"]))
        if self.add_to_cart_selector:
            signals.append(btn_ok)
        if scope:
            signals.append(not oos)
        d["in_stock"] = all(signals) if signals else None
        return d

    def add_to_cart_ready(self, page) -> bool:
        if not self.add_to_cart_selector:
            return False
        loc = page.locator(self.add_to_cart_selector)
        for i in range(min(loc.count(), 5)):
            b = loc.nth(i)
            try:
                if b.is_visible() and b.is_enabled() and b.get_attribute("aria-disabled") != "true":
                    return True
            except Exception:
                continue
        return False

    # ---------------------------------------------------------------- buy
    def click(self, page, selector: str, timeout: int = 15000):
        loc = page.locator(selector).first
        loc.wait_for(state="visible", timeout=timeout)
        human_pause(0.4, 1.2)
        loc.click(timeout=timeout)
        try:
            page.wait_for_load_state("domcontentloaded", timeout=15000)
        except Exception:
            pass
        human_pause(1.0, 2.0)

    def add_to_cart(self, page):
        self.click(page, self.add_to_cart_selector)
        self.ensure_ok(page)

    def checkout(self, page):
        """Run the steps up to the final button. Returns the final button locator (not clicked)."""
        if self.cart_url:
            self.goto(page, self.cart_url)
        for kind, arg in self.checkout_steps:
            if kind == "goto":
                self.goto(page, arg)
            elif kind == "click":
                self.click(page, arg)
            elif kind == "click_if":
                if visible(page, arg):
                    self.click(page, arg)
            elif kind == "wait":
                time.sleep(arg)
            self.ensure_ok(page, in_checkout=True)
        btn = page.locator(self.final_button_selector).first
        btn.wait_for(state="visible", timeout=30000)
        self.ensure_ok(page, in_checkout=True)
        return btn

    def order_total(self, page) -> float | None:
        return parse_price(text_of(page, self.total_selector, 3000))

    def is_confirmation(self, page) -> bool:
        return any(re.search(p, page.url, re.I) for p in self.confirmation_patterns)
