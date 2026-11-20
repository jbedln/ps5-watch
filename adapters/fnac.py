"""Fnac.com (own stock + marketplace). Same group / same tech as Darty.

STATUS: PARTLY VERIFIED. DataDome is intermittent: the first PS5 Pro page load of a fresh
profile came through (headed), every later load got the captcha (geo.captcha-delivery.com),
and headless Chromium gets a fake "FNAC DARTY - Maintenance" page. We never bypass: both
are raised as Blocked (run shows BLOQUÉ). Verified from the one good load: URL, JSON-LD,
the out-of-stock DOM (see comments in the class). NOT verified: the in-stock DOM (add-to-cart
button inside the online buy box), the DualSense test page, cart and checkout. To confirm,
solve the captcha by hand in the persistent profile (`python main.py --login --sites fnac`)
then run `--check-once [--test] --sites fnac`.

Seller rule: only "Vendu et expédié par Fnac" / "Fnac.com". Marketplace offers read
"Vendu par <shop>" (and often "Expédié par <shop>").
Listings seen via search (Nov 2026): PS5 Pro blanc et noir = a20901133 (also appears as a
marketplace-only listing at ~1 599 €); the "Pack ... EA SPORTS FC 26" and "+ lecteur
Blu-ray" pages are bundles, not used.
Test product: Manette sans fil Sony DualSense blanche (a14119958).
"""
import re

from .base import Adapter, Blocked, jsonld_products


MAINTENANCE = re.compile(r"Maintenance|n'est actuellement pas disponible", re.I)


def fnac_darty_wall(page):
    """Headless Chromium gets a fake 'FNAC DARTY - Maintenance / site non disponible' page
    (no captcha frame, no JSON-LD). Never read it as 'rupture': raise Blocked."""
    try:
        title = page.title()
        body = page.locator("body").inner_text(timeout=2000)[:600]
    except Exception:
        return
    if MAINTENANCE.search(title) or "notre site n'est actuellement pas disponible" in body:
        raise Blocked("captcha", "page Maintenance servie à Chromium (anti-bot FnacDarty): headless ? captcha ?")


def ensure_ok_fnac_darty(adapter, page, in_checkout: bool):
    """Base blocker check, minus one false positive: DataDome also parks an INVISIBLE
    captcha-delivery iframe on pages that loaded fine (seen on Fnac: full product page +
    frame). Only trust the frame when no product JSON-LD is on the page or the iframe is
    actually visible."""
    try:
        Adapter.ensure_ok(adapter, page, in_checkout)
    except Blocked as b:
        if b.kind != "captcha" or "captcha-delivery" not in b.detail:
            raise
        shown = any(
            f is not page.main_frame and "captcha-delivery" in (f.url or "") and _frame_visible(f)
            for f in page.frames)
        if shown or not jsonld_products(page):
            raise
    fnac_darty_wall(page)


def _frame_visible(f) -> bool:
    try:
        return f.frame_element().is_visible()
    except Exception:
        return True


class Fnac(Adapter):
    name = "fnac"
    label = "Fnac"
    url = "https://www.fnac.com/Console-Sony-PS5-Pro-Blanc-et-Noir/a20901133/w-4"
    test_url = "https://www.fnac.com/Manette-sans-fil-Sony-DualSense-pour-PS5-Blanc/a14119958/w-4"
    home_url = "https://www.fnac.com/"

    # Verified on the out-of-stock PS5 Pro page (Nov 2026):
    #  - JSON-LD Product.offers = the Fnac offer: price 899.99, seller "FNAC.COM",
    #    availability OutOfStock.
    #  - online availability box = `.f-spot-web-desktop` ("Stock en ligne épuisé" with class
    #    f-buyBox__availabilityStatus--unavailable); the store-pickup box (`.f-spot-store`,
    #    "En stock en magasin" + a "Retrait" button, also data-automation-id=product-buy-btn)
    #    must NOT count as online stock.
    #  - Fnac's own offer = `.f-productOffers-fnac` (data-sellertype="fnac"), price in
    #    `.f-faPriceBox__price.userPrice`. Marketplace offers sit in `.f-faMpSeller` ("Vendu et
    #    livré par <shop>") and are never accepted.
    # GUESSED (page never loaded while in stock): the add-to-cart button inside the online box.
    price_selector = ".f-productOffers-fnac .f-faPriceBox__price.userPrice, .f-faPriceBox__price.userPrice"
    add_to_cart_selector = (".f-buyBox:has(.f-spot-web-desktop.f-buyBox__availabilityStatus--available) "
                            "button:has-text('Ajouter au panier')")
    out_of_stock_scope = ".f-spot-web-desktop"
    seller_ok = r"^Vendu et expédié par Fnac(?:\.com)?$"

    login_patterns = [r"/identification", r"/Account/Login", r"secure\.fnac\.com/.*[Ll]ogin", r"/connexion"]
    confirmation_patterns = [r"/Order/Confirmation", r"/confirmation", r"/merci"]

    # guessed: add to cart opens a pop-in with "Valider mon panier"
    checkout_steps = [
        ("wait", 2),
        ("click_if", "a:has-text('Valider mon panier'), button:has-text('Valider mon panier'), "
                     "a:has-text('Voir le panier')"),
        ("click_if", "a:has-text('Valider mon panier'), button:has-text('Valider mon panier'), "
                     "button:has-text('Commander'), a:has-text('Commander')"),
        ("click_if", "button:has-text('Continuer'), button:has-text('Valider et continuer')"),
        ("click_if", "button:has-text('Continuer'), button:has-text('Valider et continuer')"),
    ]
    final_button_selector = ("button:has-text('Payer'), button:has-text('Valider et payer'), "
                             "button:has-text('Confirmer ma commande')")
    total_selector = ".js-orderTotal, [class*='total' i] >> text=/€/"

    def ensure_ok(self, page, in_checkout: bool = False):
        ensure_ok_fnac_darty(self, page, in_checkout)

    def parse(self, page):
        d = super().parse(page)
        if page.locator(".f-productOffers-fnac").count() or (d.get("seller") or "").upper() == "FNAC.COM":
            d["seller"] = "Vendu et expédié par Fnac.com"
        else:
            mp = page.locator(".f-faMpSeller__name").first
            name = mp.inner_text().strip() if mp.count() else None
            d["seller"] = f"Vendu par {name}" if name else None
        return d


ADAPTER = Fnac
