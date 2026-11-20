from math import copysign

from odoo import _, api, fields, models
from odoo.exceptions import ValidationError
from odoo.tools import float_compare


class PosPaymentMethod(models.Model):
    _inherit = "pos.payment.method"

    payment_currency_id = fields.Many2one(
        "res.currency",
        string="Payment Currency",
        compute="_compute_payment_currency_id",
        store=True,
        readonly=True,
    )
    inbound_payment_method_line_id = fields.Many2one(
        "account.payment.method.line",
        string="Incoming Payment Method",
        domain="[('journal_id', '=', journal_id), ('payment_type', '=', 'inbound')]",
        check_company=True,
        help="Accounting payment method line used for cash in / incoming receipts on this journal.",
    )
    outbound_payment_method_line_id = fields.Many2one(
        "account.payment.method.line",
        string="Outgoing Payment Method",
        domain="[('journal_id', '=', journal_id), ('payment_type', '=', 'outbound')]",
        check_company=True,
        help="Accounting payment method line used for cash out / outgoing payments on this journal.",
    )
    inbound_payment_account_id = fields.Many2one(
        related="inbound_payment_method_line_id.payment_account_id",
        string="Outstanding Receipts Account",
        readonly=True,
    )
    outbound_payment_account_id = fields.Many2one(
        related="outbound_payment_method_line_id.payment_account_id",
        string="Outstanding Payments Account",
        readonly=True,
    )

    @api.depends("journal_id", "journal_id.currency_id", "company_id", "company_id.currency_id")
    def _compute_payment_currency_id(self):
        for method in self:
            if method.journal_id and method.journal_id.currency_id:
                method.payment_currency_id = method.journal_id.currency_id
            else:
                method.payment_currency_id = method.company_id.currency_id

    @api.constrains("config_ids", "type", "journal_id")
    def _check_cash_method_single_shop(self):
        """Keep core's rule that a cash method belongs to one shop, but allow
        several cash methods (one per currency) in the same shop."""
        for method in self:
            is_cash = method.type == "cash" or method.journal_id.type == "cash"
            if is_cash and len(method.config_ids) > 1:
                raise ValidationError(
                    _(
                        "You cannot assign the same Cash payment method to multiple "
                        "POS Shops. Please create a separate Cash payment method for "
                        "each shop."
                    )
                )

    @api.onchange("journal_id")
    def _onchange_journal_id_payment_method_lines(self):
        for method in self:
            method._oca_sync_payment_method_lines_from_journal()

    def _oca_sync_payment_method_lines_from_journal(self):
        for method in self:
            journal = method.journal_id
            if not journal:
                method.inbound_payment_method_line_id = False
                method.outbound_payment_method_line_id = False
                continue
            inbound_lines = journal.inbound_payment_method_line_ids
            outbound_lines = journal.outbound_payment_method_line_ids
            if (
                not method.inbound_payment_method_line_id
                or method.inbound_payment_method_line_id.journal_id != journal
            ):
                method.inbound_payment_method_line_id = inbound_lines[:1]
            if (
                not method.outbound_payment_method_line_id
                or method.outbound_payment_method_line_id.journal_id != journal
            ):
                method.outbound_payment_method_line_id = outbound_lines[:1]

    @api.model_create_multi
    def create(self, vals_list):
        methods = super().create(vals_list)
        methods._oca_sync_payment_method_lines_from_journal()
        return methods

    def write(self, vals):
        result = super().write(vals)
        if "journal_id" in vals:
            self._oca_sync_payment_method_lines_from_journal()
        return result

    @api.model
    def _load_pos_data_fields(self, config_id):
        fields_list = super()._load_pos_data_fields(config_id)
        for field_name in (
            "payment_currency_id",
            "inbound_payment_method_line_id",
            "outbound_payment_method_line_id",
        ):
            if field_name not in fields_list:
                fields_list.append(field_name)
        return fields_list

    def is_foreign_currency_for_config(self, config):
        self.ensure_one()
        if not config or not config.allow_multi_currency_payment:
            return False
        return self.payment_currency_id != config.currency_id

    def _oca_get_cash_move_payment_method_line(self, move_type):
        self.ensure_one()
        journal = self.journal_id
        if move_type == "in":
            return (
                self.inbound_payment_method_line_id
                or journal.inbound_payment_method_line_ids[:1]
            )
        return (
            self.outbound_payment_method_line_id
            or journal.outbound_payment_method_line_ids[:1]
        )

    def _oca_get_default_outstanding_account(self, payment_type):
        self.ensure_one()
        account_ref = (
            "account_journal_payment_debit_account_id"
            if payment_type == "inbound"
            else "account_journal_payment_credit_account_id"
        )
        chart_template = self.with_context(
            allowed_company_ids=self.company_id.root_id.ids
        ).env["account.chart.template"]
        return (
            chart_template.ref(account_ref, raise_if_not_found=False)
            or self.company_id.transfer_account_id
        )

    def _oca_get_cash_move_counterpart_account(self, move_type):
        self.ensure_one()
        line = self._oca_get_cash_move_payment_method_line(move_type)
        if line.payment_account_id:
            return line.payment_account_id
        if not line:
            return self.env["account.account"]
        payment_type = "inbound" if move_type == "in" else "outbound"
        return self._oca_get_default_outstanding_account(payment_type)

    def _oca_get_payment_outstanding_account_for_amount(self, amount):
        """Outstanding account of a bank payment: receipts and refunds use the
        account of the inbound/outbound payment method line, falling back (like
        core) to the outstanding account of the method."""
        self.ensure_one()
        line = self._oca_get_cash_move_payment_method_line("in" if amount >= 0 else "out")
        return line.payment_account_id or self.outstanding_account_id

    ##############################################################
    #                 Accounting related methods                 #
    ##############################################################
    def _create_cash_payment_line(
        self,
        session,
        amount,
        account=None,
        message=None,
        partner=None,
        foreign_currency=None,
        amount_currency=None,
    ):
        """Book a cash line on the journal of a cash box.

        Core 20 books the line on the session bank statement with the amount in
        the order currency, which only fits the primary cash method when its
        journal is in the order currency. The other cash boxes (and a primary
        box on a foreign journal) have no statement and their journal amount is
        in the journal currency:

        - with a counterpart `account` (payment of an order) `amount` is in the
          order currency and the line takes the amount the customer handed over
          in the journal currency, the order amount becomes the foreign amount;
        - without it (cash difference) `amount` is already in the journal
          currency.
        """
        self.ensure_one()
        journal_currency = self.journal_id.currency_id or self.company_id.currency_id
        is_primary = self == session._oca_primary_cash_payment_method()
        order_currency = session.currency_id
        if is_primary and journal_currency == order_currency:
            return super()._create_cash_payment_line(
                session, amount, account, message, partner, foreign_currency, amount_currency
            )

        journal = self.journal_id
        today = fields.Date.context_today(self)
        statement_amount = amount
        statement_foreign_currency = False
        statement_foreign_amount = 0.0
        if account and journal_currency == order_currency:
            if foreign_currency and amount_currency:
                statement_foreign_currency = foreign_currency
                statement_foreign_amount = copysign(amount_currency, amount)
        elif account:
            if foreign_currency == journal_currency.id and amount_currency:
                statement_amount = copysign(amount_currency, amount)
            else:
                statement_amount = order_currency._convert(
                    amount, journal_currency, self.company_id, today
                )
            statement_foreign_currency = order_currency.id
            statement_foreign_amount = amount
        destination_account = account or (
            journal.profit_account_id if amount > 0 else journal.loss_account_id
        )
        session_ref = message or _(
            "%(payment_method)s POS session %(session)s",
            payment_method=self.name,
            session=session.name,
        )
        statement_line = (
            self.env["account.bank.statement.line"]
            .with_context(no_retrieve_partner=True)
            .sudo()
            .create(
                {
                    "amount": statement_amount,
                    "amount_currency": statement_foreign_amount,
                    "foreign_currency_id": statement_foreign_currency,
                    "company_id": session.company_id.id,
                    "journal_id": journal.id,
                    "date": today,
                    "partner_id": partner.id if partner else None,
                    "statement_id": session.bank_statement_id.id if is_primary else False,
                    "pos_session_id": session.id,
                    "counterpart_account_id": destination_account.id,
                    "payment_ref": session_ref,
                }
            )
        )
        statement_line.move_id.ref = session_ref
        return statement_line.move_id.line_ids.filtered(
            lambda line: line.account_id == destination_account
        )

    def _create_bank_payment_line(
        self,
        session,
        amount,
        account=None,
        message=None,
        partner=None,
        foreign_currency=None,
        amount_currency=None,
    ):
        """Use the outstanding account of the inbound/outbound payment method line.

        Core 20 always uses the outstanding account of the payment method, for
        receipts and refunds alike.

        CORE REIMPLEMENTATION: the custom path below repeats
        odoo/addons/point_of_sale/models/pos_payment_method.py:506-559
        (`_create_bank_payment_line`) of image
        odoo:20.0@sha256:8bcae4c1f895683ee851e19dd3e7d999e81e770defe9015bc9dad8bbf10f2b0d
        with another outstanding account. Re-diff it on every upgrade of the base image.
        """
        self.ensure_one()
        outstanding_account = self._oca_get_payment_outstanding_account_for_amount(amount)
        if not outstanding_account or outstanding_account == self.outstanding_account_id:
            return super()._create_bank_payment_line(
                session, amount, account, message, partner, foreign_currency, amount_currency
            )

        # Same payment as core's `_create_bank_payment_line`, with the outstanding
        # account chosen above.
        destination_account = (
            account or self.receivable_account_id or session._get_receivable_account()
        )
        rounding = session.currency_id.rounding
        payment_vals = {
            "amount": abs(amount),
            "journal_id": self.journal_id.id,
            "force_outstanding_account_id": outstanding_account.id,
            "destination_account_id": destination_account.id,
            "memo": message
            or _(
                "%(payment_method)s POS session %(session)s",
                payment_method=self.name,
                session=session.name,
            ),
            "pos_payment_method_id": self.id,
            "pos_session_id": session.id,
            "partner_id": partner.id if partner else None,
            "company_id": self.company_id.id,
        }
        if foreign_currency and amount_currency:
            payment_vals.update(
                {"currency_id": foreign_currency, "amount": abs(amount_currency)}
            )
        account_payment = self.env["account.payment"].sudo().create(payment_vals)
        is_refund = float_compare(amount, 0, precision_rounding=rounding) < 0
        if is_refund:
            account_payment.write({"payment_type": "outbound"})
        account_payment.action_post()
        return account_payment.move_id.line_ids.filtered(
            lambda line: line.account_id == destination_account
            and (not is_refund or line.debit > 0)
        )
