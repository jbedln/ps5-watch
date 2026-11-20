"""Boulanger.com (own stock + marketplace, so the seller rule matters).

Verified live (Nov 2026):
- PS5 Pro 2 To = /ref/1230556 ("Console SONY PS5 Pro 2Tb"). Today Boulanger's own stock
  is out (both "Retrait en magasin" and "Livraison à domicile" say Indisponible) and the
  page falls back to a marketplace offer (TOPBIZ, ~1 899 €) with a working "Ajouter au
  panier" button. JSON-LD says InStock at that marketplace price. So stock alone is NOT
  enough: the seller line ("Produit neuf vendu et expédié par Boulanger") decides.
- Everything is scoped to `.product__summary__buying`: the page also has a sticky bar,
  "produits similaires" cards and recommendation carousels that all carry their own
  "Ajouter au panier" buttons, prices and "vendu par" lines.
- Test product: DualSense blanche V3 (/ref/1231767), sold by Boulanger, ~59,99 €.
  Do not use `out_of_stock_scope` here: the DualSense has pickup available but home
  delivery "Indisponible", which would be a false rupture.
- Akamai (Boulanger's bot manager) answers headless Chromium with an "Invalid URL" page
  (errors.edgesuite.net reference), on every URL. Headed Chromium loads normally. We do
  not try to spoof around it: `ensure_ok` turns that page into a Blocked so a headless run
  shows BLOQUÉ instead of a false "rupture". Use headed mode for the real watch (the
  default in config.yaml).

Checkout (guessed, cannot be tested without an account): the add-to-cart button opens a
`#modal-add-to-cart` dialog with a "Voir mon panier" / "Finaliser ma commande" link.
"""
import re

from .base import Adapter, Blocked

BUY = ".product__summary__buying"


class Boulanger(Adapter):
    name = "boulanger"
    label = "Boulanger"
    url = "https://www.boulanger.com/ref/1230556"        # Console SONY PS5 Pro 2Tb
    test_url = "https://www.boulanger.com/ref/1231767"   # Manette DualSense blanche V3
    home_url = "https://www.boulanger.com/"
    settle_ms = 2500

    seller_selector = f"{BUY} .merchant__header"
    seller_ok = r"^Produit neuf vendu et expédié par Boulanger$"
    add_to_cart_selector = f"{BUY} button[aria-controls='modal-add-to-cart']"
    price_selector = f"{BUY} .product-info__price-main .price__current"

    login_patterns = [r"/connexion", r"/identification", r"/compte/login", r"/login"]
    confirmation_patterns = [r"/commande/confirmation", r"confirmation", r"merci"]

    # guessed
    cart_url = "https://www.boulanger.com/panier"
    checkout_steps = [
        ("click_if", "a:has-text('Finaliser ma commande'), button:has-text('Finaliser ma commande'), "
                     "button:has-text('Commander'), a:has-text('Commander')"),
        ("click_if", "button:has-text('Continuer'), button:has-text('Valider')"),
        ("click_if", "button:has-text('Continuer'), button:has-text('Valider')"),
    ]
    final_button_selector = ("button:has-text('Payer'), button:has-text('Valider et payer'), "
                             "button:has-text('Confirmer ma commande'), button:has-text('Je paie')")
    total_selector = "[class*='total' i] >> text=/€/"

    def ensure_ok(self, page, in_checkout: bool = False):
        # Akamai bot wall: plain error page, no captcha frame for detect_blocker to find.
        try:
            title = page.title()
            body = page.locator("body").inner_text(timeout=2000)[:400]
        except Exception:
            title = body = ""
        if title.strip() in ("Invalid URL", "Access Denied") or "errors.edgesuite.net" in body \
                or "You don't have permission to access" in body:
            raise Blocked("captcha", "Akamai bot wall (Invalid URL / Access Denied): headless ? use headed")
        super().ensure_ok(page, in_checkout)

    def parse(self, page):
        d = super().parse(page)
        if d.get("seller"):
            d["seller"] = re.sub(r"\s+", " ", d["seller"]).strip()
        # Reconditionné offers read "Produit reconditionné - ... vendu et expédié par ..."
        if d.get("seller") and not d["seller"].startswith("Produit neuf"):
            d["condition"] = "used"
        return d


ADAPTER = Boulanger
