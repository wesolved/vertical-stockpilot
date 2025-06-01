from odoo import models, api

class StockPicking(models.Model):
    _inherit = "stock.picking"

    def _action_done(self):
        res = super()._action_done()
        for picking in self:
            if(
                picking.picking_type_id.code == "outgoing"
            ):
                for move in picking.move_ids_without_package:
                    if move.product_id.type == "product":
                        self.env[
                            "stockpilot.inventory"
                        ].with_delay()._trigger_stock_update(move.product_id)
        return res
