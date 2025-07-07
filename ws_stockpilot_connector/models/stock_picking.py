# Copyright (C) 2025 WeSolved BV <https://wesolved.com>
# @author Miro Tasevski <miro.tasevski@wesolved.com>
# @author Insaf Amrani <insaf.amrani.boukhobza@wesolved.com>
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl).

from odoo import models


class StockPicking(models.Model):
    _inherit = "stock.picking"

    def _action_done(self):
        """
        Overrides the stock.picking `_action_done` method.
        """
        res = super()._action_done()
        for picking in self:
            if picking.picking_type_id.code == "outgoing":
                sale_order = picking.sale_id
                if sale_order and sale_order.stockpilot_order_id:
                    for move in picking.move_ids_without_package:
                        if move.product_id.type == "product":
                            config = self.env["stockpilot.configuration"].get_config()
                            if config:
                                self.env["stockpilot.inventory"].with_context(
                                    stockpilot_config=config
                                ).with_delay()._trigger_stock_update(move.product_id)
        return res
