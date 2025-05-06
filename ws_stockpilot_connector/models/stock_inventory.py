from odoo import models, api

class StockInventory(models.Model):
    _inherit = 'stock.inventory'

    def action_validate(self):
        res = super(StockInventory, self).action_validate()
        for line in self.line_ids.filtered(lambda l: l.product_id.default_code):
            self.env['stockpilot.inventory']._trigger_stock_update(line.product_id)
        return res
