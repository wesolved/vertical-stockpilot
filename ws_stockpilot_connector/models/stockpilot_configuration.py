# Copyright (C) 2025 WeSolved BV <https://wesolved.com>
# @author Miro Tasevski <miro.tasevski@wesolved.com>
# @author Insaf Amrani <insaf.amrani.boukhobza@wesolved.com>
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl).

import logging

import requests

from odoo import _, fields, models
from odoo.exceptions import UserError

from ..stockpilot_api import StockpilotApi

_logger = logging.getLogger(__name__)


class StockpilotConfiguration(models.Model):
    _name = "stockpilot.configuration"
    _description = "Stockpilot Configuration"

    name = fields.Char(
        string="Name",
        required=True,
    )

    create_missing_taxes = fields.Boolean(
        string="Create Missing Taxes",
        default=True,
        help="Automatically create tax records when they don't exist",
    )

    default_tax_id = fields.Many2one(
        "account.tax",
        string="Default Tax",
        domain=[("type_tax_use", "=", "sale")],
        help="Default tax to apply when no other tax information is available",
    )

    api_client_id = fields.Char(
        string="API Client ID",
    )
    api_client_secret = fields.Char(
        string="API Client Secret",
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

    active = fields.Boolean(
        string="Active",
        default=True,
    )

    shipping_product = fields.Many2one(
        "product.product",
        string="Shipping Product",
        domain=[("type", "=", "service")],
        help="Product used for shipping costs in Stockpilot orders",
    )

    def _get_connection(self):
        """
        Get a StockpilotApi connection instance using this configuration's credentials.

        Returns:
            StockpilotApi: API connection object.
        """
        connection = StockpilotApi(
            self.api_client_id, self.api_client_secret, self.environment
        )

        return connection

    def toggle_active(self):
        """
        Standard method name that works with Odoo's built-in archive/unarchive.
        Archives or unarchives the configuration.

        Returns:
            bool: True if successful.
        """
        self.write({"active": not self.active})
        return True

    def toggle_active_view(self):
        """
        Return an action to view Stockpilot configuration records (tree/form view).

        Returns:
            dict: Odoo action for window view.
        """
        return {
            "type": "ir.actions.act_window",
            "name": "Configurations",
            "res_model": "stockpilot.configuration",
            "view_mode": "tree,form",
            "contex": {
                "search_default_active": not self.env.context.get(
                    "search_default_active", True
                )
            },
            "domain": [],
        }

    def unlink(self):
        """
        Raises a UserError if trying to delete an active configuration.

        Returns:
            bool: Result of the parent unlink call.
        """
        active_configs = self.filtered(lambda c: c.active)
        if active_configs:
            raise UserError(
                _("You cannot delete active configurations! Archive them first.")
            )

        return super().unlink()

    def _verify_credentials(self):
        """
        Check if API credentials and base URL are valid.
        Raises a UserError if any credentials are missing or invalid.
        """
        self.ensure_one()
        if not all([self.api_client_id, self.api_client_secret, self.base_url]):
            raise UserError(_("All API credentials must be configured"))
        if not self.base_url.startswith(("http://", "https://")):
            raise UserError(_("Base URL must start with http:// or https://"))

    def _test_api_connectivity(self):
        """
        Test connectivity to the Stockpilot API using current credentials.

        Returns:
            tuple: (bool success, str message)
        """
        try:
            connection = self._get_connection()
            params = {"page": 1, "page_size": 100}
            response = connection._execute_get_request("inventory", params)
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

        Returns:
            dict: Odoo client action for notification.
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

    def _fetch_orders(self):
        for config in self.env["stockpilot.configuration"].search([]):
            config.with_delay().import_orders()

    def import_orders(self):
        """
        Import Stockpilot orders. Can be triggered by a scheduled
        action or a manual button press.
        Fetches open orders from Stockpilot and creates corresponding sale.order records.
        """
        self.ensure_one()
        connection = self._get_connection()
        params = {"status": "open", "page": 1, "page_size": 100}
        response = connection._execute_get_request("orders", params)
        if response.status_code != 200:
            raise UserError(_("Fetching stockpilot orders failed"))
        orders = response.json().get("results", [])
        for order in orders:
            self.env["sale.order"]._import_stockpilot_order(order, self)
        return

    def export_products(self):
        """
        Button action to create batch export job for products to Stockpilot.
        (Stub implementation)
        """
        products = self.env["product.product"].search([])
        batch = self.env["queue.job.batch"].get_new_batch("Import products")
        for product in products:
            self.env["stockpilot.product.product"].with_context(
                job_batch=batch
            ).with_delay().create(
                {
                    "stockpilot_configuration_id": self.id,
                    "product_product_id": product.id,
                }
            )
        self.ensure_one()
        return
