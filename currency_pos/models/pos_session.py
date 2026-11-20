import math

from odoo import Command, _, api, fields, models
from odoo.exceptions import AccessError, UserError
from odoo.tools import float_is_zero


class PosSession(models.Model):
    _inherit = "pos.session"

    cash_box_ids = fields.One2many(
        "pos.session.cash.box",
        "session_id",
        string="Cash Boxes",
    )

    @api.model
    def _load_pos_data_models(self, config_id):
        models_list = super()._load_pos_data_models(config_id)
        if "res.currency.rate" not in models_list:
            models_list.append("res.currency.rate")
        # Load currencies before payment methods so many2one links resolve on first pass.
        if "res.currency" in models_list and "pos.payment.method" in models_list:
            models_list = [model for model in models_list if model != "res.currency"]
            method_index = models_list.index("pos.payment.method")
            models_list.insert(method_index, "res.currency")
        return models_list

    def _oca_cash_payment_methods(self):
        self.ensure_one()
        return self.payment_method_ids.filtered(lambda pm: pm.type == "cash")

    def _oca_primary_cash_payment_method(self):
        """The cash method core 20 tracks with the session bank statement."""
        self.ensure_one()
        return self.config_id._get_cash_payment_method()

    def _oca_payment_method_currency(self, payment_method):
        return payment_method.payment_currency_id or self.currency_id

    def _oca_is_foreign_payment_method(self, payment_method):
        payment_currency = self._oca_payment_method_currency(payment_method)
        return bool(payment_currency and payment_currency != self.currency_id)

    def _oca_get_cash_box(self, payment_method):
        self.ensure_one()
        return self.cash_box_ids.filtered(
            lambda box: box.payment_method_id == payment_method
        )[:1]

    def _oca_statement_lines(self, journal=None):
        """Cash statement lines posted by this session (all cash journals).

        Odoo 20 only links the primary cash journal lines to the session bank
        statement; the other cash boxes are found through `pos_session_id`.
        """
        self.ensure_one()
        domain = [("pos_session_id", "=", self.id)]
        if journal:
            domain.append(("journal_id", "=", journal.id))
        return (
            self.env["account.bank.statement.line"]
            .sudo()
            .search(domain, order="create_date, id")
        )

    def _oca_previous_cash_box_balance(self, payment_method):
        self.ensure_one()
        previous_session = self.search(
            [
                ("config_id", "=", self.config_id.id),
                ("id", "!=", self.id),
                ("state", "=", "closed"),
            ],
            order="stop_at desc, id desc",
            limit=1,
        )
        if not previous_session:
            return 0.0
        previous_box = previous_session.cash_box_ids.filtered(
            lambda box: box.payment_method_id == payment_method
        )[:1]
        return previous_box.balance_end_real if previous_box else 0.0

    def _oca_suggested_opening_balance(self, payment_method):
        """Opening suggested for a cash box.

        The primary box follows the cash journal balance core 20 uses for the
        session statement; the other boxes follow the last closed session.
        """
        self.ensure_one()
        if payment_method == self._oca_primary_cash_payment_method():
            # The journal balance is computed with raw SQL, so a value cached
            # earlier in the same transaction can be stale.
            payment_method.journal_id.invalidate_recordset(
                ["current_statement_balance", "has_statement_lines"]
            )
            return self.config_id._get_opening_balance()
        return self._oca_previous_cash_box_balance(payment_method)

    def _oca_ensure_cash_boxes(self, init_from_previous=False):
        for session in self:
            existing = session.cash_box_ids.payment_method_id
            to_create = [
                {
                    "session_id": session.id,
                    "payment_method_id": payment_method.id,
                    "balance_start": (
                        session._oca_suggested_opening_balance(payment_method)
                        if init_from_previous
                        else 0.0
                    ),
                }
                for payment_method in session._oca_cash_payment_methods() - existing
            ]
            if to_create:
                self.env["pos.session.cash.box"].create(to_create)

    def _oca_sync_cash_box_opening_balances(self):
        """Fill suggested openings from the last closed session while still in opening control."""
        for session in self.filtered(lambda record: record.state == "opening_control"):
            session._oca_ensure_cash_boxes(init_from_previous=True)
            for cash_box in session.cash_box_ids:
                cash_box.balance_start = session._oca_suggested_opening_balance(
                    cash_box.payment_method_id
                )

    def _oca_get_cash_box_opening_map(self):
        self.ensure_one()
        self._oca_sync_cash_box_opening_balances()
        return {
            cash_box.payment_method_id.id: cash_box.balance_start
            for cash_box in self.cash_box_ids
        }

    @api.model
    def _load_pos_data_read(self, records, config):
        # `self` is NOT the session here: `@api.model` methods run on the empty
        # model, and `records` carries the sessions (also when core's
        # `pos.config.notify_synchronisation` re-reads a session on a device
        # sync). So compute the map per row from the record that was read.
        result = super()._load_pos_data_read(records, config)
        for row in result:
            # Prefixed with "_" so POS Base.setup exposes it on the session record.
            row["_oca_cash_box_openings"] = self.browse(row["id"])._oca_get_cash_box_opening_map()
        return result

    def _oca_normalize_cashbox_values(self, cashbox_values):
        if not cashbox_values:
            return {}
        if isinstance(cashbox_values, dict):
            return {int(key): value for key, value in cashbox_values.items()}
        return {int(pm_id): amount for pm_id, amount in cashbox_values}

    def _oca_amount_in_payment_method_currency(self, payments, payment_method):
        currency = self._oca_payment_method_currency(payment_method)
        order_currency = self.currency_id
        total = 0.0
        for payment in payments:
            if payment.payment_method_id != payment_method:
                continue
            if currency == order_currency:
                total += payment.amount
                continue
            if payment.payment_currency_amount not in (False, None):
                total += payment.payment_currency_amount
                continue
            total += payment.currency_id._convert(
                payment.amount,
                currency,
                payment.company_id,
                payment.payment_date.date() if payment.payment_date else fields.Date.today(),
            )
        return currency.round(total), currency

    def _oca_get_journal_cash_moves(self, payment_method):
        """Cash in/out of one cash box, in the layout of core's `get_cash_in_out_list`."""
        self.ensure_one()
        moves = []
        cash_in_count = 0
        cash_out_count = 0
        for cash_move in self._oca_statement_lines(payment_method.journal_id):
            if not self.env["pos.session.cash.box"]._oca_is_cash_move_line(cash_move):
                continue
            if cash_move.amount > 0:
                cash_in_count += 1
                name = f"Cash in {cash_in_count}"
            else:
                cash_out_count += 1
                name = f"Cash out {cash_out_count}"
            moves.append(
                {
                    "name": cash_move.payment_ref or name,
                    "amount": cash_move.amount,
                    "id": cash_move.id,
                    "date": cash_move.create_date,
                    "cashier_name": self._get_cash_move_cashier_name(cash_move),
                }
            )
        return moves

    def _oca_build_cash_box_closing_details(self, payment_method, payments):
        self.ensure_one()
        self._oca_ensure_cash_boxes()
        cash_box = self._oca_get_cash_box(payment_method)
        # Change payments (negative, `is_change`) are part of the drawer: core's
        # closing control adds them to the cash payments as well.
        method_payments = payments.filtered(
            lambda payment: payment.payment_method_id == payment_method
        )
        amount_payment_currency, payment_currency = self._oca_amount_in_payment_method_currency(
            method_payments,
            payment_method,
        )
        payment_amount_session = sum(method_payments.mapped("amount"))
        moves = self._oca_get_journal_cash_moves(payment_method)
        moves_amount = sum(move["amount"] for move in moves)
        opening = cash_box.balance_start
        if self._oca_is_foreign_payment_method(payment_method):
            amount = payment_currency.round(opening + amount_payment_currency + moves_amount)
        else:
            amount = self.currency_id.round(opening + payment_amount_session + moves_amount)
            amount_payment_currency = payment_amount_session
        return {
            "name": payment_method.name,
            "id": payment_method.id,
            "amount": amount,
            "opening": opening,
            "payment_amount": payment_amount_session,
            "moves": moves,
            "amount_payment_currency": amount_payment_currency,
            "payment_amount_payment_currency": amount_payment_currency,
            "payment_currency_id": payment_currency.id if payment_currency else False,
            "payment_currency_name": payment_currency.name if payment_currency else "",
            "payment_currency_symbol": (
                payment_currency.symbol or payment_currency.name if payment_currency else ""
            ),
            "has_foreign_currency": self._oca_is_foreign_payment_method(payment_method),
            "type": "cash",
        }

    def oca_set_opening_control(self, cashbox_values, notes):
        """Open the session with opening cash amounts per cash payment method.

        :param cashbox_values: dict {payment_method_id: amount} or list of pairs
        :param notes: opening notes
        """
        self.ensure_one()
        if self.state != "opening_control":
            # Same answer as core's `set_opening_control` for an opened session.
            return self.set_opening_control(0.0, notes)
        values = self._oca_normalize_cashbox_values(cashbox_values)
        self._oca_ensure_cash_boxes()
        primary = self._oca_primary_cash_payment_method()
        for cash_box in self.cash_box_ids:
            if cash_box.payment_method_id.id in values:
                cash_box.balance_start = values[cash_box.payment_method_id.id]
        principal_amount = values.get(primary.id, 0.0) if primary else 0.0
        return self.with_context(oca_cashbox_values=values).set_opening_control(
            principal_amount,
            notes,
        )

    def _set_opening_control_data(self, cashbox_value: int, notes: str):
        self._oca_ensure_cash_boxes()
        cashbox_values = self._oca_normalize_cashbox_values(
            self.env.context.get("oca_cashbox_values")
        )
        primary = self._oca_primary_cash_payment_method()
        for cash_box in self.cash_box_ids:
            if cash_box.payment_method_id == primary:
                continue
            if cash_box.payment_method_id.id in cashbox_values:
                cash_box.balance_start = cashbox_values[cash_box.payment_method_id.id]
        super()._set_opening_control_data(cashbox_value, notes)
        if primary:
            primary_box = self._oca_get_cash_box(primary)
            if primary_box:
                primary_box.balance_start = (
                    cashbox_values.get(primary.id, cashbox_value)
                    if cashbox_values
                    else cashbox_value
                )

    def close_session_from_ui(self, payment_method_closing={}):
        """Keep the counted amounts of the closing popup for the cash boxes.

        `payment_method_closing` is Odoo 20's `{payment_method_id: counted}`
        mapping; the counted amount of a cash box is in its own currency.
        """
        self.ensure_one()
        if self.state == "closed":
            # Core reports draft orders before the closed state, which makes
            # the popup offer a retry loop on a session closed elsewhere.
            return {
                "status": False,
                "type": "session_already_closed",
                "message": _("This session is already closed."),
                "redirect": True,
            }
        self._oca_check_closing_counts(payment_method_closing)
        session = self.with_context(oca_payment_method_closing=payment_method_closing or {})
        return super(PosSession, session).close_session_from_ui(payment_method_closing)

    def _oca_check_closing_counts(self, payment_method_closing):
        """Refuse malformed counted amounts instead of failing deep in the closing."""
        try:
            valid = isinstance(payment_method_closing, dict)
            counted_map = (
                self._oca_normalize_cashbox_values(payment_method_closing) if valid else {}
            )
            valid = valid and all(
                isinstance(amount, (int, float))
                and not isinstance(amount, bool)
                and math.isfinite(amount)
                for amount in counted_map.values()
            )
        except (TypeError, ValueError, OverflowError):
            valid = False
        if not valid:
            raise UserError(_("The counted amounts are invalid."))

    def _oca_record_cash_box_counts(self):
        """Store the counted balance and the difference of every cash box.

        Runs before the session accounting, so the expected balance only holds
        the opening, the payments and the cash in/out of the box.
        """
        self.ensure_one()
        counted_by_method = self._oca_normalize_cashbox_values(
            self.env.context.get("oca_payment_method_closing")
        )
        primary = self._oca_primary_cash_payment_method()
        self._oca_ensure_cash_boxes()
        for cash_box in self.cash_box_ids:
            payment_method = cash_box.payment_method_id
            expected = cash_box._oca_get_expected_balance()
            counted = counted_by_method.get(payment_method.id)
            if counted is None:
                # Core counts a missing primary cash method as an empty drawer.
                counted = 0.0 if payment_method == primary else expected
            cash_box.write(
                {
                    "balance_end_real": counted,
                    "closing_difference": cash_box.currency_id.round(counted - expected),
                }
            )

    def _validate_session_accounting(self):
        # Only a real closing from the popup carries the counted amounts; other
        # callers of the accounting (crons, automatic closing) must not
        # overwrite the stored counts.
        if "oca_payment_method_closing" in self.env.context:
            self._oca_record_cash_box_counts()
        return super()._validate_session_accounting()

    def _handle_cash_statement_entries(self, payment_method_closing={}):
        """Also book the closing difference of the cash boxes without bank statement.

        Core calls this method when the session opens (it then creates the
        session bank statement) and when it closes; only the closing counts.
        """
        is_opening = not self.bank_statement_id
        result = super()._handle_cash_statement_entries(payment_method_closing)
        if not is_opening:
            self._oca_post_secondary_cash_box_differences()
        return result

    def _oca_post_secondary_cash_box_differences(self):
        self.ensure_one()
        primary = self._oca_primary_cash_payment_method()
        for cash_box in self.cash_box_ids:
            if cash_box.payment_method_id == primary:
                continue  # core books the primary box difference
            self._oca_post_cash_box_difference(
                cash_box.payment_method_id,
                cash_box.closing_difference,
            )

    def _oca_post_cash_box_difference(self, payment_method, amount):
        """Cash difference of a cash box, in the currency of its journal."""
        self.ensure_one()
        journal = payment_method.journal_id
        currency = self._oca_payment_method_currency(payment_method)
        if not journal or float_is_zero(amount, precision_rounding=currency.rounding):
            return
        if amount < 0.0:
            counterpart_account = journal.loss_account_id
            label = _("Cash difference observed during the counting (Loss) - closing")
            account_type = _("Loss")
        else:
            counterpart_account = journal.profit_account_id
            label = _("Cash difference observed during the counting (Profit) - closing")
            account_type = _("Profit")
        if not counterpart_account:
            raise UserError(
                _(
                    "Please go on the %(journal)s journal and define a %(type)s Account. "
                    "This account will be used to record cash difference.",
                    journal=journal.name,
                    type=account_type,
                )
            )
        statement_line = (
            self.env["account.bank.statement.line"]
            .with_context(no_retrieve_partner=True)
            .sudo()
            .create(
                {
                    "journal_id": journal.id,
                    "company_id": self.company_id.id,
                    "amount": amount,
                    "date": fields.Date.context_today(self),
                    "pos_session_id": self.id,
                    "payment_ref": label,
                    "counterpart_account_id": counterpart_account.id,
                }
            )
        )
        statement_line.move_id.message_post(
            body=_("Related Session: %(link)s", link=self._get_html_link())
        )

    def _handle_bank_payment_method_difference(self, payment_method_closing={}):
        """Read the counted amount of a foreign bank method in its own currency.

        Core compares the order currency total of the payments with the counted
        amount; the closing popup counts a foreign bank method in the currency
        of the method, so convert its difference to the order currency.

        Core also books that difference with lines in the company currency
        (`pos_session.py` `_handle_bank_payment_method_difference`: no `currency_id`,
        `amount_currency` = the order currency difference), which is only right when
        the order currency is the company currency. When it is not (e.g. a company in
        VES selling in USD) the difference is booked here instead.
        """
        closing = dict(payment_method_closing or {})
        book_here = self.currency_id != self.company_id.currency_id
        for payment_method in self.payment_method_ids.filtered(lambda pm: pm.type == "bank"):
            is_foreign = self._oca_is_foreign_payment_method(payment_method)
            if not (is_foreign or book_here):
                continue
            key = next(
                (k for k in (str(payment_method.id), payment_method.id) if k in closing),
                None,
            )
            if key is None:
                continue
            payments = self.order_ids.payment_ids.filtered(
                lambda payment, pm=payment_method: payment.payment_method_id == pm
            )
            order_amount = sum(payments.mapped("amount"))
            counted = closing[key] or 0.0
            if is_foreign:
                expected, currency = self._oca_amount_in_payment_method_currency(
                    payments, payment_method
                )
                difference = currency.round(expected - counted)
                counted = order_amount
                if not currency.is_zero(difference):
                    counted -= currency._convert(
                        difference,
                        self.currency_id,
                        self.company_id,
                        fields.Date.context_today(self),
                    )
            if book_here:
                # Core then sees no difference for this method.
                self._oca_book_bank_difference(payment_method, order_amount - counted)
                counted = order_amount
            closing[key] = counted
        return super()._handle_bank_payment_method_difference(closing)

    def _oca_book_bank_difference(self, payment_method, difference):
        """Book a bank method difference (order currency, positive = loss) with the
        lines in the order currency and the balance in the company currency."""
        self.ensure_one()
        order_currency = self.currency_id
        if order_currency.is_zero(difference):
            return
        journal = payment_method.journal_id
        correction_account = journal.loss_account_id if difference > 0 else journal.profit_account_id
        if not journal or not correction_account:
            return
        pm_account = payment_method.receivable_account_id or self._get_receivable_account()
        today = fields.Date.context_today(self)
        amount = order_currency.round(abs(difference))
        balance = self.company_id.currency_id.round(
            order_currency._convert(amount, self.company_id.currency_id, self.company_id, today)
        )
        sign = 1 if difference < 0 else -1
        move = (
            self.env["account.move"]
            .sudo()
            .with_context(linked_to_pos=True)
            .create(
                {
                    "journal_id": journal.id,
                    "date": today,
                    "ref": _(
                        "Bank difference for %(pm)s in %(session)s",
                        pm=payment_method.name,
                        session=self.name,
                    ),
                    "line_ids": [
                        Command.create(
                            {
                                "name": payment_method.name,
                                "account_id": pm_account.id,
                                "currency_id": order_currency.id,
                                "amount_currency": sign * amount,
                                "balance": sign * balance,
                            }
                        ),
                        Command.create(
                            {
                                "name": payment_method.name,
                                "account_id": correction_account.id,
                                "currency_id": order_currency.id,
                                "amount_currency": -sign * amount,
                                "balance": -sign * balance,
                            }
                        ),
                    ],
                }
            )
        )
        move._post()
        self.correction_move_ids |= move

    def try_cash_in_out(self, _type, amount, reason, partner_id, extras=None, **kwargs):
        """Cash in/out on a given cash box.

        Odoo 20 books the move on the single cash method with the journal
        suspense account. When the client names a cash method (`extras` or the
        `payment_method_id` keyword) the move is booked on its own journal and
        against the account of its inbound/outbound payment method line.
        """
        extras = dict(extras or {})
        payment_method_id = extras.get("payment_method_id") or kwargs.pop(
            "payment_method_id", None
        )
        if not payment_method_id:
            return super().try_cash_in_out(_type, amount, reason, partner_id, **kwargs)
        if not self.env.user._has_cash_move_permission():
            raise AccessError(_("You don't have the access rights to perform a cash in/out."))
        payment_method = self.env["pos.payment.method"].browse(payment_method_id)
        if payment_method not in self._oca_cash_payment_methods():
            raise UserError(_("There is no cash payment method for this PoS Session"))
        journal = payment_method.journal_id
        counterpart = (
            payment_method._oca_get_cash_move_counterpart_account(_type)
            or journal.suspense_account_id
        )
        vals = {
            "journal_id": journal.id,
            "company_id": self.company_id.id,
            "amount": amount if _type == "in" else -amount,
            "date": fields.Date.context_today(self),
            "pos_session_id": self.id,
            "payment_ref": f"{self.name}-{_type}-{reason}",
            "counterpart_account_id": counterpart.id,
        }
        if payment_method == self._oca_primary_cash_payment_method() and self.bank_statement_id:
            vals["statement_id"] = self.bank_statement_id.id
        if kwargs.get("employee_id") and "employee_id" in self.env["account.bank.statement.line"]._fields:
            vals["employee_id"] = kwargs["employee_id"]
        self.env["account.bank.statement.line"].with_context(
            no_retrieve_partner=True
        ).sudo().create(vals)

    def _oca_closing_payment_method_amounts(self, payment_method, payments):
        self.ensure_one()
        order_currency = self.currency_id
        method_currency = self._oca_payment_method_currency(payment_method)
        amount_payment_currency, payment_currency = self._oca_amount_in_payment_method_currency(
            payments,
            payment_method,
        )
        has_foreign_currency = bool(
            payment_currency
            and method_currency
            and payment_currency != order_currency
        )
        return {
            "amount_payment_currency": amount_payment_currency,
            "payment_amount_payment_currency": amount_payment_currency,
            "payment_currency_id": payment_currency.id if payment_currency else False,
            "payment_currency_name": payment_currency.name if payment_currency else "",
            "payment_currency_symbol": payment_currency.symbol or payment_currency.name
            if payment_currency
            else "",
            "has_foreign_currency": has_foreign_currency,
        }

    def _oca_aggregate_payments_amounts_by_employee(self, payments, payment_method):
        """Build pos_hr employee breakdown in the payment method currency when needed."""
        if not self._oca_is_foreign_payment_method(payment_method):
            return self._aggregate_payments_amounts_by_employee(payments)

        payments_by_employee = []
        for employee, payments_group in payments.grouped("employee_id").items():
            amount_foreign, _currency = self._oca_amount_in_payment_method_currency(
                payments_group,
                payment_method,
            )
            payments_by_employee.append(
                {
                    "id": employee.id if employee else "others",
                    "name": employee.name if employee else _("Others"),
                    "amount": amount_foreign,
                }
            )
        return sorted(
            payments_by_employee,
            key=lambda item: (item["id"] == "others", item["name"]),
        )

    def _oca_aggregate_moves_by_employee(self, payment_method):
        moves_per_employee = {}
        statement_lines = self._oca_statement_lines(payment_method.journal_id)
        for employee, moves in statement_lines.grouped("employee_id").items():
            if not employee:
                continue
            moves_per_employee[employee.id] = {
                "id": employee.id,
                "name": employee.name,
                "amount": sum(moves.mapped("amount")),
            }
        return sorted(moves_per_employee.values(), key=lambda item: -item["amount"])

    def get_closing_control_data(self):
        data = super().get_closing_control_data()
        self._oca_ensure_cash_boxes()
        orders = self._get_order_for_session_closing()
        payments = orders.payment_ids.filtered(
            lambda payment: payment.payment_method_id.type != "pay_later"
        )
        cash_details = []
        for payment_method in self._oca_cash_payment_methods():
            details = self._oca_build_cash_box_closing_details(payment_method, payments)
            method_payments = payments.filtered(
                lambda payment, pm=payment_method: payment.payment_method_id == pm
            )
            details["amount_per_employee"] = self._oca_aggregate_payments_amounts_by_employee(
                method_payments,
                payment_method,
            )
            details["moves_per_employee"] = self._oca_aggregate_moves_by_employee(
                payment_method
            )
            cash_details.append(details)
        if cash_details:
            # Odoo 20's closing popup declares its props with `useProps` and only
            # knows `default_cash_details`: the list of cash boxes (the first one is
            # the default) travels nested in it.
            data["default_cash_details"] = {**cash_details[0], "cash_details": cash_details}
        data["non_cash_payment_methods"] = [
            method_data
            for method_data in data.get("non_cash_payment_methods", [])
            if method_data.get("type") != "cash"
        ]
        for payment_method_data in data["non_cash_payment_methods"]:
            payment_method = self.env["pos.payment.method"].browse(payment_method_data["id"])
            method_payments = payments.filtered(
                lambda payment, pm=payment_method: payment.payment_method_id == pm
            )
            payment_method_data.update(
                self._oca_closing_payment_method_amounts(payment_method, method_payments)
            )
        return data

    # CORE COPY: odoo/addons/point_of_sale/models/pos_session.py, lines 1015-1146
    # (`_create_session_account_move`), image odoo:20.0@sha256:8bcae4c1f895683ee851e19dd3e7d999e81e770defe9015bc9dad8bbf10f2b0d.
    # Only change: the single cash payment method check (core line 1056) is removed.
    # Re-diff against core on every upgrade of the base image.
    def _create_session_account_move(self, orders):
        """Session closing receipt, copied from Odoo 20's point_of_sale.

        The only change is the removed "Only one cash payment method can be used
        in a session" check (point_of_sale/models/pos_session.py, same method):
        every cash box is a cash payment method of the session. Core has no hook
        for it, so compare this method with core when upgrading.
        """
        if not orders:
            return self.env['account.move']

        refund = orders[0].is_refund_or_negative()  # All orders are refunds or not
        AccountJournal = self.env['account.journal'].with_company(
            self.company_id,
        )
        journal = AccountJournal._ensure_company_account_journal()
        config_journal = self.config_id.journal_id
        if self.config_id.journal_id != journal and config_journal.type != 'sale':
            self.config_id.journal_id = journal

        # product_commands => invoice_line_ids (display_type=product, net price_unit)
        lines = orders.with_context(hide_combo_title=True)._prepare_account_move_line_data()
        lines_commands = [Command.create(line['account.move.line']) for line in lines]

        payments = orders._prepare_account_move_line_data_for_payments()
        line_data = [pm['account.move.line'] for pm in payments]
        payment_commands = [Command.create(pm_data) for pm_data in line_data]
        extra_commands = self._prepare_session_closing_extra_line_commands(
            orders,
            refund,
            payments,
        )

        # Ensure rounding method record is set on the invoice if needed
        rounding_method = self.config_id._get_rounding_method_for_invoice(orders)
        move_vals = self._prepare_session_move_vals(orders)
        move_vals.update({
            'invoice_line_ids': lines_commands,
            'line_ids': payment_commands,
            'invoice_cash_rounding_id': rounding_method.id,
        })
        move = self.env['account.move'].sudo().with_context(
            check_move_validity=False,
            linked_to_pos=True,
        ).create(move_vals)

        move_ctx = move.with_context(
            linked_to_pos=True,
            skip_invoice_sync=True,
        )

        if len(extra_commands) > 0:
            move_ctx.with_context(
                check_move_validity=False,
            ).write({'line_ids': extra_commands})

        payment_term_lines = move.line_ids.filtered(
            lambda line: line.display_type == 'payment_term',
        )

        with move_ctx._check_balanced({'records': move}):
            if rounding_method.exists():
                data = orders._prepare_account_move_line_data_for_rounding(move)
                move_ctx.line_ids = data

            # A rounded foreign-currency payment converts to a slightly different company-currency
            # total than the sum of individually converted product/tax balances. Absorb the diff.
            summary = sum(move.line_ids.mapped('balance'))
            balance_diff = self.company_id.currency_id.round(summary)
            if move.currency_id != self.company_id.currency_id and balance_diff:
                if balance_diff:
                    payment_term_lines = move.line_ids.filtered(
                        lambda line: line.display_type == 'payment_term',
                    )
                    if payment_term_lines:
                        payment_term_lines[0].balance -= balance_diff

        move_ctx.with_company(self.company_id)._post()
        default_partner = self.config_id.default_partner_id
        receivable_account = self._get_receivable_account()

        # The payment_term lines are created in the same order as the
        # payments, pair them so each payment is reconciled with its own
        # term line. We cannot reconcile automatically all lines together
        # because sometime it create weird reconciliation with multiple payments
        for payment, term in zip(payments, payment_term_lines.sorted('id')):
            metadata = payment['metadata']
            pm = metadata['payment_method_id']
            payment_line = pm._create_payment_line(
                self,
                metadata['amount'],
                receivable_account,
                False,
                metadata['partner'] or default_partner,
                metadata['foreign_currency_id'].id,
                metadata['amount_currency'],
            )
            to_reconcile = (payment_line + term).filtered(
                lambda line: not line.reconciled,
            )
            if len(to_reconcile) > 1:
                to_reconcile.with_context(
                    skip_invoice_sync=True,
                    no_cash_basis=True,
                ).sudo().reconcile()

        return move
