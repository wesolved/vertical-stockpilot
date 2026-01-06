# Copyright (C) 2026 WeSolved BV <https://wesolved.com>
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl).

from odoo import models


class SaleOrder(models.Model):
    _inherit = "sale.order"

    def override_order(self, order, order_info):
        order = super().override_order(order, order_info)

        metadata = (order_info or {}).get("metadata") or {}
        shipping_title = (
            ((metadata.get("shippingLines") or [{}])[0].get("node") or {}).get("title")
            or ""
        )

        if not shipping_title:
            return order

        mapping = self.env["stockpilot.shipping.method"].search(
            [
                ("stockpilot_configuration_id", "=", order.stockpilot_configuration_id.id),
                ("stockpilot_name", "=", shipping_title),
            ],
            limit=1,
        )
        if mapping and mapping.carrier_id:
            order.carrier_id = mapping.carrier_id.id

        return order
