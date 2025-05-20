from odoo import models, api

class ProductProduct(models.Model):
    _inherit = 'product.product'

    def write(self, vals):
        res = super().write(vals)
        if any(field in vals for field in ['qty_available', 'default_code']):
            self.env['stockpilot.inventory']._trigger_stock_update(self)
        return res
