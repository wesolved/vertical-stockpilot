# Copyright (C) 2025 WeSolved BV <https://wesolved.com>
# @author Miro Tasevski <miro.tasevski@wesolved.com>
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl).

from odoo import fields, models


class ProductProduct(models.Model):
    _inherit = "product.product"

    stockpilot_ids = fields.One2many(
        "stockpilot.product.product", "product_product_id", copy=False
    )

    def _update_stockpilot_stock(self):
        """
        Trigger an inventory update towards Stockpilot for
        all linked stockpilot.product.product records.
        Sends the current quantity for each variant to Stockpilot.
        """
        for product in self.stockpilot_ids:
            configuration_id = product.stockpilot_configuration_id
            product_id = product.product_product_id
            connection = configuration_id._get_connection()
            product_data = {
                "id": product.stockpilot_id,
                "quantity": product.product_product_id.qty_available,
            }
            try:
                connection._execute_post_request("inventory/update", product_data)
            except Exception as e:
                if "Product not found" in str(e):
                    product.unlink()
                    self.env["stockpilot.product.product"].create(
                        {
                            "stockpilot_configuration_id": configuration_id.id,
                            "product_product_id": product_id.id,
                        }
                    )
