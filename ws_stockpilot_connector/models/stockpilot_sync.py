# Copyright (C) 2025 WeSolved BV <https://wesolved.com>
# @author Miro Tasevski <miro.tasevski@wesolved.com>
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl).
import logging
import time
from datetime import datetime

import requests
from odoo import fields, models

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
        """Fetch and process all Stockpilot orders for all configurations."""

        configs = self.env["stockpilot.configuration"].search([])
        if not configs:
            _logger.info("No Stockpilot configurations found - skipping order import")
            return True

        for config in configs:
            orders = self._get_stockpilot_orders(config)
            if not orders or not orders.get("results"):
                continue

            for order_data in orders["results"]:
                self._process_stockpilot_order(order_data, config.company_id)

        return True

    def _process_stockpilot_order(self, order_data, company):
        """Process a single Stockpilot order and create or
        update the corresponding Odoo sale order."""

        try:
            existing_order = self.env["sale.order"].search(
                [
                    ("stockpilot_order_id", "=", order_data.get("id")),
                    ("company_id", "=", company.id),
                ],
                limit=1,
            )

            channel_name = order_data.get("sales_channel")
            team_id = self._get_odoo_team_for_channel(channel_name, company)
            partners = self._find_or_create_customer(order_data, company)
            order_date = self._parse_order_date(order_data.get("order_placed_dt"))

            if existing_order:
                _logger.info(f"Updating order {order_data.get('order_number')}")
                existing_order.write(
                    {
                        "partner_id": partners["company"].id,  # Set to company
                        "partner_invoice_id": partners["invoice"].id,
                        "partner_shipping_id": partners["delivery"].id,
                        "date_order": order_date,
                        "team_id": team_id.id if team_id else False,
                        "note": f"Updated {order_data.get('handle', 'Unknown')}",
                    }
                )
                self._update_order_lines(
                    existing_order,
                    order_data.get("order_details", {}).get("line_items", []),
                    company,
                )
                return True

            order_vals = {
                "stockpilot_order_id": order_data.get("id"),
                "name": order_data.get("order_number"),
                "partner_id": partners["company"].id,  # Set to company
                "partner_invoice_id": partners["invoice"].id,
                "partner_shipping_id": partners["delivery"].id,
                "date_order": order_date,
                "company_id": company.id,
                "team_id": team_id.id if team_id else False,
                "order_line": self._prepare_order_lines(
                    order_data.get("order_details", {}).get("line_items", []), company
                ),
                "note": f"Imported {order_data.get('handle', 'Unknown')}",
            }

            order = self.env["sale.order"].create(order_vals)

            shipping_total = float(
                order_data.get("order_details", {}).get("shipping_total", 0)
            )
            if shipping_total > 0:
                self._add_shipping_line(order, shipping_total)

            if order.state == "draft":
                order.action_confirm()

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
        """Find or create the customer, invoice, delivery, and
        main contact partners in Odoo from Stockpilot order data"""
        # Extract customer and address info from order_details
        order_details = order_data.get("order_details", {})
        customer_info = {
            "company_name": order_details.get("billing_company"),
            "main_email": order_details.get("customer_email"),
            "phone": order_details.get("customer_phone"),
            "billing_address": {
                "address_line": order_details.get("billing_street"),
                "zipcode": order_details.get("billing_zipcode"),
                "city": order_details.get("billing_city"),
                "country": order_details.get("billing_country"),
            },
            "shipping_address": {
                "address_line": order_details.get("shipment_street"),
                "zipcode": order_details.get("shipment_zipcode"),
                "city": order_details.get("shipment_city"),
                "country": order_details.get("shipment_country"),
            },
            "vat": order_details.get("vat_number"),
            "website": None,  # Not available in order_details
            "main_contact": {
                "first_name": order_details.get("billing_firstname"),
                "last_name": order_details.get("billing_lastname"),
                "email": order_details.get("customer_email"),
                "phone": order_details.get("customer_phone"),
            },
            "invoice_email": order_details.get("customer_email"),
            "orders_email": order_details.get("customer_email"),
        }
        _logger.info("[Stockpilot Sync] Incoming customer_info: %s", customer_info)
        # The rest of the function remains unchanged, using customer_info as before
        stockpilot_customer_id = None  # Not available in this payload
        company_name = (
            customer_info.get("company_name")
            or order_data.get("customer_name")
            or "Stockpilot Customer"
        )
        website = customer_info.get("website")
        vat = customer_info.get("vat")
        phone = customer_info.get("phone")
        main_email = customer_info.get("main_email")
        invoice_email = customer_info.get("invoice_email")
        orders_email = customer_info.get("orders_email")
        billing = customer_info.get("billing_address", {})
        shipping = customer_info.get("shipping_address", {})
        main_contact = customer_info.get("main_contact", {})
        main_firstname = main_contact.get("first_name")
        main_lastname = main_contact.get("last_name")
        main_contact_email = main_contact.get("email")
        main_contact_phone = main_contact.get("phone")
        domain = [("company_id", "=", company.id)]
        partner_obj = self.env["res.partner"]
        # 1. Find or create the company (is_company=True)
        company_partner = None
        if stockpilot_customer_id:
            company_partner = partner_obj.search(
                domain
                + [
                    ("stockpilot_customer_id", "=", stockpilot_customer_id),
                    ("is_company", "=", True),
                ],
                limit=1,
            )
        if not company_partner and vat:
            company_partner = partner_obj.search(
                domain + [("vat", "=", vat), ("is_company", "=", True)],
                limit=1,
            )
        if not company_partner and main_email:
            company_partner = partner_obj.search(
                domain
                + [
                    ("email", "=", main_email),
                    ("is_company", "=", True),
                ],
                limit=1,
            )

        def get_address_vals(addr, label):
            street = addr.get("address_line")
            zip_code = addr.get("zipcode")
            city = addr.get("city")
            country_code = addr.get("country")
            country_id = False
            if country_code:
                country_id = (
                    self.env["res.country"]
                    .search([("code", "=", country_code)], limit=1)
                    .id
                )
                if not country_id:
                    _logger.warning(
                        f"[Stockpilot Sync] {label} country code"
                        " '{country_code}' not found in Odoo!"
                    )
            if not street or not zip_code or not city:
                _logger.warning(
                    f"[Stockpilot Sync] {label} address missing fields: "
                    f"street={street}, zip={zip_code}, city={city}"
                )
            return {
                "street": street,
                "zip": zip_code,
                "city": city,
                "country_id": country_id,
            }

        billing_vals = get_address_vals(billing, "Billing")
        shipping_vals = get_address_vals(shipping, "Shipping")
        company_vals = {
            "name": company_name,
            "website": website,
            "vat": vat,
            "phone": phone,
            "email": main_email,
            "stockpilot_customer_id": stockpilot_customer_id,
            "is_company": True,
            "company_id": company.id,
            "customer_rank": 1,
            **billing_vals,
        }
        if company_partner:
            company_partner.write({k: v for k, v in company_vals.items() if v})
        else:
            company_partner = partner_obj.create(
                {k: v for k, v in company_vals.items() if v}
            )
        # 2. Invoice address (child)
        invoice_vals = {
            "parent_id": company_partner.id,
            "type": "invoice",
            "name": f"{company_name}",
            **billing_vals,
            "email": invoice_email or main_email,
            "phone": phone,
        }
        invoice_partner = partner_obj.search(
            [("parent_id", "=", company_partner.id), ("type", "=", "invoice")], limit=1
        )
        if invoice_partner:
            invoice_partner.write({k: v for k, v in invoice_vals.items() if v})
        else:
            invoice_partner = partner_obj.create(
                {k: v for k, v in invoice_vals.items() if v}
            )
        # 3. Delivery address (child)
        delivery_vals = {
            "parent_id": company_partner.id,
            "type": "delivery",
            "name": f"{company_name}",
            **shipping_vals,
            "email": orders_email or main_email,
            "phone": phone,
        }
        delivery_partner = partner_obj.search(
            [("parent_id", "=", company_partner.id), ("type", "=", "delivery")], limit=1
        )
        if delivery_partner:
            delivery_partner.write({k: v for k, v in delivery_vals.items() if v})
        else:
            delivery_partner = partner_obj.create(
                {k: v for k, v in delivery_vals.items() if v}
            )
        # 4. Main contact (person, child)
        main_contact_vals = {
            "parent_id": company_partner.id,
            "type": "contact",
            "name": f"{main_firstname or ''} {main_lastname or ''}".strip()
            or company_name,
            "email": main_contact_email or main_email,
            "phone": main_contact_phone or phone,
        }
        main_contact_partner = partner_obj.search(
            [
                ("parent_id", "=", company_partner.id),
                ("type", "=", "contact"),
                ("email", "=", main_contact_email or main_email),
            ],
            limit=1,
        )
        if main_contact_partner:
            main_contact_partner.write(
                {k: v for k, v in main_contact_vals.items() if v}
            )
        else:
            main_contact_partner = partner_obj.create(
                {k: v for k, v in main_contact_vals.items() if v}
            )
        return {
            "company": company_partner,
            "invoice": invoice_partner,
            "delivery": delivery_partner,
            "main_contact": main_contact_partner,
        }

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
        """Prepare order line values from Stockpilot
        with tax and discount, avoiding duplicates."""

        order_lines = []
        config = self.env["stockpilot.configuration"].get_config(company.id)

        seen_lines = set()  # (name, qty)

        for line in line_items:
            try:
                raw_title = (line.get("sales_channel_title") or "").strip()
                if not raw_title:
                    continue

                quantity = float(line.get("quantity", 1))
                retail_price = float(line.get("retail_price", 0)) or float(
                    line.get("total_price", 0)
                )
                discount_abs = float(line.get("discount", 0)) or 0.0
                discount_pct = (
                    round((discount_abs / retail_price) * 100, 2)
                    if retail_price
                    else 0.0
                )

                line_key = (raw_title, quantity)
                if line_key in seen_lines:
                    _logger.warning(f"Duplicate line detected and skipped: {line_key}")
                    continue
                seen_lines.add(line_key)

                product = self.env["product.product"].search(
                    [("name", "=ilike", raw_title)], limit=1
                )

                if not product:
                    product = self._create_placeholder_product(raw_title)

                taxes = self._get_taxes_for_line(line, config, company, product)

                order_lines.append(
                    (
                        0,
                        0,
                        {
                            "product_id": product.id,
                            "product_uom_qty": quantity,
                            "price_unit": retail_price,
                            "discount": discount_pct,
                            "name": raw_title,
                            "tax_id": [(6, 0, taxes.ids)],
                        },
                    )
                )

            except Exception as e:
                _logger.error(f"Error preparing line: {str(e)}")

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
        """Always prefer tax from Stockpilot's line['tax_rate']"""

        tax_rate = float(line.get("tax_rate", 0))
        tax_name = line.get("tax_name", "Imported Tax")

        if tax_rate <= 0:
            return self.env["account.tax"]

        # Match on amount within 0.01 precision
        existing_tax = self.env["account.tax"].search(
            [
                ("type_tax_use", "=", "sale"),
                ("company_id", "=", company.id),
                ("amount_type", "=", "percent"),
                ("amount", ">=", tax_rate - 0.01),
                ("amount", "<=", tax_rate + 0.01),
            ],
            limit=1,
        )

        if existing_tax:
            return existing_tax

        if config and config.create_missing_taxes:
            return self.env["account.tax"].create(
                {
                    "name": f"{tax_name or 'Stockpilot Tax'} ({tax_rate}%)",
                    "amount": tax_rate,
                    "amount_type": "percent",
                    "type_tax_use": "sale",
                    "company_id": company.id,
                }
            )

        return self.env["account.tax"]

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

    def _update_order_lines(self, order, line_items, company):
        """Update or create order lines from Stockpilot, skipping duplicates."""

        config = self.env["stockpilot.configuration"].get_config(company.id)

        existing_lines = {
            (line.name.strip(), line.product_uom_qty): line for line in order.order_line
        }

        seen_lines = set()

        for line in line_items:
            name = (line.get("sales_channel_title") or "").strip()
            if not name:
                continue

            quantity = float(line.get("quantity", 1))
            retail_price = float(line.get("retail_price", 0)) or float(
                line.get("total_price", 0)
            )
            discount_abs = float(line.get("discount", 0)) or 0.0
            discount_pct = (
                round((discount_abs / retail_price) * 100, 2) if retail_price else 0.0
            )

            line_key = (name, quantity)
            if line_key in seen_lines:
                _logger.warning(f"Duplicate update line skipped: {line_key}")
                continue
            seen_lines.add(line_key)

            product = self.env["product.product"].search(
                [("name", "=ilike", name)], limit=1
            )

            if not product:
                product = self._create_placeholder_product(name)

            taxes = self._get_taxes_for_line(line, config, company, product)

            if line_key in existing_lines:
                existing_lines[line_key].write(
                    {
                        "price_unit": retail_price,
                        "discount": discount_pct,
                        "tax_id": [(6, 0, taxes.ids)],
                        "name": name,
                    }
                )
            else:
                self.env["sale.order.line"].create(
                    {
                        "order_id": order.id,
                        "product_id": product.id,
                        "product_uom_qty": quantity,
                        "price_unit": retail_price,
                        "discount": discount_pct,
                        "tax_id": [(6, 0, taxes.ids)],
                        "name": name,
                    }
                )
