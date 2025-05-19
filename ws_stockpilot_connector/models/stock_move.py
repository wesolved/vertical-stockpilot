from odoo import models, api

class StockMove(models.Model):
    _inherit = 'stock.move'

    def _action_done(self, cancel_backorder=False):
        """
        Override of the `_action_done` method to trigger a stock update in Stockpilot
        """
        res = super(StockMove, self)._action_done(cancel_backorder)
        for move in self.filtered(lambda m: m.state == 'done' and m.product_id.default_code):
            self.env['stockpilot.inventory']._trigger_stock_update(move.product_id)
        return res
