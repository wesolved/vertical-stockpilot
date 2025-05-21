# Copyright (C) 2025 WeSolved BV <https://wesolved.com>
# @author Miro Tasevski <miro.tasevski@wesolved.com>
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl).
import requests

from odoo import _, fields, models, api
from odoo.exceptions import UserError
import logging

_logger = logging.getLogger(__name__)

class StockpilotConfiguration(models.Model):
    _name = "stockpilot.configuration"
    _description = "Stockpilot Configuration"

    api_client_id = fields.Char(
        string="API Client ID", default="f9e56e88-14e1-4fc0-8089-04aba8e6088b"
    )
    api_client_secret = fields.Char(
        string="API Client Secret",
        default="4c2145b40980fd2005f80bf97776b6e63600587d0c0cbe404fade80027bb9a1f",
    )
    base_url = fields.Char(string="Base URL", default="https://api.stockpilot.dev")
    environment = fields.Selection(
        [
            ("test", "Test"),
            ("production", "Production"),
        ],
        string="Environment",
        default="test",
    )

    company_id = fields.Many2one(
        "res.company", string="Company", default=lambda self: self.env.company
    )

    def _verify_credentials(self):
        """Check if API credentials and base URL are valid."""
        self.ensure_one()
        if not all([self.api_client_id, self.api_client_secret, self.base_url]):
            raise UserError(_("All API credentials must be configured"))
        if not self.base_url.startswith(("http://", "https://")):
            raise UserError(_("Base URL must start with http:// or https://"))

    def _test_api_connectivity(self):
        """Connecting to Stockpilot API"""
        try:
            response = requests.get(
                f"{self.base_url.rstrip('/')}/inventory",
                headers={
                    "X-CLIENT-ID": self.api_client_id,
                    "X-CLIENT-SECRET": self.api_client_secret,
                },
                params={"page": 1, "page_size": 100},
                timeout=10,
            )
            return response.status_code == 200, (
                _("Connection successful")
                if response.status_code == 200
                else _("API returned status: %s") % response.status_code
            )
        except requests.exceptions.RequestException:
            return False, _("Could not connect to API server")
        except Exception:
            return False, _("Unexpected error occurred")

    def test_connection(self):
        """
        Tests the API connection and shows a notification with the result.
        Triggered by a button click in the UI.
        """
        self.ensure_one()
        try:
            self._verify_credentials()
            success, message = self._test_api_connectivity()

            return {
                "type": "ir.actions.client",
                "tag": "display_notification",
                "params": {
                    "title": _("Success") if success else _("Failed"),
                    "message": message,
                    "type": "success" if success else "danger",
                    "sticky": not success,
                },
            }
        except UserError as e:
            return {
                "type": "ir.actions.client",
                "tag": "display_notification",
                "params": {
                    "title": _("Error"),
                    "message": str(e),
                    "type": "danger",
                    "sticky": True,
                },
            }

    @api.model
    def get_config(self, company_id=None):
        """Get configuration for current or specified company"""
        if company_id is None:
            company_id = self.env.company.id
        return self.search([('company_id', '=', company_id)], limit=1)

    def import_orders(self):
        """Button action to import orders from Stockpilot with detailed logging"""
        self.ensure_one()
        try:
            _logger.info("Starting order import from Stockpilot")
            _logger.debug(f"Using configuration - Client ID: {self.api_client_id}, Base URL: {self.base_url}")

            # Get the sync model
            sync_model = self.env['stockpilot.sync']

            # Execute the import
            result = sync_model._fetch_stockpilot_orders()

            if not result:
                _logger.error("Order import returned False/None - possible failure")
                return {
                    'type': 'ir.actions.client',
                    'tag': 'display_notification',
                    'params': {
                        'title': _('Warning'),
                        'message': _('Order import completed but may have had issues'),
                        'type': 'warning',
                        'sticky': True,
                    }
                }

            _logger.info("Orders imported successfully")
            return {
                'type': 'ir.actions.client',
                'tag': 'display_notification',
                'params': {
                    'title': _('Success'),
                    'message': _('Orders imported successfully'),
                    'type': 'success',
                    'sticky': False,
                }
            }
        except Exception as e:
            _logger.error(f"Failed to import orders: {str(e)}", exc_info=True)
            return {
                'type': 'ir.actions.client',
                'tag': 'display_notification',
                'params': {
                    'title': _('Error'),
                    'message': _('Failed to import orders: %s') % str(e),
                    'type': 'danger',
                    'sticky': True,
                }
            }

    def import_stock(self):
        """Button action to import stock levels"""
        self.ensure_one()
        try:
            result = self.env['stockpilot.inventory'].import_stock_levels(self)

            message = _("Stock import completed with:") + "\n"
            message += _("- %d products updated") % result['updated'] + "\n"
            message += _("- %d products created") % result['created'] + "\n"
            message += _("- %d products failed") % result['failed']

            notif_type = 'success'
            if result['failed'] > 0:
                notif_type = 'warning'
            if result['updated'] == 0 and result['created'] == 0:
                notif_type = 'danger'

            return {
                'type': 'ir.actions.client',
                'tag': 'display_notification',
                'params': {
                    'title': _('Stock Import Results'),
                    'message': message,
                    'type': notif_type,
                    'sticky': result['failed'] > 0,
                }
            }
        except Exception as e:
            _logger.error(f"Failed to import stock: {str(e)}", exc_info=True)
            return {
                'type': 'ir.actions.client',
                'tag': 'display_notification',
                'params': {
                    'title': _('Error'),
                    'message': _('Failed to import stock levels: %s') % str(e),
                    'type': 'danger',
                    'sticky': True,
                }
            }

    def export_products(self):
        """Button action to export products to Stockpilot"""
        self.ensure_one()
        try:
            success_count = 0
            fail_count = 0
            products = self.env['product.product'].search([
                ('type', '=', 'product'),
                ('default_code', '!=', False),
                ('active', '=', True)
            ])

            if not products:
                return {
                    'type': 'ir.actions.client',
                    'tag': 'display_notification',
                    'params': {
                        'title': _('Warning'),
                        'message': _('No products with SKU found to export'),
                        'type': 'warning',
                        'sticky': True,
                    }
                }

            _logger.info(f"Starting export of {len(products)} products to Stockpilot")

            for product in products:
                try:
                    if self.env['stockpilot.inventory']._trigger_stock_update(product):
                        success_count += 1
                        _logger.info(f"Successfully exported product {product.default_code}")
                    else:
                        fail_count += 1
                        _logger.warning(f"Failed to export product {product.default_code}")
                except Exception as e:
                    fail_count += 1
                    _logger.error(f"Error exporting product {product.default_code}: {str(e)}")

            message = _("Export completed: %d successful, %d failed. Check logs for details.") % (success_count,
                                                                                                  fail_count)

            return {
                'type': 'ir.actions.client',
                'tag': 'display_notification',
                'params': {
                    'title': _('Export Results'),
                    'message': message,
                    'type': 'success' if fail_count == 0 else 'warning',
                    'sticky': True,
                }
            }
        except Exception as e:
            _logger.error(f"Export failed completely: {str(e)}")
            return {
                'type': 'ir.actions.client',
                'tag': 'display_notification',
                'params': {
                    'title': _('Error'),
                    'message': _('Failed to export products: %s') % str(e),
                    'type': 'danger',
                    'sticky': True,
                }
            }
