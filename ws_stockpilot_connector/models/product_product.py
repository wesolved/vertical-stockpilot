from odoo import models, api

class ProductProduct(models.Model):
    _inherit = 'product.product'

    def write(self, vals):
        res = super(ProductProduct, self).write(vals)
        if any(field in vals for field in ['default_code', 'active']):
            for product in self.filtered('default_code'):
                self.env['stockpilot.inventory']._trigger_stock_update(product)
        return res
