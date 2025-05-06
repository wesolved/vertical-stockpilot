from odoo import models, api

class StockQuant(models.Model):
    _inherit = 'stock.quant'

    def write(self, vals):
        res = super(StockQuant, self).write(vals)
        if 'quantity' in vals:
            for quant in self.filtered(lambda q: q.product_id.default_code):
                self.env['stockpilot.inventory']._trigger_stock_update(quant.product_id)
        return res
