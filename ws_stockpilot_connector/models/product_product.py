from odoo import fields, models


class ProductProduct(models.Model):
    _inherit = "product.product"

    stockpilot_id = fields.Char(
        string="Stockpilot ID",
        help="Unique identifier for the product in Stockpilot.",
    )

    exported_to_stockpilot = fields.Boolean(
        string="Exported to Stockpilot",
        help="Indicates whether the product has been exported to Stockpilot.",
    )

    def write(self, vals):
        """
        Update record and trigger Stockpilot sync on stock/code change.
        """
        res = super().write(vals)
        if any(field in vals for field in ["qty_available", "default_code"]):
            self.env["stockpilot.inventory"]._trigger_stock_update(self)
        return res
