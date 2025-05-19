from odoo import models, api

class ProductProduct(models.Model):
    _inherit = 'product.product'

    def write(self, vals):
        """
        Override of the write method to trigger a stock update in Stockpilot
        """
        res = super(ProductProduct, self).write(vals)

        trigger_fields = {
            'default_code',
            'active',
            'qty_available',
            'virtual_available',
            'incoming_qty',
            'outgoing_qty',
            'free_qty',
        }

        if any(field in vals for field in trigger_fields):
            products = self.filtered('default_code')
            if products:
                self.env['stockpilot.inventory']._trigger_stock_update(products)
        return res
