"""PlayStation Direct FR (sold by Sony itself, no marketplace).

Notes from testing (Nov 2026):
- The JSON-LD in the HTML is server-cached. The real stock is set client side a few
  seconds later on the main CTA (`data-qa="mfeCtaMain#..."`). We wait, then require
  JSON-LD InStock + a clickable main CTA + no "Non disponible" in the offer block.
- The CTA label changes ("Ajouter au panier", "Faire une affaire" during deals...),
  so we target it by data-qa, not by text.
- Add to cart needs a signed-in PSN account. Signed out, the cart drawer shows
  "Une erreur s'est produite." -> we treat it as a login problem.
"""
from .base import Adapter, Blocked, visible


class PlayStation(Adapter):
    name = "playstation"
    label = "PlayStation Direct"
    url = "https://www.playstation.com/fr-fr/ps5/ps5-pro/buy-now/"
    test_url = "https://www.playstation.com/fr-fr/accessories/dualsense-wireless-controller/buy-now/"
    home_url = "https://www.playstation.com/fr-fr/"
    settle_ms = 6000

    default_seller = "PlayStation Direct"
    seller_ok = r"^PlayStation Direct$"
    add_to_cart_selector = "button[data-qa='mfeCtaMain#cta#action']"
    out_of_stock_scope = "[data-qa='mfeCtaMain#offer0']"
    price_selector = "[data-qa='mfeCtaMain#offer0#finalPrice']"
    cookie_reject_selectors = ("#onetrust-reject-all-handler", ".ot-pc-refuse-all-handler",
                               "button:has-text('Tout refuser')")

    login_patterns = [r"my\.account\.sony\.com", r"/signin", r"/oauth"]
    confirmation_patterns = [r"/confirmation", r"order-?confirmation", r"thank-?you"]

    # Cart = side drawer, checkout on the same domain. Selectors by text: to confirm
    # once with `--dry-run` while signed in (they may need a tweak).
    checkout_steps = [
        ("wait", 3),
        ("click", "button:has-text('Paiement'), a:has-text('Paiement'), button:has-text('Passer la commande'), "
                  "a:has-text('Passer la commande'), button:has-text('Commander'), a:has-text('Voir le panier')"),
        ("click_if", "button:has-text('Paiement'), a:has-text('Paiement'), button:has-text('Passer la commande')"),
        ("click_if", "button:has-text('Continuer'), button:has-text('Suivant')"),
        ("click_if", "button:has-text('Continuer'), button:has-text('Suivant')"),
    ]
    final_button_selector = ("button:has-text('Payer maintenant'), button:has-text('Confirmer la commande'), "
                             "button:has-text('Confirmer l\\'achat'), button:has-text('Passer la commande')")
    total_selector = "[data-qa*='total' i] >> text=/€/"

    def add_to_cart(self, page):
        super().add_to_cart(page)
        page.wait_for_timeout(3000)
        if visible(page, "text=Une erreur s'est produite"):
            raise Blocked("login", "panier PlayStation en erreur (compte PSN déconnecté ?)")


ADAPTER = PlayStation
