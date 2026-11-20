"""Micromania (Salesforce Commerce Cloud). Sells new AND "occasion" (used) offers, no marketplace.

Notes from testing (Nov 2026):
- Imperva/Incapsula blocks headless Chromium ("Request unsuccessful. Incapsula incident",
  tiny page with /_Incapsula_Resource). Headed Chromium passes on the first load. We detect the
  block page and raise Blocked, so a headless run shows BLOQUÉ, never a false "rupture".
  => run with browser.headless: false (the config default).
- No JSON-LD. The page carries schema.org *microdata* inside the selected "État" block:
  `.condition-section .variation-select.selected` holds the condition label (Neuf / Occasion),
  [itemprop=price content=...], [itemprop=availability href=...InStock] and the seller (Micromania).
  Several other prices exist on the page (bundles, recommendations): never use a page-wide selector.
- Stock: when out of stock the "Créer une alerte" box is shown, `.add-to-cart-container` gets `d-none`
  and the `.add-to-cart` button is `disabled`. In stock, the container is visible and the button enabled.
- Occasion offers live on other URLs (e.g. /p/ps5-pro-occasion-145581.html) and show "Occasion" in the
  condition label: parse() sets condition="used", so validate() refuses them.
- Cart: /checkout/cart (link seen in the mini-cart). The checkout buttons below are GUESSED (never
  tested: needs an account). Check with `main.py --dry-run` once logged in via `--login`.
- Test product: DualSense (106098), new, sold by Micromania.
"""
import re

from .base import Adapter, Blocked, parse_price

_JS = """() => {
  const root = document.querySelector('.condition-section .variation-select.selected')
            || document.querySelector('.product-detail');
  if (!root) return null;
  const q = s => root.querySelector(s);
  return {
    cond: (q('.product-condition') || {}).textContent || '',
    price: (q('[itemprop=price]') || {getAttribute: () => null}).getAttribute('content'),
    avail: (q('[itemprop=availability]') || {}).href || '',
    itemCond: (q('[itemprop=itemCondition]') || {}).textContent || '',
    seller: ((q('[itemprop=seller] [itemprop=name]') || {}).textContent || '').trim(),
  };
}"""


class Micromania(Adapter):
    name = "micromania"
    label = "Micromania"
    url = "https://www.micromania.fr/p/playstation-5-pro-144778.html"      # PS5 Pro 2 To, NEUF
    test_url = "https://www.micromania.fr/p/manette-sans-fil-dualsense-106098.html"
    home_url = "https://www.micromania.fr/"
    settle_ms = 2500

    default_seller = "Micromania"          # no marketplace
    seller_ok = r"^Micromania$"
    add_to_cart_selector = ".add-to-cart-container:not(.d-none) button.add-to-cart:not([disabled])"
    price_selector = None                  # read from microdata in parse()
    out_of_stock_scope = ".prices-add-to-cart-actions"
    cookie_reject_selectors = ("#onetrust-reject-all-handler", "button#didomi-notice-disagree-button",
                               "button:has-text('Tout refuser')", "button:has-text('Continuer sans accepter')")

    login_patterns = [r"/login", r"/connexion", r"/identification", r"/compte/connexion"]
    confirmation_patterns = [r"/checkout/confirmation", r"order-?confirmation", r"/confirmation", r"merci"]

    # GUESSED: cart page, then "Commander" up to the payment step.
    cart_url = "https://www.micromania.fr/checkout/cart"
    checkout_steps = [
        ("click", "a:has-text('Commander'), button:has-text('Commander'), a:has-text('Valider mon panier'), "
                  "button:has-text('Valider mon panier')"),
        ("wait", 3),
        ("click_if", "button:has-text('Continuer'), button:has-text('Suivant')"),
        ("click_if", "button:has-text('Continuer'), button:has-text('Suivant')"),
    ]
    final_button_selector = ("button:has-text('Payer'), button:has-text('Confirmer la commande'), "
                             "button:has-text('Valider et payer')")
    total_selector = ".grand-total .value, .order-total .value, .grand-total-sum"

    def ensure_ok(self, page, in_checkout: bool = False):
        try:
            html = page.content()
        except Exception:
            html = ""
        if len(html) < 6000 and re.search(r"_Incapsula_Resource|Incapsula incident", html):
            raise Blocked("captcha", "Imperva/Incapsula (page de blocage)")
        super().ensure_ok(page, in_checkout)

    def parse(self, page) -> dict:
        info = page.evaluate(_JS)
        if not info:
            return {"in_stock": None}
        d = {"seller": info["seller"] or self.default_seller}
        try:
            d["price"] = float(info["price"]) if info["price"] else None
        except ValueError:
            d["price"] = None
        if d["price"] is None:
            d["price"] = parse_price(info["cond"])
        is_used = bool(re.search(r"occasion|reconditionn|used|refurb", info["cond"] + info["itemCond"], re.I))
        d["condition"] = "used" if is_used else "new"
        signals = [self.add_to_cart_ready(page)]
        if info["avail"]:
            signals.append("InStock" in info["avail"])
        d["in_stock"] = all(signals)
        return d


ADAPTER = Micromania
