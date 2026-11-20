import * as Chrome from "@point_of_sale/../tests/pos/tours/utils/chrome_util";
import * as Dialog from "@point_of_sale/../tests/generic_helpers/dialog_util";
import * as PaymentScreen from "@point_of_sale/../tests/pos/tours/utils/payment_screen_util";
import * as ProductScreen from "@point_of_sale/../tests/pos/tours/utils/product_screen_util";
import * as FeedbackScreen from "@point_of_sale/../tests/pos/tours/utils/feedback_screen_util";
import { registry } from "@web/core/registry";

const CLOSING_POPUP = ".modal .close-pos-popup";

function fillCountedCash(index, value) {
    return {
        content: `Type ${value} as the counted amount of cash method #${index}`,
        trigger: `${CLOSING_POPUP} .cash-input:eq(${index}) input`,
        run: `edit ${value}`,
    };
}

registry.category("web_tour.tours").add("PosClosingCountedCashByMethodTour", {
    steps: () =>
        [
            Chrome.startPoS(),
            Dialog.confirm("Open Register"),
            ProductScreen.addOrderline("Tour Closing Product", "1"),
            ProductScreen.clickPayButton(),
            PaymentScreen.clickPaymentMethod("Cash"),
            PaymentScreen.clickValidate(),
            // Odoo 20 replaced the receipt screen by the feedback screen.
            FeedbackScreen.isShown(),
            FeedbackScreen.clickNextOrder(),
            ProductScreen.isShown(),
            ...Chrome.clickMenuOption("Close Register"),
            {
                content: "Closing popup lists a count input per cash method",
                trigger: `${CLOSING_POPUP} .cash-input:eq(1) input`,
            },
            fillCountedCash(0, "10"),
            fillCountedCash(1, "8"),
            Dialog.confirm("Close Register"),
            {
                content: "Accept the counting difference",
                trigger: ".modal button:contains('Proceed Anyway')",
                run: "click",
                // Core leaves through `router.close()`, a full page navigation.
                expectUnloadPage: true,
            },
            // After closing, core navigates to /pos/ui/<config> (router.close()),
            // which shows the login screen of the next session.
            Chrome.startPoS(),
            Chrome.endTour(),
        ].flat(),
});
