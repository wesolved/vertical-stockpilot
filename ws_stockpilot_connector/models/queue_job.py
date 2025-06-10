from odoo import models, fields

class StockpilotQueueJob(models.Model):
    _inherit = "queue.job"

    product_id = fields.Many2one("product.product", string="Related Product")
    config_id = fields.Many2one("stockpilot.configuration", string="Stockpilot Config")
