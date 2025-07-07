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

    stockpilot_config_id = fields.Many2one(
        "stockpilot.configuration",
        string="Stockpilot Configuration",
        help="Configuration used to export this product to Stockpilot",
        copy=False,
    )

    def write(self, vals):
        """
        Update record and trigger Stockpilot sync on stock/code change.
        """
        res = super().write(vals)
        if any(field in vals for field in ["qty_available", "default_code"]):
            config = self.env["stockpilot.configuration"].get_config()
            if config:
                self.env["stockpilot.inventory"].with_context(
                    stockpilot_config=config
                )._trigger_stock_update(self)
        return res
