# Copyright (C) 2025 WeSolved BV <https://wesolved.com>
# @author Miro Tasevski <miro.tasevski@wesolved.com>
# @author Insaf Amrani <insaf.amrani.boukhobza@wesolved.com>
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl).

import logging

import requests
from odoo import _, api, fields, models
from odoo.exceptions import UserError

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

    channel_mapping_ids = fields.One2many(
        "stockpilot.channel.mapping",
        "config_id",
        string="Channel Mappings",
    )

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

    active = fields.Boolean(
        string="Active",
        default=True,
    )

    _sql_constraints = [
        (
            "company_uniq",
            "unique(company_id)",
            "Only one configuration per company allowed!",
        ),
    ]

    def toggle_active(self):
        """Standard method name that works with Odoo's built-in archive/unarchive"""
        self.write({"active": not self.active})
        return True

    def toggle_active_view(self):
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
        """Prevent deletion of active configurations"""
        active_configs = self.filtered(lambda c: c.active)
        if active_configs:
            raise UserError(
                _("You cannot delete active configurations! Archive them first.")
            )
        return super().unlink()

    @api.model
    def _get_default_config(self):
        """Get or create default configuration for current company"""
        company_id = self.env.company.id
        config = self.search([("company_id", "=", company_id)], limit=1)
        if not config:
            config = self.create(
                {
                    "company_id": company_id,
                    "api_client_id": "f9e56e88-14e1-4fc0-8089-04aba8e6088b",
                    "api_client_secret": (
                        "4c2145b40980fd2005f80bf97776b6e63600587d0c0cbe404fade80027bb9a1f"
                    ),
                    "base_url": "https://api.stockpilot.dev",
                    "environment": "test",
                }
            )
        return config

    def _get_config_action(self):
        """Return action to open the configuration form"""
        config = self._get_default_config()
        return {
            "type": "ir.actions.act_window",
            "res_model": self._name,
            "view_mode": "form",
            "res_id": config.id,
            "target": "current",
            "context": {"form_view_initial_mode": "edit"},
        }

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
                "%s/inventory" % self.base_url.rstrip("/"),
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
        return self.search([("company_id", "=", company_id)], limit=1)

    def import_orders(self):
        """Button action to import orders from Stockpilot with detailed logging"""
        self.ensure_one()
        try:
            _logger.info("Starting order import from Stockpilot")

            # Get the sync model
            sync_model = self.env["stockpilot.sync"]

            # Execute the import
            result = sync_model.with_delay()._fetch_stockpilot_orders()

            if not result:
                _logger.error("Order import returned False/None - possible failure")

            _logger.info("Orders imported successfully")
        except Exception as e:
            _logger.error(_("Failed to import orders: %s") % str(e), exc_info=True)

    def import_stock(self):
        """Button action to import products from Stockpilot to Odoo without notifications"""
        self.ensure_one()
        try:
            # Get inventory model
            inventory_model = self.env["stockpilot.inventory"]

            # Execute the import
            result = (
                inventory_model.with_context(stockpilot_config=self)
                .with_delay()
                .import_stockpilot_products()
            )

            if isinstance(result, dict):
                success_count = result.get("created", 0) + result.get("updated", 0)
                fail_count = result.get("failed", 0)
                _logger.info(
                    "Import: %d products (%d created, %d updated, %d failed)",
                    success_count + fail_count,
                    result.get("created", 0),
                    result.get("updated", 0),
                    fail_count,
                )
            else:
                _logger.warning(
                    "Import completed with unexpected results: %s", str(result)
                )
                fail_count = 1

            return True

        except Exception as e:
            _logger.error("Product import failed: %s", str(e), exc_info=True)
            return False

    def export_products(self):
        """Button action to create batch export job for products to Stockpilot"""
        self.ensure_one()
        try:
            # Create a new batch export
            export_time = fields.Datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            batch_export_name = _("Batch Export - %s") % export_time
            batch_export = self.env["stockpilot.batch.export"].create(
                {
                    "name": batch_export_name,
                    "config_id": self.id,
                }
            )

            message = _("Created batch export job: %s") % batch_export.name
            _logger.info(message)

            # Start the batch export
            batch_export.action_start_export()

            return {
                "type": "ir.actions.client",
                "tag": "display_notification",
                "params": {
                    "title": _("Batch Export Started"),
                    "message": _(
                        "Batch export job created successfully. "
                        "Check the batch exports menu for progress."
                    ),
                    "type": "success",
                    "sticky": False,
                },
            }

        except Exception as e:
            error_message = _("Failed to create batch export: %s") % str(e)
            _logger.error(
                error_message,
                exc_info=True,
            )
            return {
                "type": "ir.actions.client",
                "tag": "display_notification",
                "params": {
                    "title": _("Error"),
                    "message": error_message,
                    "type": "danger",
                    "sticky": True,
                },
            }
