# Copyright (C) 2025 WeSolved BV <https://wesolved.com>
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl).

from odoo import fields, models


class ProductProduct(models.Model):
    _inherit = "product.product"

    stockpilot_ids = fields.One2many(
        "stockpilot.product.product", "product_product_id", copy=False
    )

    def _stockpilot_get_bom_parent_products(self):
        """
        Return the manufactured/kit product variants whose bill of materials
        contain one of these products as a component. Their available quantity
        depends on the component stock, so they must be re-synced to Stockpilot
        whenever the component stock changes.

        Safe to call when the ``mrp`` module is not installed: the ``mrp.bom``
        model is simply absent and an empty recordset is returned.

        Returns:
            recordset: product.product records that should also be synced.
        """
        parent_products = self.env["product.product"]
        bom_model = self.env.get("mrp.bom")
        if bom_model is None or not self:
            return parent_products

        boms = bom_model.search(
            [("bom_line_ids.product_id", "in", self.ids)]
        )
        for bom in boms:
            if bom.product_id:
                parent_products |= bom.product_id
            else:
                # BOM defined on the template: include all its variants.
                parent_products |= bom.product_tmpl_id.product_variant_ids
        return parent_products

    def _push_stockpilot_product(self, configuration_id=False):
        """
        Push the product to Stockpilot and create a stockpilot.product.product record.
        If the product already exists in Stockpilot, it will not be created again.
        """
        if not configuration_id:
            configurations = self.env["stockpilot.configuration"].search([])
        else:
            configurations = self.env["stockpilot.configuration"].browse(
                configuration_id
            )
        for product in self:
            for configuration in configurations:
                if product.stockpilot_ids.filtered(
                    lambda r: r.stockpilot_configuration_id == configuration
                ):
                    product._update_stockpilot_stock()
                else:
                    self.env["stockpilot.product.product"].with_delay().create(
                        {
                            "stockpilot_configuration_id": configuration.id,
                            "product_product_id": product.id,
                        }
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
                "quantity": product_id._calculate_stock(configuration_id),
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

    def _calculate_stock(self, stockpilot_configuration):
        if stockpilot_configuration.stock_calculator == "qty_available":
            return self.qty_available
        elif stockpilot_configuration.stock_calculator == "virtual_available":
            return self.virtual_available
        elif stockpilot_configuration.stock_calculator == "free_qty":
            return self.free_qty
        elif stockpilot_configuration.stock_calculator == "incoming_qty":
            return self.incoming_qty
        elif stockpilot_configuration.stock_calculator == "outgoing_qty":
            return self.outgoing_qty
        return 0
