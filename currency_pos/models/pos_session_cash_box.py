from odoo import api, fields, models
from odoo.tools import float_is_zero


class PosSessionCashBox(models.Model):
    _name = "pos.session.cash.box"
    _description = "POS Session Cash Box"
    _order = "id"

    session_id = fields.Many2one(
        "pos.session",
        required=True,
        ondelete="cascade",
        index=True,
    )
    payment_method_id = fields.Many2one(
        "pos.payment.method",
        required=True,
        ondelete="restrict",
    )
    currency_id = fields.Many2one(
        "res.currency",
        compute="_compute_currency_id",
        store=True,
    )
    journal_id = fields.Many2one(
        "account.journal",
        related="payment_method_id.journal_id",
        store=True,
    )
    balance_start = fields.Monetary(
        currency_field="currency_id",
        default=0.0,
    )
    balance_end_real = fields.Monetary(
        currency_field="currency_id",
        default=0.0,
    )
    closing_difference = fields.Monetary(
        currency_field="currency_id",
        default=0.0,
        help="Counted minus expected at closing control time (before sales statement lines).",
    )
    balance_end = fields.Monetary(
        currency_field="currency_id",
        compute="_compute_balance_end",
    )
    difference = fields.Monetary(
        currency_field="currency_id",
        compute="_compute_balance_end",
    )
    is_primary = fields.Boolean(compute="_compute_is_primary")

    _session_payment_method_uniq = models.Constraint(
        "unique(session_id, payment_method_id)",
        "A cash box already exists for this payment method in the session.",
    )

    @api.depends("payment_method_id", "payment_method_id.payment_currency_id", "session_id.currency_id")
    def _compute_currency_id(self):
        for box in self:
            box.currency_id = (
                box.payment_method_id.payment_currency_id
                or box.session_id.currency_id
            )

    @api.depends("session_id.payment_method_ids", "payment_method_id")
    def _compute_is_primary(self):
        for box in self:
            primary = box.session_id.payment_method_ids.filtered(
                lambda pm: pm.type == "cash"
            )[:1]
            box.is_primary = bool(primary and box.payment_method_id == primary)

    @api.depends(
        "balance_start",
        "balance_end_real",
        "session_id.order_ids.payment_ids.amount",
        "session_id.order_ids.payment_ids.payment_currency_amount",
    )
    def _compute_balance_end(self):
        for box in self:
            expected = box._oca_get_expected_balance()
            box.balance_end = expected
            box.difference = box.balance_end_real - expected

    @api.model
    def _oca_is_cash_move_line(self, statement_line):
        """True for a cash in/out line.

        The other lines of a cash journal are written by the session closing:
        the payment lines (counterpart on a receivable account) and the opening
        or closing cash differences (counterpart on the profit/loss account).
        """
        journal = statement_line.journal_id
        counterparts = (
            statement_line.move_id.line_ids.account_id - journal.default_account_id
        )
        if counterparts & (journal.profit_account_id | journal.loss_account_id):
            return False
        return not any(
            account.account_type == "asset_receivable" for account in counterparts
        )

    def _oca_get_expected_balance(self):
        """Opening + payments + cash in/out, in the currency of the cash box."""
        self.ensure_one()
        session = self.session_id
        payment_method = self.payment_method_id
        payments = session._get_closed_orders().payment_ids.filtered(
            lambda payment: (
                payment.payment_method_id == payment_method
                and not float_is_zero(
                    payment.amount, precision_rounding=session.currency_id.rounding
                )
            )
        )
        payment_amount, _currency = session._oca_amount_in_payment_method_currency(
            payments,
            payment_method,
        )
        moves_amount = sum(
            line.amount
            for line in session._oca_statement_lines(payment_method.journal_id)
            if self._oca_is_cash_move_line(line)
        )
        return self.currency_id.round(self.balance_start + payment_amount + moves_amount)
