# Copyright (C) 2025 WeSolved BV <https://wesolved.com>
# @author Miro Tasevski <miro.tasevski@wesolved.com>
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl).
import requests

from odoo import fields, models, _
from odoo.exceptions import UserError



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
        if not self.base_url.startswith(('http://', 'https://')):
            raise UserError(_("Base URL must start with http:// or https://"))

    def _test_api_connectivity(self):
        """Connecting to Stockpilot API"""
        try:
            response = requests.get(
                f"{self.base_url.rstrip('/')}/inventory",
                headers={
                    'X-CLIENT-ID': self.api_client_id,
                    'X-CLIENT-SECRET': self.api_client_secret
                },
                params={'page': 1, 'page_size': 100},
                timeout=10
            )
            return response.status_code == 200, _("Connection successful") if response.status_code == 200 else _(
                "API returned status: %s") % response.status_code
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
                'type': 'ir.actions.client',
                'tag': 'display_notification',
                'params': {
                    'title': _('Success') if success else _('Failed'),
                    'message': message,
                    'type': 'success' if success else 'danger',
                    'sticky': not success,
                }
            }
        except UserError as e:
            return {
                'type': 'ir.actions.client',
                'tag': 'display_notification',
                'params': {
                    'title': _('Error'),
                    'message': str(e),
                    'type': 'danger',
                    'sticky': True,
                }
            }
