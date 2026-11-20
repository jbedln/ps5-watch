"""Auchan.fr — only "Vendu par Auchan" (the site is also a marketplace: Mass Distrib, Multishop...).

Notes from testing (Nov 2026):
- No usable JSON-LD. Product page = `.offer-selector__*` blocks (server rendered):
  seller  `.offer-selector__description-content .offer-selector__seller` ("Vendu par Auchan",
          or "Vendu par" + link for a marketplace seller),
  price   `.offer-selector__price-container meta[itemprop=price]`,
  stock   `meta[itemprop=availability]` (schema.org/InStock | OutOfStock) next to it.
- Sold-out state: "Bientôt dispo !" in `.product-unavailable__message`, add-to-cart absent.
  Some listings hide the price entirely ("Afficher le prix") when unavailable.
- The add-to-cart button exists but is `disabled` until a store / drive is chosen for items
  that are store-based (e.g. DualSense Starlight Blue "Retrait dès 1h en magasin"), so it
  cannot be used as the stock signal anonymously. We use availability meta + no
  unavailable banner. For the real purchase choose a store once in the profile
  (`main.py --login --sites auchan`), otherwise the click step times out.
- Two listings for the same console: C1824137 = EAN 0711719595472 (CFI-7021, 799,99 EUR,
  "Vendu par Auchan", currently "Bientôt dispo !") and C1851143 = EAN 0711719024040
  (newer ref, price hidden while unavailable). Both are checked (`alt_urls`).
- Test product: DualSense Starlight Blue (59,99 EUR), "Vendu par Auchan".
- Cart: /checkout/cart/ (header link "Voir mon panier"). Anonymous add was not possible
  without a store, so the cart page and everything after are GUESSED.
"""
import re
import time
import random

from .base import Adapter, parse_price, text_of, visible


class Auchan(Adapter):
    name = "auchan"
    label = "Auchan"
    url = "https://www.auchan.fr/sony-console-playstation-5-pro/pr-C1824137"
    alt_urls = ["https://www.auchan.fr/sony-console-playstation-5-pro/pr-C1851143"]
    test_url = "https://www.auchan.fr/sony-manette-sans-fil-dualsense-starlight-blue-ps5/pr-C1856154"
    home_url = "https://www.auchan.fr/"
    settle_ms = 1500

    seller_ok = r"^Auchan(\.fr)?$"
    seller_selector = ".offer-selector__description-content .offer-selector__seller"
    add_to_cart_selector = ".offer-selector__action-wrapper--add-to-cart button.quantity-selector__button--add"
    price_selector = ".offer-selector__price-container .product-price--large"
    out_of_stock_scope = ".offer-selector__action-wrapper--unavailable, .product-unavailable__message"
    cookie_reject_selectors = ("#onetrust-reject-all-handler", "button#didomi-notice-disagree-button",
                               "button:has-text('Continuer sans accepter')", "button:has-text('Tout refuser')")

    login_patterns = [r"/connexion", r"/login", r"/identification", r"/mon-compte/connexion"]
    confirmation_patterns = [r"/confirmation", r"/commande/confirmation", r"merci", r"order-?complete"]

    cart_url = "https://www.auchan.fr/checkout/cart/"
    checkout_steps = [
        ("click", "a:has-text('Valider mon panier'), button:has-text('Valider mon panier'), "
                  "a:has-text('Passer la commande'), button:has-text('Passer la commande'), "
                  "a:has-text('Commander'), button:has-text('Commander')"),
        ("wait", 3),
        ("click_if", "button:has-text('Continuer'), button:has-text('Valider')"),
        ("wait", 3),
        ("click_if", "button:has-text('Continuer'), button:has-text('Valider')"),
    ]
    final_button_selector = ("button:has-text('Payer'), button:has-text('Valider et payer'), "
                             "button:has-text('Confirmer la commande'), button:has-text('Je paie')")
    total_selector = "[class*='total' i] >> text=/€/"

    def check(self, page, url=None) -> dict:
        if url and url != self.url:                    # --test or explicit URL: single page
            return super().check(page, url)
        best = None
        for u in [self.url, *self.alt_urls]:
            r = super().check(page, u)
            ok = bool(r.get("in_stock")) and re.search(self.seller_ok, r.get("seller") or "", re.I)
            if ok:
                return r
            if best is None or (r.get("in_stock") and not best.get("in_stock")):
                best = r
            time.sleep(random.uniform(3, 6))
        return best

    def parse(self, page) -> dict:
        seller_raw = text_of(page, self.seller_selector) or ""
        m = re.search(r"Vendu par\s*(.+)", seller_raw, re.S)
        seller = re.sub(r"\s+", " ", m.group(1)).strip() if m else None

        def meta(prop):
            loc = page.locator(f".offer-selector__price-container meta[itemprop='{prop}']").first
            try:
                return loc.get_attribute("content") if loc.count() else None
            except Exception:
                return None

        avail = meta("availability") or ""
        price = None
        if meta("price"):
            try:
                price = float(meta("price"))
            except ValueError:
                price = None
        if price is None:
            price = parse_price(text_of(page, self.price_selector))
        unavailable = visible(page, ".product-unavailable__message")
        in_stock = "InStock" in avail and not unavailable
        return {"in_stock": in_stock, "price": price, "seller": seller, "condition": "new"}


ADAPTER = Auchan
