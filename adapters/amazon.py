"""Amazon.fr — only "Expédié par Amazon" AND "Vendu par Amazon"."""
from .base import Adapter, parse_price, text_of


class Amazon(Adapter):
    name = "amazon"
    label = "Amazon.fr"
    url = "https://www.amazon.fr/dp/B0DHSV68YZ"          # PS5 Pro 2 To, CFI-7021
    test_url = "https://www.amazon.fr/dp/B08H99BPJN"     # DualSense
    home_url = "https://www.amazon.fr/"

    seller_ok = r"^Expédié par Amazon(\.fr)? / Vendu par Amazon(\.fr)?$"
    add_to_cart_selector = "#add-to-cart-button"
    price_selector = ("#corePrice_feature_div .a-price .a-offscreen, "
                      "#corePriceDisplay_desktop_feature_div .a-price .a-offscreen, "
                      "#apex_desktop .apex-pricetopay-value .a-offscreen")
    out_of_stock_scope = "#availability"
    cookie_reject_selectors = ("#sp-cc-rejectall-link", "button:has-text('Refuser')")

    login_patterns = [r"/ap/signin", r"/ap/mfa", r"/ap/cvf", r"/errors/validateCaptcha"]
    confirmation_patterns = [r"/thankyou", r"/buy/thankyou", r"/gp/buy/spc/handlers/static-submit"]

    cart_url = "https://www.amazon.fr/gp/cart/view.html"
    checkout_steps = [
        ("click", "input[name='proceedToRetailCheckout'], #sc-buy-box-ptc-button input"),
        ("wait", 3),
        # Amazon sometimes inserts Prime / delivery upsells: always refuse.
        ("click_if", "#prime-decline-button, a:has-text('Non merci'), button:has-text('Non merci')"),
    ]
    final_button_selector = ("#submitOrderButtonId input, input[name='placeYourOrder1'], "
                             "#placeOrder, #bottomSubmitOrderButtonId input")
    total_selector = ("#subtotals-marketplace-table .grand-total-price, "
                      "#subtotals-marketplace-table tr:last-child td.a-text-right")

    def parse(self, page):
        d = super().parse(page)
        ships = text_of(page, "#fulfillerInfoFeature_feature_div .offer-display-feature-text-message")
        sold = text_of(page, "#merchantInfoFeature_feature_div .offer-display-feature-text-message")
        # When both are the same, Amazon shows one row labelled "Expéditeur / Vendeur".
        label = text_of(page, "#merchantInfoFeature_feature_div") or ""
        if sold and not ships and "Expéditeur / Vendeur" in label:
            ships = sold
        if ships or sold:
            d["seller"] = f"Expédié par {ships or '?'} / Vendu par {sold or '?'}"
        # Buybox on a used offer => never.
        if page.locator("#usedBuySection, #usedbuyBox").count() and not page.locator("#newAccordionRow, #qualifiedBuybox").count():
            d["condition"] = "used"
        else:
            d["condition"] = d.get("condition") or "new"
        if d.get("price") is None:
            d["price"] = parse_price(text_of(page, "#corePrice_desktop .a-offscreen"))
        return d

    def add_to_cart(self, page):
        super().add_to_cart(page)
        # Protection / warranty side sheet: decline.
        for sel in ("#attachSiNoCoverage", "#attach-close_sideSheet-link", "button:has-text('Non merci')"):
            try:
                b = page.locator(sel).first
                if b.count() and b.is_visible():
                    b.click(timeout=3000)
                    break
            except Exception:
                pass


ADAPTER = Amazon
