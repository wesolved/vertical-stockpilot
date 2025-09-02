# Copyright (C) 2025 WeSolved BV <https://wesolved.com>
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl).

from odoo import models


class StockMove(models.Model):
    _inherit = "stock.move"

    def _action_done(self, *args, **kwargs):
        """
        Call parent method and schedule Stockpilot stock update if transfer is done.

        Returns:
            recordset: Result of the parent _action_done call.
        """
        res = super()._action_done(*args, **kwargs)
        for record in self:
            if record.state == "done" and (
                not record.picking_id
                or (
                    record.picking_id
                    and record.picking_id.picking_type_id.code == "incoming"
                )
            ):
                record.product_id.with_delay()._update_stockpilot_stock()
        return res
