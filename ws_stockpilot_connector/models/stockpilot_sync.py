# Copyright (C) 2025 WeSolved BV <https://wesolved.com>
# Author: Miro Tasevski <miro.tasevski@wesolved.com>
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl).
# Corrected version with VAT on products and working discount calculation.

import logging
from datetime import datetime

import requests
from odoo import _, fields, models
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)


class StockpilotSync(models.Model):
    _name = "stockpilot.sync"
    _description = "Stockpilot Synchronization"

    def _get_stockpilot_orders(self, config):
        try:
            base_url = f"{config.base_url.rstrip('/')}/orders"
            headers = {
                "X-CLIENT-ID": config.api_client_id,
                "X-CLIENT-SECRET": config.api_client_secret,
            }
            params = {"page": 1, "page_size": 100}
            all_orders = []
            while True:
                response = requests.get(
                    base_url, headers=headers, params=params, timeout=15
                )
                response.raise_for_status()
                data = response.json()
                if not isinstance(data, dict) or "results" not in data:
                    break
                current_orders = data.get("results", [])
                all_orders.extend(current_orders)
                if not current_orders or len(current_orders) < params["page_size"]:
                    break
                params["page"] += 1
            return {"results": all_orders}
        except Exception as e:
            _logger.error(f"Fatal error fetching orders: {str(e)}", exc_info=True)
            return None

    def _fetch_stockpilot_orders(self):
        configs = self.env["stockpilot.configuration"].search([])
        if not configs:
            raise UserError(_("No Stockpilot configurations found"))
        for config in configs:
            orders = self._get_stockpilot_orders(config)
            if not orders or not orders.get("results"):
                continue
            for order_data in orders["results"]:
                self._process_stockpilot_order(order_data, config.company_id)
        return True

    def _process_stockpilot_order(self, order_data, company):
        try:
            existing_order = self.env["sale.order"].search(
                [
                    ("stockpilot_order_id", "=", order_data.get("id")),
                    ("company_id", "=", company.id),
                ],
                limit=1,
            )

            team_id = self._get_odoo_team_for_channel(
                order_data.get("sales_channel"), company
            )
            partner = self._find_or_create_customer(order_data, company)
            order_date = self._parse_order_date(order_data.get("order_placed_dt"))

            line_items = order_data.get("order_details", {}).get("line_items", [])

            if existing_order:
                existing_order.write(
                    {
                        "partner_id": partner.id,
                        "date_order": order_date,
                        "team_id": team_id.id if team_id else False,
                        "note": f"Updated {order_data.get('handle', 'Unknown')}",
                    }
                )
                self._update_order_lines(existing_order, line_items, company)
            else:
                order_vals = {
                    "stockpilot_order_id": order_data.get("id"),
                    "name": order_data.get("order_number"),
                    "partner_id": partner.id,
                    "date_order": order_date,
                    "company_id": company.id,
                    "team_id": team_id.id if team_id else False,
                    "order_line": self._prepare_order_lines(line_items, company),
                    "note": f"Imported {order_data.get('handle', 'Unknown')}",
                }
                order = self.env["sale.order"].create(order_vals)
                shipping_total = float(
                    order_data.get("order_details", {}).get("shipping_total", 0)
                )
                if shipping_total > 0:
                    self._add_shipping_line(order, shipping_total, company)
                if order.state == "draft":
                    order.action_confirm()
            return True
        except Exception as e:
            _logger.error(f"Failed to process order: {str(e)}", exc_info=True)
            return False

    def _prepare_order_lines(self, line_items, company):
        lines = []
        config = self.env["stockpilot.configuration"].get_config(company.id)
        seen = set()
        for line in line_items:
            name = (line.get("sales_channel_title") or "").strip()
            if not name:
                continue
            qty = float(line.get("quantity", 1))
            unit_price = float(line.get("retail_price", 0)) or float(
                line.get("total_price", 0)
            )
            discount_abs = float(line.get("discount", 0)) or 0.0
            discount_pct = (
                round((discount_abs / unit_price) * 100, 2) if unit_price else 0.0
            )

            if (name, qty) in seen:
                continue
            seen.add((name, qty))

            product = self.env["product.product"].search(
                [("name", "=ilike", name)], limit=1
            )
            if not product:
                product = self._create_placeholder_product(name)
            # taxes = self._get_taxes_for_line(line, config, company, product)
            taxes = self._get_taxes_for_line(line, config, company, product)
            tax_ids = [(6, 0, taxes.ids)] if taxes else []
            lines.append(
                (
                    0,
                    0,
                    {
                        "product_id": product.id,
                        "product_uom_qty": qty,
                        "price_unit": unit_price,
                        "discount": discount_pct,
                        "name": name,
                        "tax_id": tax_ids,
                    },
                )
            )
        return lines

    def _update_order_lines(self, order, line_items, company):
        config = self.env["stockpilot.configuration"].get_config(company.id)
        existing = {(l.name.strip(), l.product_uom_qty): l for l in order.order_line}
        seen = set()
        for line in line_items:
            name = (line.get("sales_channel_title") or "").strip()
            if not name:
                continue
            qty = float(line.get("quantity", 1))
            unit_price = float(line.get("retail_price", 0)) or float(
                line.get("total_price", 0)
            )
            discount_abs = float(line.get("discount", 0)) or 0.0
            discount_pct = (
                round((discount_abs / unit_price) * 100, 2) if unit_price else 0.0
            )
            key = (name, qty)
            if key in seen:
                continue
            seen.add(key)
            product = self.env["product.product"].search(
                [("name", "=ilike", name)], limit=1
            )
            if not product:
                product = self._create_placeholder_product(name)
            taxes = self._get_taxes_for_line(line, config, company, product)
            tax_ids = [(6, 0, taxes.ids)] if taxes else []
            if key in existing:
                existing[key].write(
                    {
                        "price_unit": unit_price,
                        "discount": discount_pct,
                        "tax_id": tax_ids,
                    }
                )
            else:
                self.env["sale.order.line"].create(
                    {
                        "order_id": order.id,
                        "product_id": product.id,
                        "product_uom_qty": qty,
                        "price_unit": unit_price,
                        "discount": discount_pct,
                        "name": name,
                        "tax_id": tax_ids,
                    }
                )

    def _get_taxes_for_line(self, line, config, company, product):
        tax_rate = float(line.get("tax_rate", 0))
        if tax_rate <= 0:
            return self.env["account.tax"].browse([])
        existing_tax = self.env["account.tax"].search(
            [
                ("company_id", "=", company.id),
                ("amount", ">=", tax_rate - 0.01),
                ("amount", "<=", tax_rate + 0.01),
                ("type_tax_use", "=", "sale"),
                ("amount_type", "=", "percent"),
            ],
            limit=1,
        )
        if existing_tax:
            return existing_tax
        if config and config.create_missing_taxes:
            return self.env["account.tax"].create(
                {
                    "name": f"{tax_rate:.2f}% VAT",
                    "amount": tax_rate,
                    "amount_type": "percent",
                    "type_tax_use": "sale",
                    "company_id": company.id,
                }
            )
        return self.env["account.tax"].browse([])

    def _add_shipping_line(self, order, amount, company):
        shipping_product = self.env["product.product"].search(
            [("name", "ilike", "shipping"), ("type", "=", "service")], limit=1
        )
        if not shipping_product:
            shipping_product = self.env["product.product"].create(
                {
                    "name": "Shipping",
                    "type": "service",
                    "list_price": 0.0,
                }
            )
        tax = self.env["account.tax"].search(
            [
                ("company_id", "=", company.id),
                ("type_tax_use", "=", "sale"),
                ("amount", ">", 0),
            ],
            limit=1,
        )
        order.write(
            {
                "order_line": [
                    (
                        0,
                        0,
                        {
                            "product_id": shipping_product.id,
                            "name": "Shipping Costs",
                            "product_uom_qty": 1,
                            "price_unit": amount,
                            "is_delivery": True,
                            "tax_id": [(6, 0, tax.ids)],
                        },
                    )
                ]
            }
        )

    def _create_placeholder_product(self, name):
        return self.env["product.product"].create(
            {
                "name": name,
                "type": "product",
                "list_price": 0.0,
                "standard_price": 0.0,
            }
        )

    def _parse_order_date(self, date_str):
        if not date_str:
            return fields.Datetime.now()
        for fmt in ("%Y-%m-%dT%H:%M:%S%z", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%d"):
            try:
                return datetime.strptime(date_str, fmt).replace(tzinfo=None)
            except ValueError:
                continue
        return fields.Datetime.now()

    def _get_odoo_team_for_channel(self, name, company):
        if not name:
            return False
        config = self.env["stockpilot.configuration"].get_config(company.id)
        if not config:
            return False
        mapping = config.channel_mapping_ids.filtered(
            lambda m: m.stockpilot_channel.lower() == name.lower()
        )
        if mapping:
            return mapping.odoo_team_id
        if config.create_missing_teams:
            return self.env["crm.team"].create(
                {
                    "name": f"{name} (Stockpilot)",
                    "company_id": company.id,
                    "team_type": "sales",
                }
            )
        return False

    def _find_or_create_customer(self, order_data, company):
        stockpilot_id = order_data.get("customer", {}).get("id")
        email = order_data.get("customer_email")
        phone = order_data.get("customer_phone")
        name = order_data.get("customer_name", "Stockpilot Customer")
        domain = [("company_id", "=", company.id)]
        if stockpilot_id:
            partner = self.env["res.partner"].search(
                domain + [("stockpilot_customer_id", "=", stockpilot_id)], limit=1
            )
            if partner:
                return partner
        if email:
            partner = self.env["res.partner"].search(
                domain + [("email", "=", email)], limit=1
            )
            if partner:
                if stockpilot_id and not partner.stockpilot_customer_id:
                    partner.stockpilot_customer_id = stockpilot_id
                return partner
        return self.env["res.partner"].create(
            {
                "name": name,
                "email": email,
                "phone": phone,
                "company_id": company.id,
                "stockpilot_customer_id": stockpilot_id,
                "customer_rank": 1,
            }
        )
