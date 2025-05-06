from odoo import models, fields, api, _
from odoo.exceptions import UserError
import requests
from datetime import datetime


class StockpilotInventory(models.Model):
    _name = 'stockpilot.inventory'
    _description = 'Stockpilot Inventory Synchronization'

    def _trigger_stock_update(self, product):
        """Main method to update stock in Stockpilot"""
        config = self.env['stockpilot.configuration'].get_config()
        if not config or not product.default_code:
            return False

        try:
            stock_data = {
                'sku': product.default_code,
                'quantity': int(product.qty_available),
                'reserved': int(product.outgoing_qty)
            }

            response = self._call_stockpilot_api(
                config,
                'inventory/update',
                stock_data,
                method='PUT'
            )

            if not response.get('success'):
                product_data = {
                    'sku': product.default_code,
                    'quantity': int(product.qty_available)
                }
                self._call_stockpilot_api(
                    config,
                    'inventory/create',
                    product_data
                )

            return True

        except Exception as e:
            return False

    def _call_stockpilot_api(self, config, endpoint, data=None, method='POST'):
        """Generic API call handler"""
        url = f"{config.base_url.rstrip('/')}/{endpoint}"
        headers = {
            'X-CLIENT-ID': config.api_client_id,
            'X-CLIENT-SECRET': config.api_client_secret,
            'Content-Type': 'application/json'
        }

        try:
            response = requests.request(
                method,
                url,
                json=data,
                headers=headers,
                timeout=10
            )
            response.raise_for_status()
            return response.json()
        except requests.exceptions.RequestException as e:
            error_msg = f"API Error ({endpoint}): {str(e)}"
            raise UserError(_(error_msg))

    def _scheduled_full_sync(self):
        """Periodic full stock synchronization"""
        config = self.env['stockpilot.configuration'].get_config()
        if not config:
            return

        products = self.env['product.product'].search([
            ('type', '=', 'product'),
            ('default_code', '!=', False),
            ('active', '=', True)
        ])

        for product in products:
            self._trigger_stock_update(product)
