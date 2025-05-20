from odoo import models, api

class StockMove(models.Model):
    _inherit = 'stock.move'

    def _action_done(self):
        res = super()._action_done()
        if self.state == 'done':
            self.env['stockpilot.inventory'].with_delay(eta=60)._trigger_stock_update(self.product_id)
        return res
