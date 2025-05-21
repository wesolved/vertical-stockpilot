from odoo import models


class StockQuant(models.Model):
    _inherit = "stock.quant"

    def write(self, vals):
        """
        Override of the write method to trigger a stock update in Stockpilot
        """
        res = super().write(vals)
        if "quantity" in vals:
            for quant in self.filtered(lambda q: q.product_id.default_code):
                self.env["stockpilot.inventory"]._trigger_stock_update(quant.product_id)
        return res
