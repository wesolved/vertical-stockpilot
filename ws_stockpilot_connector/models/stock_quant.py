from odoo import models


class StockQuant(models.Model):
    _inherit = "stock.quant"

    def write(self, vals):
        """
        Update record and schedule Stockpilot stock update if 'quantity' changes.
        """
        res = super().write(vals)
        if "quantity" in vals:
            config = self.env["stockpilot.configuration"].get_config()
            if config:
                self.env["stockpilot.inventory"].with_context(
                    stockpilot_config=config
                ).with_delay(eta=30)._trigger_stock_update(self.product_id)
        return res
