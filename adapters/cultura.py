"""Cultura.com. Marketplace site: the buy box often shows a MARKETPLACE seller, so the seller
check is the critical rule here (only "Vendu et expédié par : Cultura").

Notes from testing (Nov 2026):
- Cloudflare: headless Chromium gets the "Vérification de sécurité" challenge (detected as a captcha ->
  BLOQUÉ). Headed Chromium passes, BUT the first request(s) of a fresh session often return a bare
  "405 Method Not Allowed" page (173 bytes). Waiting ~8-16 s and reloading works. goto() retries up to
  3 times and then raises Blocked (so a persistent 405 is shown as BLOQUÉ, never as a false "rupture").
  The persistent profile (cookies) should make this rarer in the real run.
- When Cultura itself has no stock ("front_availability":"unavailable") the page shows the cheapest
  marketplace offer in the buy box, and the JSON-LD (InStock, price 1649...) describes THAT offer. Seen
  for the PS5 Pro: buy box = "Vendu et expédié par : EveryDeal", 1649 €. The seller is therefore read from
  `.cro-neo-container__soldby`; for Cultura-sold items it is plain text (no link) "Vendu et expédié par :
  Cultura", for marketplace the seller name is a link.
- The Cultura-sold OOS state shows the "Alerte stock" container ("indisponible en ligne") and no
  `.addToCartPdp` button. In stock, the button `.addToCartPdp` has the price in `.span_price`.
- Condition: `.cro-neo-container__state` "État : Neuf". Used offers exist (marketplace) -> condition "used".
- Cart: /checkout (the "mon panier" link of the add-to-cart notification). Adding the test product
  anonymously works. The checkout buttons are GUESSED (never tested: needs an account).
- Test product: Astérix tome 1 (book, sold by Cultura, in stock): no DualSense is sold by Cultura itself
  right now (all marketplace). Swap in `config.yaml` (sites.cultura.test_url) if needed.
"""
import re
import time

from .base import Adapter, Blocked, text_of

_BAD_PAGE = re.compile(r"^\s*405 Method Not Allowed", re.I)


class Cultura(Adapter):
    name = "cultura"
    label = "Cultura"
    url = "https://www.cultura.com/p-console-sony-playstation-5-pro-2tb-12685100.html"
    test_url = "https://www.cultura.com/p-asterix-t-1-asterix-le-gaulois-9782012101333.html"
    home_url = "https://www.cultura.com/"
    settle_ms = 3500

    seller_ok = r"^Vendu et expédié par\s*:?\s*Cultura$"
    seller_selector = "#pdp-availability .cro-neo-container__soldby"
    add_to_cart_selector = "#pdp-availability button.addToCartPdp"
    price_selector = None                  # parsed in parse(): base.parse_price() mangles "1649,00€" -> 164
    out_of_stock_scope = "#pdp-availability"
    cookie_reject_selectors = ("button:has-text('Continuer sans accepter')", "button:has-text('Tout refuser')")

    login_patterns = [r"/login", r"/connexion", r"/identification", r"/customer/account/login"]
    confirmation_patterns = [r"/checkout/success", r"/checkout/confirmation", r"order-?confirmation", r"merci"]

    # GUESSED after /checkout (cart page).
    cart_url = "https://www.cultura.com/checkout"
    checkout_steps = [
        ("click", "button:has-text('Commander'), a:has-text('Commander'), button:has-text('Passer la commande'), "
                  "a:has-text('Passer la commande'), button:has-text('Valider mon panier')"),
        ("wait", 3),
        ("click_if", "button:has-text('Continuer'), button:has-text('Suivant')"),
        ("click_if", "button:has-text('Continuer'), button:has-text('Suivant')"),
    ]
    final_button_selector = ("button:has-text('Payer'), button:has-text('Confirmer la commande'), "
                             "button:has-text('Valider et payer')")
    total_selector = ".total-price, [class*='grand-total'], [class*='order-total']"

    def _bad_page(self, page) -> bool:
        try:
            return bool(_BAD_PAGE.search(page.locator("body").inner_text(timeout=2000)[:200]))
        except Exception:
            return False

    def goto(self, page, url: str):
        for attempt in range(3):
            page.goto(url, wait_until="domcontentloaded", timeout=45000)
            try:
                page.wait_for_load_state("networkidle", timeout=8000)
            except Exception:
                pass
            page.wait_for_timeout(2500)          # the 405 can replace the page a moment after load
            if not self._bad_page(page):
                break
            if attempt < 2:
                time.sleep(8 + 4 * attempt)
        else:
            raise Blocked("captcha", "Cloudflare: 405 Method Not Allowed (x3)")
        if self.settle_ms:
            page.wait_for_timeout(self.settle_ms)
        self.reject_cookies(page)
        self.ensure_ok(page)

    def parse(self, page) -> dict:
        d = super().parse(page)
        seller = text_of(page, self.seller_selector)
        if seller:
            d["seller"] = re.sub(r"\s+", " ", seller.replace("\xa0", " ")).strip()
        state = text_of(page, "#pdp-availability .cro-neo-container__state") or ""
        if re.search(r"occasion|reconditionn|bon état|très bon|comme neuf", state, re.I) or (
                state and not re.search(r"neuf", state, re.I)):
            d["condition"] = "used"
        elif state:
            d["condition"] = "new"
        raw = (text_of(page, "#pdp-availability button.addToCartPdp .span_price")
               or text_of(page, ".pdp-formats .price--big") or "")
        m = re.search(r"(\d[\d\s\u202f]*)[,.](\d{2})", raw.replace("\xa0", " "))
        if m:
            d["price"] = float(re.sub(r"\D", "", m.group(1)) + "." + m.group(2))
        return d


ADAPTER = Cultura
