from odoo import models


class StockQuant(models.Model):
    _inherit = "stock.quant"

    def write(self, vals):
        """
        Update record and schedule Stockpilot stock update if 'quantity' changes.
        """
        res = super().write(vals)
        if "quantity" in vals:
            self.env["stockpilot.inventory"].with_delay(eta=30)._trigger_stock_update(
                self.product_id
            )
        return res
