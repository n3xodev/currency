import * as Chrome from "@point_of_sale/../tests/pos/tours/utils/chrome_util";
import * as ProductScreen from "@point_of_sale/../tests/pos/tours/utils/product_screen_util";
import * as PaymentScreen from "@point_of_sale/../tests/pos/tours/utils/payment_screen_util";
import * as FeedbackScreen from "@point_of_sale/../tests/pos/tours/utils/feedback_screen_util";
import { registry } from "@web/core/registry";

registry.category("web_tour.tours").add("PosPaymentCurrencyTour", {
    steps: () =>
        [
            Chrome.startPoS(),
            ProductScreen.addOrderline("Tour MC Product", "1"),
            ProductScreen.clickPayButton(),
            PaymentScreen.clickPaymentMethod("Bank EUR"),
            PaymentScreen.clickPaymentMethod("Bank EUR"),
            PaymentScreen.validateButtonIsHighlighted(true),
            PaymentScreen.clickValidate(),
            // Odoo 20 replaced the receipt screen by the feedback screen.
            FeedbackScreen.isShown(),
            FeedbackScreen.clickNextOrder(),
            ProductScreen.isShown(),
        ].flat(),
});
