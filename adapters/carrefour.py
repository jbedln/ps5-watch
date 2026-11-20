"""Carrefour.fr — only products sold AND shipped by Carrefour itself (no "Vendeurs partenaires").

Notes from testing (Nov 2026):
- Cloudflare Turnstile ("Un instant...") is served to HEADLESS Chromium. In a headed window the
  page loads normally, so run the real watcher headed (config `browser.headless: false`).
  Headless --check-once therefore shows BLOQUÉ captcha: expected, never bypassed.
- The JSON-LD is useless here: it lists "Carrefour Drive" InStock even when the product is
  sold out for delivery, plus marketplace offers. We ignore it and read the buybox instead.
- Buybox (`[data-testid=buybox]`) has 3 radio options: "Retrait magasin", "Livraison",
  "Vendeurs partenaires". The retailer's own stock = a visible "Ajouter au panier" button
  (`.add-to-cart button`). Without a store chosen, pickup shows a "Choisir un magasin"
  custom element instead (=> counted as not buyable). Home delivery needs no store:
  Livraison disabled = "Plus de stock". To also catch store pickup, choose a store once
  with `main.py --login --sites carrefour` (it is remembered in the profile).
- The product page has two copies of the add button (one hidden, sticky mobile): use :visible.
- Marketplace offers never get the Carrefour label: if the active option is "Vendeurs
  partenaires" (or a "Vendu par X" line appears) the seller is not Carrefour.
- Cart (anonymous add OK): header cart -> "Voir mon panier" -> /cart/livraison-unifiee
  ("Vendu et livré par Carrefour" shown per line). Steps: 1 panier, 2 livraison, 3 paiement.
  Signed out the main button (#data-validate-step-summary-resume) reads "Me connecter".
  VERIFIED: add to cart, cart URL, total/validate selectors. GUESSED: steps 2-3 and the
  final pay button (needs a signed-in --dry-run).
- Test product: Support vertical PS5 Sony (29,99 EUR), sold and delivered by Carrefour.
"""
from .base import Adapter, parse_price, text_of


class Carrefour(Adapter):
    name = "carrefour"
    label = "Carrefour"
    url = "https://www.carrefour.fr/p/console-ps5-pro-2-to-sony-0711719595472"      # CFI-7021, EAN ...5472
    test_url = "https://www.carrefour.fr/p/support-vertical-pour-consoles-ps5-sony-0711719579533"
    home_url = "https://www.carrefour.fr/"
    settle_ms = 3000

    seller_ok = r"^Carrefour$"
    BUYBOX = "[data-testid='buybox']"
    add_to_cart_selector = "[data-testid='buybox'] .add-to-cart button:visible"
    price_selector = "[data-testid='buybox'] [data-testid='product-price__amount--main']"
    cookie_reject_selectors = ("#onetrust-reject-all-handler", "button:has-text('Tout refuser')",
                               "button:has-text('Continuer sans accepter')")

    login_patterns = [r"/mon-compte/(connexion|login)", r"/connexion", r"/login", r"auth\.carrefour"]
    confirmation_patterns = [r"/confirmation", r"/commande/.*(merci|confirmation)", r"thank-?you"]

    cart_url = "https://www.carrefour.fr/cart/livraison-unifiee"
    checkout_steps = [
        ("click", "#data-validate-step-summary-resume"),            # "Me connecter" signed out, "Continuer" signed in
        ("wait", 3),
        ("click_if", "[data-testid='checkout-actions'] button:has-text('Continuer'), "
                     "[data-testid='checkout-actions'] button:has-text('Valider')"),
        ("wait", 3),
        ("click_if", "[data-testid='checkout-actions'] button:has-text('Continuer'), "
                     "[data-testid='checkout-actions'] button:has-text('Valider')"),
    ]
    final_button_selector = ("[data-testid='checkout-actions'] button:has-text('Payer'), "
                             "button:has-text('Confirmer et payer'), button:has-text('Valider et payer')")
    total_selector = "[data-testid='checkout-total']"

    def parse(self, page) -> dict:
        bb = self.BUYBOX
        # "899 / ,99 / €" are three <p>: glue them.
        raw = text_of(page, self.price_selector)
        price = parse_price(raw.replace("\n", "")) if raw else None

        active = (text_of(page, f"{bb} .buybox__option-btn--active") or "").lower()
        text = text_of(page, bb, 2500) or ""
        seller = "Carrefour"
        if "partenaire" in active:
            seller = "Vendeur partenaire (marketplace)"
        else:
            import re
            m = re.search(r"Vendu (?:et exp[ée]di[ée] )?par\s+([^\n]+)", text)
            if m:
                seller = m.group(1).strip()
        return {"in_stock": self.add_to_cart_ready(page), "price": price, "seller": seller,
                "condition": "new"}


ADAPTER = Carrefour
