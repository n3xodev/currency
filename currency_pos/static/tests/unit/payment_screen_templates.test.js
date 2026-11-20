import { describe, expect, test } from "@odoo/hoot";
import { applyInheritance } from "@web/core/template_inheritance";

const parser = new DOMParser();
const serializer = new XMLSerializer();

function applyTemplateInheritance(arch, operations) {
    const archXmlDoc = parser.parseFromString(arch, "text/xml");
    const inheritsDoc = parser.parseFromString(operations, "text/xml");
    const modifiedTemplate = applyInheritance(
        archXmlDoc.documentElement,
        inheritsDoc.documentElement,
        "currency_pos/test"
    );
    return serializer.serializeToString(modifiedTemplate);
}

// The architectures below are the structure of the Odoo 20 templates
// (point_of_sale/static/src/app/screens/payment_screen/*) the module inherits from,
// and the operations are the ones of static/src/app/screens/payment_screen/payment_screen.xml.
const PAYMENT_AMOUNT_REPLACEMENT = `<div class="payment-amount px-3 text-end">
    <t t-if="line.isForeignCurrencyPayment?.()">
        <div class="lh-sm">
            <t t-out="this.getPaymentLineForeignAmountDisplay(line)"/>
        </div>
        <div class="small text-muted lh-sm">
            <t t-out="this.getPaymentLineOrderAmountDisplay(line)"/>
        </div>
    </t>
    <t t-else="">
        <t t-out="this.getPaymentLineOrderAmountDisplay(line)"/>
    </t>
</div>`;

const PAYMENT_SCREEN_PAYMENT_LINES_ARCH = `<t t-name="point_of_sale.PaymentScreenPaymentLines">
    <div t-if="this.paymentLines.length" class="paymentlines flex-grow-1 d-flex flex-column overflow-y-auto gap-2">
        <t t-foreach="this.paymentLines" t-as="line" t-key="line.uuid">
            <div class="paymentline d-flex align-items-center rounded-3">
                <div class="payment-infos d-flex align-items-center justify-content-between flex-grow-1 px-3 py-3 text-truncate cursor-pointer fs-2">
                    <span class="payment-name">
                        <t t-out="line.displayName" />
                    </span>
                    <div class="payment-amount px-3">
                        <PriceFormatter price="this.getFormattedPrice(line)" />
                    </div>
                </div>
            </div>
        </t>
    </div>
</t>`;

const PAYMENT_SCREEN_STATUS_ARCH = `<t t-name="point_of_sale.PaymentScreenStatus">
    <div t-if="this.props.order.payment_ids.length == 0">Please select a payment method</div>
    <section t-elif="this.showStatus" class="paymentlines-container border-top pt-3">
        <div t-if="this.showStatus" class="payment-status-container d-flex flex-column-reverse flex-lg-row justify-content-between fs-2">
            <div class="payment-status-amount d-flex justify-content-between flex-grow-1 px-1">
                <span class="label pe-2" t-out="this.order.remainingDueLabel" />
                <span class="amount align-self-end highlight fw-bolder">
                    <PriceFormatter price="this.amountText" />
                </span>
            </div>
        </div>
    </section>
</t>`;

const PAYMENT_SCREEN_DUE_ARCH = `<t t-name="point_of_sale.PaymentScreenDue">
    <section class="paymentlines-container fw-bold">
        <div class="total text-center text-dark">
            <PriceFormatter price="this.orderTotalDue" />
        </div>
    </section>
</t>`;

const PAYMENT_SCREEN_PAYMENT_LINES_OPERATIONS = `<t t-inherit="point_of_sale.PaymentScreenPaymentLines" t-inherit-mode="extension">
    <xpath expr="//span[hasclass('payment-name')]/following-sibling::div[hasclass('payment-amount')]" position="replace">
        ${PAYMENT_AMOUNT_REPLACEMENT}
    </xpath>
</t>`;

const PAYMENT_SCREEN_STATUS_OPERATIONS = `<t t-inherit="point_of_sale.PaymentScreenStatus" t-inherit-mode="extension">
    <xpath expr="//div[hasclass('payment-status-container')]" position="before">
        <div t-if="this.getPaymentStatusCurrencyLabel()" class="text-muted small pb-2">
            Entering amount in <t t-out="this.getPaymentStatusCurrencyLabel()"/>
        </div>
    </xpath>
</t>`;

const PAYMENT_SCREEN_DUE_OPERATIONS = `<t t-inherit="point_of_sale.PaymentScreenDue" t-inherit-mode="extension">
    <xpath expr="//section[hasclass('paymentlines-container')]" position="attributes">
        <attribute name="class" add="position-relative" separator=" "/>
    </xpath>
    <xpath expr="//div[hasclass('total')]" position="before">
        <div t-if="this.getPaymentCurrencyRateLabels().length"
            class="o_currency_pos_payment_rates position-absolute top-0 end-0 m-2 text-start text-muted fs-6 lh-sm">
            <div t-foreach="this.getPaymentCurrencyRateLabels()" t-as="rateLabel" t-key="rateLabel_index"
                t-out="rateLabel"/>
        </div>
    </xpath>
</t>`;

describe("currency_pos payment screen templates", () => {
    test("PaymentScreenStatus inheritance applies without xpath errors", () => {
        const result = applyTemplateInheritance(
            PAYMENT_SCREEN_STATUS_ARCH,
            PAYMENT_SCREEN_STATUS_OPERATIONS
        );
        expect(result).toInclude("this.getPaymentStatusCurrencyLabel()");
        expect(result).toInclude("payment-status-container");
    });

    test("PaymentScreenDue inheritance shows rate labels without xpath errors", () => {
        const result = applyTemplateInheritance(
            PAYMENT_SCREEN_DUE_ARCH,
            PAYMENT_SCREEN_DUE_OPERATIONS
        );
        expect(result).toInclude("this.getPaymentCurrencyRateLabels()");
        expect(result).toInclude("o_currency_pos_payment_rates");
        expect(result).toInclude("position-relative");
    });

    test("PaymentScreenPaymentLines inheritance applies without xpath errors", () => {
        const result = applyTemplateInheritance(
            PAYMENT_SCREEN_PAYMENT_LINES_ARCH,
            PAYMENT_SCREEN_PAYMENT_LINES_OPERATIONS
        );
        expect(result).toInclude("this.getPaymentLineForeignAmountDisplay(line)");
        expect(result).toInclude("this.getPaymentLineOrderAmountDisplay(line)");
        expect(result).not.toInclude("PriceFormatter");
    });
});
