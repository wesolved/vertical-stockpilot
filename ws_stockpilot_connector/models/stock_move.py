from odoo import models


class StockMove(models.Model):
    _inherit = "stock.move"

    def _action_done(self):
        """
        Call parent method and schedule Stockpilot stock update if transfer is done.
        """
        res = super()._action_done()
        if self.state == "done":
            self.env["stockpilot.inventory"].with_delay(eta=60)._trigger_stock_update(
                self.product_id
            )
        return res
