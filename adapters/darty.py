"""Darty.com (Fnac Darty group: own stock + marketplace). Mirrors adapters/fnac.py.

STATUS: UNVERIFIED SELECTORS. Darty serves the same DataDome captcha
(geo.captcha-delivery.com) as Fnac to headed Chromium, and a fake "Maintenance" page to
headless, from the first request, so the DOM could not be inspected (never bypassed). Verified: the URLs, and that
`detect_blocker` flags the captcha iframe (run shows BLOQUÉ). Selectors are best guesses:
confirm once with a hand-solved session (`--login --sites darty`, then `--check-once`).

Seller rule: only "Vendu et expédié par Darty". Marketplace offers show "Vendu par <shop>"
(Darty's PS5 Pro page is mostly marketplace offers, ~1 550-1 690 € seen via search).
Product: darty.com .../console_ps5/sony_ps5_pro.html ("Console PlayStation5 Pro", 2 To).
Test product: Manette Sony DualSense blanche (MC122209395); it may be marketplace-only,
in which case the test row will show "vendeur refusé": swap test_url for a Darty-sold item.
"""
import re

from .base import Adapter
from .fnac import ensure_ok_fnac_darty


class Darty(Adapter):
    name = "darty"
    label = "Darty"
    url = "https://www.darty.com/nav/achat/console_jeux/univers_ps5/console_ps5/sony_ps5_pro.html"
    test_url = "https://www.darty.com/nav/achat/ref/MC122209395.html"
    home_url = "https://www.darty.com/"

    seller_selector = "[class*='seller' i], .product_buybox [class*='vendeur' i], .buybox__seller"
    seller_ok = r"^(?!.*\bVendu par\b)(?=.*\bVendu et expédié par Darty\b).*$"
    add_to_cart_selector = ("button[data-automation-id='add-to-cart'], .product_buybox button.add-to-cart, "
                            "button:has-text('Ajouter au panier')")
    price_selector = ".product_buybox [class*='price' i], [data-automation-id='product_price']"
    out_of_stock_scope = ".product_buybox, [data-automation-id='product_buybox']"

    login_patterns = [r"/webapp/wcs/stores/servlet/Logon", r"/identification", r"/connexion", r"/login"]
    confirmation_patterns = [r"/confirmation", r"OrderConfirmation", r"/merci"]

    checkout_steps = [
        ("wait", 2),
        ("click_if", "a:has-text('Voir mon panier'), a:has-text('Voir le panier'), button:has-text('Voir mon panier')"),
        ("click_if", "a:has-text('Commander'), button:has-text('Commander'), button:has-text('Valider mon panier')"),
        ("click_if", "button:has-text('Continuer'), button:has-text('Valider')"),
        ("click_if", "button:has-text('Continuer'), button:has-text('Valider')"),
    ]
    final_button_selector = ("button:has-text('Payer'), button:has-text('Valider et payer'), "
                             "button:has-text('Confirmer ma commande')")
    total_selector = "[class*='total' i] >> text=/€/"

    def ensure_ok(self, page, in_checkout: bool = False):
        ensure_ok_fnac_darty(self, page, in_checkout)

    def parse(self, page):
        d = super().parse(page)
        if d.get("seller"):
            d["seller"] = re.sub(r"\s+", " ", d["seller"]).strip()
        return d


ADAPTER = Darty
