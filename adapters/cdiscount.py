"""Cdiscount. Huge marketplace: ONLY accept "Vendu par Cdiscount" (never a marketplace seller, even if
"Expédié par Cdiscount").

Notes from testing (Nov 2026):
- Headless Chromium gets an "Accès bloqué" page (RayID...). Headed Chromium passes. The block page is
  detected -> Blocked (BLOQUÉ in the table), never a false "rupture". Run with browser.headless: false.
- JSON-LD is `"@type":"product"` (lowercase!), so base.jsonld_products() misses it: parse() reads
  it itself. offers = {availability, itemCondition, price} of the buy-box offer. No seller in JSON-LD.
- Seller: `[data-e2e="product-shipping"]` text. Marketplace: "Vendu et expédié par SuperPromos" (seller
  name, "Vendeur basé à ..."). Cdiscount own offer: "Livré par Cdiscount" and NO "Vendu ... par" line.
  parse() builds "Vendu par <seller>", or "Vendu par Cdiscount" when only "Livré/Expédié par Cdiscount"
  is there. Unknown layout -> seller None -> "vendeur introuvable" (safe side).
- Out of stock: `[data-e2e="unavailable-message"]` "Actuellement indisponible" + JSON-LD OutOfStock, and the
  main button `[data-e2e="product-add-to-cart"]` is absent. Beware: carousels contain other "Ajouter"
  buttons (without data-e2e), never match on text.
- PS5 Pro page (f-1035001-ps5prov2, CFI-7121 revision per the listing) was OutOfStock at 1700 EUR.
- Test product: DualSense Midnight Black (ps5dsblackv3), new, 54,99 EUR, "Livré par Cdiscount".
- Checkout (cart URL and buttons) is GUESSED, never tested (needs an account).
"""
import json
import re

from .base import Adapter, Blocked, text_of


class Cdiscount(Adapter):
    name = "cdiscount"
    label = "Cdiscount"
    url = "https://www.cdiscount.com/jeux-pc-video-console/ps5/console-playstation-5-pro/f-1035001-ps5prov2.html"
    test_url = ("https://www.cdiscount.com/informatique/gaming/manette-sans-fil-dualsense-r-midnight-black-i-p/"
                "f-1071403-ps5dsblackv3.html")
    home_url = "https://www.cdiscount.com/"
    settle_ms = 2500

    seller_ok = r"^Vendu (?:et expédié )?par Cdiscount$"
    seller_selector = None                 # computed in parse()
    add_to_cart_selector = "[data-e2e='product-add-to-cart']"
    price_selector = None                  # JSON-LD price
    out_of_stock_scope = "[data-e2e='unavailable-message']"
    cookie_reject_selectors = ("#footer_tc_privacy_button_2", "button:has-text('Tout refuser')",
                               "button:has-text('Continuer sans accepter')", "button:has-text('Refuser')")

    login_patterns = [r"/login", r"/connexion", r"/identification", r"/Authentification"]
    confirmation_patterns = [r"/confirmation", r"order-?confirmation", r"/merci", r"thank-?you"]

    # GUESSED.
    cart_url = "https://www.cdiscount.com/Basket.html"
    checkout_steps = [
        ("click", "button:has-text('Valider mon panier'), a:has-text('Valider mon panier'), "
                  "button:has-text('Commander'), a:has-text('Commander')"),
        ("wait", 3),
        ("click_if", "button:has-text('Continuer'), button:has-text('Suivant')"),
        ("click_if", "button:has-text('Continuer'), button:has-text('Suivant')"),
    ]
    final_button_selector = ("button:has-text('Payer'), button:has-text('Confirmer la commande'), "
                             "button:has-text('Valider et payer')")
    total_selector = "[data-e2e*='total' i], .totalAmount, [class*='grandTotal']"

    def ensure_ok(self, page, in_checkout: bool = False):
        try:
            title = page.title()
            body = page.locator("body").inner_text(timeout=2000)[:600]
        except Exception:
            title, body = "", ""
        if re.search(r"Accès bloqué", title + " " + body[:200]) and "RayID" in body:
            raise Blocked("captcha", "Cdiscount: Accès bloqué (RayID)")
        super().ensure_ok(page, in_checkout)

    @staticmethod
    def _offer(page) -> dict:
        for raw in page.locator('script[type="application/ld+json"]').all_text_contents():
            try:
                node = json.loads(raw)
            except (json.JSONDecodeError, TypeError):
                continue
            for n in (node if isinstance(node, list) else [node]):
                if isinstance(n, dict) and str(n.get("@type", "")).lower() == "product":
                    o = n.get("offers")
                    o = o[0] if isinstance(o, list) and o else o
                    if isinstance(o, dict):
                        return o
        return {}

    def parse(self, page) -> dict:
        o = self._offer(page)
        avail = str(o.get("availability", ""))
        cond = str(o.get("itemCondition", ""))
        d = {
            "price": float(o["price"]) if o.get("price") not in (None, "") else None,
            "condition": ("new" if "NewCondition" in cond else
                          "used" if re.search(r"Used|Refurbished|Damaged", cond) else None),
        }
        ship = text_of(page, "[data-e2e='product-shipping']", 2500) or ""
        ship = re.sub(r"\s+", " ", ship.replace("\xa0", " "))
        m = re.search(r"Vendu (?:et expédié )?par\s+(.+?)(?:\s+Vendeur basé|\s+Livraison|\s+Expédié|\s+Retour|$)", ship)
        if m:
            d["seller"] = f"Vendu par {m.group(1).strip()}"
        elif re.search(r"(?:Livré|Expédié) par Cdiscount", ship):
            d["seller"] = "Vendu par Cdiscount"
        unavailable = page.locator(self.out_of_stock_scope).count() > 0
        signals = [self.add_to_cart_ready(page), not unavailable]
        if avail:
            signals.append("InStock" in avail)
        d["in_stock"] = all(signals)
        return d


ADAPTER = Cdiscount
