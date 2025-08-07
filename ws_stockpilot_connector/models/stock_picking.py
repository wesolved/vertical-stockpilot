# Copyright (C) 2025 WeSolved BV <https://wesolved.com>
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl).

from odoo import fields, models


class StockPicking(models.Model):
    _inherit = "stock.picking"

    carrier_tracking_ref = fields.Char()

    def _action_done(self):
        """
        Overrides the stock.picking `_action_done` method
        to trigger Stockpilot forwarding for outgoing pickings.

        Returns:
            recordset: Result of the parent _action_done call.
        """
        res = super()._action_done()
        for picking in self:
            if picking.picking_type_id.code == "outgoing":
                sale_order = picking.sale_id
                if sale_order and sale_order.stockpilot_id:
                    sale_order.with_delay()._stockpilot_fulfill(
                        picking.carrier_tracking_ref
                    )
        return res
