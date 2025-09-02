# Copyright (C) 2025 WeSolved BV <https://wesolved.com>
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl).

from odoo import api, fields, models


class StockPicking(models.Model):
    _inherit = "stock.picking"

    carrier_tracking_ref = fields.Char()

    @api.onchange("carrier_tracking_ref")
    def _onchange_carrier_tracking_ref(self):
        """
        Overrides the stock.picking `_action_done` method
        to trigger Stockpilot forwarding for outgoing pickings.

        Returns:
            recordset: Result of the parent _action_done call.
        """
        return
        for picking in self:
            if picking.picking_type_id.code == "outgoing":
                sale_order = picking.sale_id
                if sale_order and sale_order.stockpilot_id:
                    sale_order.with_delay()._stockpilot_fulfill(
                        picking.carrier_tracking_ref
                    )

    def write(self, vals_list):
        """
        Overrides the stock.picking `write` method to
        capture tracking number updates.

        Args:
            vals_list (list): List of dictionaries containing field values to update.

        Returns:
            bool: True if the write operation was successful.
        """
        res = super().write(vals_list)
        for picking in self:
            if picking.picking_type_id.code == "outgoing":
                sale_order = picking.sale_id
                if (
                    sale_order
                    and sale_order.stockpilot_id
                    and "carrier_tracking_ref" in vals_list
                ):
                    sale_order.with_delay()._stockpilot_fulfill(
                        picking.carrier_tracking_ref
                    )
        return res
