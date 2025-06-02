# Copyright (C) 2025 WeSolved BV <https://wesolved.com>
# @author Miro Tasevski <miro.tasevski@wesolved.com>
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl).
import logging
import time
from datetime import datetime

import requests
from odoo import _, fields, models
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)


class StockpilotSync(models.Model):
    _name = "stockpilot.sync"
    _description = "Stockpilot Synchronization"

    def _get_stockpilot_orders(self, config):
        """Fetch ALL orders from Stockpilot API with dynamic pagination"""
        try:
            base_url = f"{config.base_url.rstrip('/')}/orders"
            headers = {
                "X-CLIENT-ID": config.api_client_id,
                "X-CLIENT-SECRET": config.api_client_secret,
            }
            params = {
                "page": 1,
                "page_size": 100,
            }

            all_orders = []
            max_retries = 3
            retry_delay = 5

            while True:
                retry_count = 0
                page_success = False
                current_orders = []

                while retry_count < max_retries and not page_success:
                    try:
                        _logger.info(f"Fetching page {params['page']} from {base_url}")
                        response = requests.get(
                            base_url, headers=headers, params=params, timeout=15
                        )
                        response.raise_for_status()
                        data = response.json()

                        if not isinstance(data, dict) or "results" not in data:
                            _logger.error(f"Invalid API response format: {data}")
                            break

                        current_orders = data.get("results", [])
                        all_orders.extend(current_orders)
                        page_success = True

                    except requests.exceptions.RequestException as e:
                        retry_count += 1
                        _logger.warning(
                            f"Page {params['page']} {retry_count}/{max_retries}: {str(e)}"
                        )
                        if retry_count < max_retries:
                            time.sleep(retry_delay)

                if not page_success:
                    _logger.error(
                        f"Failed to fetch page {params['page']} after {max_retries} attempts"
                    )
                    break

                if not current_orders or len(current_orders) < params["page_size"]:
                    break

                params["page"] += 1

            _logger.info(f"Fetched {len(all_orders)} total orders from Stockpilot")
            return {"results": all_orders}

        except Exception as e:
            _logger.error(f"Fatal error in order fetching: {str(e)}", exc_info=True)
            return None

    def _fetch_stockpilot_orders(self):
        """Fetch orders from Stockpilot with the actual API structure"""

        _logger.info("Starting Stockpilot order import")

        configs = self.env["stockpilot.configuration"].search([])
        if not configs:
            _logger.error("No Stockpilot configurations found")
            raise UserError(_("No Stockpilot configurations found"))

        for config in configs:
            _logger.info(f"Processing config for company: {config.company_id.name}")

            orders = self._get_stockpilot_orders(config)
            if not orders or not orders.get("results"):
                _logger.warning("No orders received from Stockpilot API")
                return

            order_list = orders.get("results", [])
            _logger.info(f"Received {len(order_list)} orders from Stockpilot")

            for order_data in order_list:
                self.with_delay()._process_stockpilot_order(
                    order_data, config.company_id
                )

        return "Successfully Created Tasks to process orders"

    def _process_stockpilot_order(self, order_data, company):
        """Process a single Stockpilot order, skip if already exists"""
        _logger.info(f"Processing order {order_data.get('order_number')}")

        try:
            existing_order = self.env["sale.order"].search(
                [
                    ("stockpilot_order_id", "=", order_data.get("id")),
                    ("company_id", "=", company.id),
                ],
                limit=1,
            )

            if existing_order:
                _logger.info(
                    f"Order {order_data.get('order_number')} already exists, skipping"
                )
                return True

            channel_name = order_data.get("sales_channel")
            team_id = self._get_odoo_team_for_channel(channel_name, company)

            partner = self._find_or_create_customer(order_data, company)
            if not partner:
                _logger.error(
                    f"Failed to find/create customer for order {order_data.get('order_number')}"
                )
                return False

            order_date = self._parse_order_date(order_data.get("order_placed_dt"))

            order_vals = {
                "stockpilot_order_id": order_data.get("id"),
                "name": order_data.get("order_number"),
                "partner_id": partner.id,
                "date_order": order_date,
                "company_id": company.id,
                "team_id": team_id.id if team_id else False,
                "order_line": self._prepare_order_lines(
                    order_data.get("order_details", {}).get("line_items", []), company
                ),
                "note": f"Imported {order_data.get('handle', 'Unknown')}",
            }

            _logger.info(f"Creating new order for {order_data.get('order_number')}")
            order = self.env["sale.order"].create(order_vals)

            shipping_total = float(
                order_data.get("order_details", {}).get("shipping_total", 0)
            )
            if shipping_total > 0:
                self._add_shipping_line(order, shipping_total)

            if order.state == "draft":
                order.action_confirm()
                _logger.info(f"Confirmed order {order.name}")

            return True

        except Exception as e:
            _logger.error(
                f"Failed to process order {order_data.get('order_number')}: {str(e)}",
                exc_info=True,
            )
            return False

    def _parse_order_date(self, date_str):
        """Parse order date from various Stockpilot formats"""
        if not date_str:
            return fields.Datetime.now()

        try:
            return datetime.strptime(date_str, "%Y-%m-%dT%H:%M:%S%z").replace(
                tzinfo=None
            )
        except ValueError:
            try:
                return datetime.strptime(date_str, "%Y-%m-%dT%H:%M:%S")
            except ValueError:
                try:
                    return datetime.strptime(date_str, "%Y-%m-%d")
                except ValueError:
                    _logger.warning(
                        f"Unparseable date format: {date_str}, using current time"
                    )
                    return fields.Datetime.now()

    def _get_odoo_team_for_channel(self, channel_name, company):
        """Map Stockpilot channel to Odoo sales team"""
        if not channel_name:
            return False

        config = self.env["stockpilot.configuration"].get_config(company.id)
        if not config:
            return False

        mapping = config.channel_mapping_ids.filtered(
            lambda m: m.stockpilot_channel.lower() == channel_name.lower()
        )
        if mapping:
            return mapping.odoo_team_id

        if config.create_missing_teams:
            return self.env["crm.team"].create(
                {
                    "name": f"{channel_name} (Stockpilot)",
                    "company_id": company.id,
                    "team_type": "sales",
                }
            )

        return False

    def _find_or_create_customer(self, order_data, company):
        """Find or create customer with company context"""
        stockpilot_customer_id = order_data.get("customer", {}).get("id")
        email = order_data.get("customer_email")
        phone = order_data.get("customer_phone")
        name = order_data.get("customer_name", "Stockpilot Customer")

        domain = [("company_id", "=", company.id)]

        if stockpilot_customer_id:
            existing = self.env["res.partner"].search(
                domain + [("stockpilot_customer_id", "=", stockpilot_customer_id)],
                limit=1
            )
            if existing:
                return existing

        if email:
            existing = self.env["res.partner"].search(
                domain + [("email", "=", email)], limit=1
            )
            if existing:
                if stockpilot_customer_id and not existing.stockpilot_customer_id:
                    existing.stockpilot_customer_id = stockpilot_customer_id
                return existing

        return self.env["res.partner"].create(
            {
                "name": name,
                "email": email,
                "phone": phone,
                "company_id": company.id,
                "stockpilot_customer_id": stockpilot_customer_id,
                "customer_rank": 1,
            }
        )

    def _create_order_from_stockpilot(self, order_data, company):
        """Create new Odoo order from Stockpilot data"""
        partner = self._find_or_create_customer(order_data["customer"], company)

        order_vals = {
            "stockpilot_order_id": order_data["id"],
            "partner_id": partner.id,
            "date_order": order_data.get("date", fields.Datetime.now()),
            "state": self._map_stockpilot_to_odoo_status(
                order_data.get("status", "New")
            ),
            "company_id": company.id,
            "order_line": self._prepare_order_lines(order_data.get("lines", [])),
        }

        return self.env["sale.order"].create(order_vals)

    def _update_order_from_stockpilot(self, order, order_data):
        """Update existing Odoo order from Stockpilot data"""
        update_vals = {
            "state": self._map_stockpilot_to_odoo_status(
                order_data.get("status", order.state)
            ),
        }

        if "lines" in order_data:
            self._update_order_lines(order, order_data["lines"])

        order.write(update_vals)

    def _prepare_order_lines(self, line_items, company):
        """Prepare order line values from Stockpilot line items with tax information"""
        order_lines = []
        config = self.env["stockpilot.configuration"].get_config(company.id)

        for line in line_items:
            try:
                if not line.get("sales_channel_title"):
                    _logger.warning("Line missing product title, skipping")
                    continue

                product = self.env["product.product"].search(
                    [
                        (
                            "name",
                            "=ilike",
                            line["sales_channel_title"].split("-")[0].strip(),
                        )
                    ],
                    limit=1,
                )

                if not product:
                    _logger.warning(
                        f"Product not found for: {line['sales_channel_title']}"
                    )
                    product = self._create_placeholder_product(
                        line["sales_channel_title"]
                    )

                price = float(line.get("retail_price", 0)) or float(
                    line.get("total_price", 0)
                )
                if price <= 0:
                    price = product.list_price

                taxes = self._get_taxes_for_line(line, config, company, product)

                order_lines.append(
                    (
                        0,
                        0,
                        {
                            "product_id": product.id,
                            "product_uom_qty": float(line.get("quantity", 1)),
                            "price_unit": price,
                            "name": line["sales_channel_title"],
                            "tax_id": [(6, 0, taxes.ids)],
                        },
                    )
                )

            except Exception as e:
                _logger.error(f"Failed to process line: {str(e)}")
                continue

        _logger.info(f"Prepared {len(order_lines)} order lines with taxes")
        return order_lines

    def _get_taxes_for_line(self, line, config, company, product):
        """
        Determine the correct taxes for an order line with this priority:
        """
        if not config:
            config = self.env["stockpilot.configuration"].get_config(company.id)

        line_tax = self._get_tax_from_line_data(line, config, company)
        if line_tax:
            return line_tax

        if product.taxes_id:
            return product.taxes_id.filtered(lambda t: t.company_id == company)

        if config and config.default_tax_id:
            return config.default_tax_id

        return self.env["account.tax"]

    def _get_tax_from_line_data(self, line, config, company):
        """Extract and find/create tax based on line item data"""
        tax_rate = float(line.get("tax_rate", 0))
        tax_name = line.get("tax_name", "Imported Tax")

        if tax_rate == 0:
            return None

        existing_tax = self.env["account.tax"].search(
            [
                ("type_tax_use", "=", "sale"),
                ("company_id", "=", company.id),
                ("amount", "=", tax_rate),
            ],
            limit=1,
        )

        if existing_tax:
            return existing_tax

        if config and config.create_missing_taxes:
            try:
                new_tax = self.env["account.tax"].create(
                    {
                        "name": f"{tax_name} ({tax_rate}%)",
                        "amount": tax_rate,
                        "amount_type": "percent",
                        "type_tax_use": "sale",
                        "company_id": company.id,
                        "description": f"Imported {line.get('sales_channel_title', '')}",
                    }
                )
                _logger.info(f"Created new tax: {new_tax.name}")
                return new_tax
            except Exception as e:
                _logger.error(f"Failed to create tax: {str(e)}")

        return None

    def _create_placeholder_product(self, product_name):
        """Create a placeholder product when the real one isn't found"""
        try:
            _logger.info(f"Creating placeholder product for {product_name}")
            return self.env["product.product"].create(
                {
                    "name": product_name,
                    "type": "product",
                    "list_price": 0.0,
                    "standard_price": 0.0,
                }
            )
        except Exception as e:
            _logger.error(f"Failed to create placeholder product: {str(e)}")
            raise

    def _update_order_lines(self, order, lines_data):
        """Update existing order lines from Stockpilot data"""

    def _add_shipping_line(self, order, shipping_total):
        """Add shipping line to the order"""
        try:
            shipping_product = self.env["product.product"].search(
                [("name", "ilike", "shipping"), ("type", "=", "service")], limit=1
            )

            if not shipping_product:
                shipping_product = self.env["product.product"].create(
                    {
                        "name": "Shipping",
                        "type": "service",
                        "list_price": 0.0,
                        "invoice_policy": "order",
                    }
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
                                "price_unit": shipping_total,
                                "is_delivery": True,
                            },
                        )
                    ]
                }
            )
        except Exception as e:
            _logger.error(f"Failed to add shipping line: {str(e)}")
