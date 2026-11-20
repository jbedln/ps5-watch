"""E.Leclerc (non-food site www.e.leclerc/fp/...) — only offers sold by E.Leclerc itself.

Notes from testing (Nov 2026):
- Every product page has ONE default offer shown in `#product-buybox`, headed either
  "Offre E.Leclerc" (E.Leclerc's own stock: Click&Collect + "Livraison en magasin" / relay /
  home express, "Vendu par E.Leclerc") or "Offre Partenaire" (marketplace: "Vendu par X").
  Other offers (partners, "seconde vie"/used) are in a side list and are ignored.
- JSON-LD is useless (first offer is a marketplace seller, E.Leclerc offers have no price).
  `#product-buybox[data-price]` gives the price of the default offer.
- Stock = `#add-to-cart-btn` visible + enabled and "En stock" in the buybox. Anonymous add to
  cart works for the E.Leclerc offer (cart: https://www.e.leclerc/cart, button "Choisir ma
  livraison"); no store is required to add, the store/delivery is picked in the cart.
- As of testing the PS5 Pro 2 To pages only have PARTNER offers (PIX.L DISTRIBUTION,
  Topbiz... at 1 850-2 000 EUR): they show EN STOCK but are rejected (seller + price).
  The row turns OUI only if an "Offre E.Leclerc" appears. Two listings are checked:
  0711719595472 (CFI-7021) and 0711719024040 (2TB edition, newer ref) via `alt_urls`.
- No captcha/DataDome seen on these pages in headless or headed Chromium.
- VERIFIED: add to cart, cart URL, "Choisir ma livraison". GUESSED: delivery/payment steps and
  the final pay button (checkout needs a signed-in account).
- Test product: DualSense Midnight Black (59,90 EUR), "Offre E.Leclerc".
"""
import random
import re
import time

from .base import Adapter, text_of


class Leclerc(Adapter):
    name = "leclerc"
    label = "E.Leclerc"
    url = "https://www.e.leclerc/fp/console-playstation-5-pro-ps5-0711719595472"
    alt_urls = ["https://www.e.leclerc/fp/console-playstation-5-edition-pro-2tb-ps5-0711719024040"]
    test_url = "https://www.e.leclerc/fp/manette-sans-fil-dualsense-midnight-black-eur-ps5-0711719022374"
    home_url = "https://www.e.leclerc/"
    settle_ms = 3000

    seller_ok = r"^E\.?\s?Leclerc$"
    BUYBOX = "#product-buybox"
    add_to_cart_selector = "#add-to-cart-btn"
    cookie_reject_selectors = ("#onetrust-reject-all-handler", "button#didomi-notice-disagree-button",
                               "button:has-text('Tout refuser')", "button:has-text('Continuer sans accepter')")

    login_patterns = [r"/connexion", r"/login", r"/identification", r"auth\.e\.leclerc", r"/mon-compte/connexion"]
    confirmation_patterns = [r"/confirmation", r"/commande/confirmation", r"merci", r"order-?complete"]

    cart_url = "https://www.e.leclerc/cart"
    checkout_steps = [
        ("click", "button:has-text('Choisir ma livraison')"),
        ("wait", 3),
        ("click_if", "button:has-text('Continuer'), button:has-text('Valider')"),
        ("wait", 3),
        ("click_if", "button:has-text('Continuer'), button:has-text('Valider')"),
    ]
    final_button_selector = ("button:has-text('Payer'), button:has-text('Valider et payer'), "
                             "button:has-text('Confirmer la commande')")
    total_selector = "text=/Total \\(dont T\\.V\\.A\\)/ >> xpath=../..  >> text=/€/"

    def check(self, page, url=None) -> dict:
        if url and url != self.url:
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
        bb = page.locator(self.BUYBOX).first
        if not bb.count():
            return {"in_stock": False}
        text = text_of(page, self.BUYBOX, 3000) or ""
        price = None
        try:
            price = float(bb.get_attribute("data-price"))
        except (TypeError, ValueError):
            pass

        header = re.search(r"Offre\s+(E\.?\s?Leclerc|Partenaire)", text, re.I)
        seller = None
        if header and header.group(1).lower().startswith("e"):
            seller = "E.Leclerc"
        else:
            m = re.search(r"Vendu par\s+([^\n]+)", text)
            seller = m.group(1).strip() if m else ("Partenaire" if header else None)

        # main offer block = text before the "seconde vie" (used/refurbished) section
        main = text.split("PRODUITS SECONDE VIE")[0]
        condition = "new" if re.search(r"\bNeuf\b|Offre E\.?\s?Leclerc", main) else None
        if re.search(r"Occasion|Reconditionn", main.split("Ajouter au panier")[0][-300:]):
            condition = "used"

        in_stock = self.add_to_cart_ready(page) and bool(re.search(r"En stock", main, re.I)) \
            and not self.out_of_stock_text.search(main)
        return {"in_stock": in_stock, "price": price, "seller": seller, "condition": condition}


ADAPTER = Leclerc
