# Copyright (C) 2025 WeSolved BV <https://wesolved.com>
# @author Miro Tasevski <miro.tasevski@wesolved.com>
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl).

import logging

from odoo import fields, models

_logger = logging.getLogger(__name__)


class ProductTemplate(models.Model):
    _inherit = "product.template"

    stockpilot_id = fields.Char(string="Stockpilot Product ID", copy=False)
    exported_to_stockpilot = fields.Boolean(
        string="Exported to Stockpilot", default=False
    )
    stockpilot_config_id = fields.Many2one(
        "stockpilot.configuration",
        string="Stockpilot Configuration",
        help="Configuration used to export this product to Stockpilot",
        copy=False,
    )

    def _export_product_template(self, product_tmpl):
        config = self.env["stockpilot.configuration"].get_config()
        if not config:
            _logger.error("No Stockpilot configuration found")
            return False

        payload = {
            "title": product_tmpl.name,
            "description": product_tmpl.description or "",
            "sku": product_tmpl.default_code or f"TEMPLATE-{product_tmpl.id}",
            "barcode": product_tmpl.barcode or "N/A",
            "barcode_type": "EAN",
            "condition": "NEW",
            "vat_class": "standard_rate",
            "is_active": product_tmpl.active,
        }

        _logger.info(f"Exporting product template: {product_tmpl.id}")
        response = self._call_stockpilot_api(config, "product/create", payload)

        if response and response.get("product_id"):
            product_tmpl.write(
                {
                    "stockpilot_id": response["product_id"],
                    "stockpilot_config_id": config.id,
                }
            )
            return response["product_id"]
        else:
            _logger.error(f"Failed to export product template {product_tmpl.id}")
            return False
