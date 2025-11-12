# Copyright (C) 2025 WeSolved BV <https://wesolved.com>
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl).

from math import floor

from odoo import fields, models


class ProductProduct(models.Model):
    _inherit = "product.product"

    stockpilot_ids = fields.One2many(
        "stockpilot.product.product", "product_product_id", copy=False
    )

    def _bom_for_product(self):
        """
            Return the BoM for a specific product variant (product.product)
            First, use _bom_find (takes into account company/variants), then fallback
        """
        bom = self.env["mrp.bom"]._bom_find(products=self, company_id=self.env.company.id)
        if not bom:
            bom = self.env["mrp.bom"].search(
                [("product_tmpl_id", "=", self.product_tmpl_id.id)],
                limit=1,
            )
        return bom or False

    def _compute_kit_max_qty(self, base_field="free_qty"):
        """
            Calculate the maximum possible quantity of product units
            that can be assembled from available BoM components
        """
        self.ensure_one()
        bom = self._bom_for_product()
        if not bom:
            return 0.0

        max_qty = None
        for line in bom.bom_line_ids:
            component = line.product_id
            if not component or line.product_qty <= 0:
                continue

            required_per_unit = line.product_uom_id._compute_quantity(line.product_qty, component.uom_id, rounding_method="HALF-UP")
            if required_per_unit <= 0:
                continue

            available = float(getattr(component, base_field, 0.0) or 0.0)
            possible = floor(available / required_per_unit)

            max_qty = possible if max_qty is None else min(max_qty, possible)
            if max_qty == 0:
                break

        return float(max_qty or 0.0)

    def _get_all_bom_parents(self):
        seen = set()
        to_process = set(self.ids)
        while to_process:
            ids_now = list(to_process)
            to_process.clear()

            lines = self.env["mrp.bom.line"].search([("product_id", "in", ids_now)])
            if not lines:
                continue

            parents = lines.mapped("bom_id.product_tmpl_id.product_variant_ids")
            new_ids = set(parents.ids) - seen - set(self.ids)
            if new_ids:
                seen |= new_ids
                to_process |= new_ids

        return self.env["product.product"].browse(list(seen))


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
        products_to_push = (self | self._get_all_bom_parents())
        if not products_to_push:
            return

        bridges = self.env["stockpilot.product.product"].search([("product_product_id", "in", products_to_push.ids)])
        if not bridges:
            return

        for bridge in bridges:
            configuration_id = bridge.stockpilot_configuration_id
            product_id = bridge.product_product_id
            connection = configuration_id._get_connection()
            product_data = {
                "id": bridge.stockpilot_id,
                "quantity": product_id._calculate_stock(configuration_id),
            }
            try:
                connection._execute_post_request("inventory/update", product_data)
            except Exception as e:
                if "Product not found" in str(e):
                    bridge.unlink()
                    self.env["stockpilot.product.product"].create(
                        {
                            "stockpilot_configuration_id": configuration_id.id,
                            "product_product_id": product_id.id,
                        }
                    )

    def _calculate_stock(self, stockpilot_configuration):
        if stockpilot_configuration.stock_calculator == "qty_available":
            qty = self.qty_available
        elif stockpilot_configuration.stock_calculator == "virtual_available":
            qty = self.virtual_available
        elif stockpilot_configuration.stock_calculator == "free_qty":
            qty = self.free_qty
        elif stockpilot_configuration.stock_calculator == "incoming_qty":
            qty = self.incoming_qty
        elif stockpilot_configuration.stock_calculator == "outgoing_qty":
            qty = self.outgoing_qty
        else:
            qty = 0

        if not qty:
            bom = self._bom_for_product()
            if bom:
                qty = self._compute_kit_max_qty(base_field="free_qty")
        return qty
