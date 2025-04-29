# Copyright (C) 2025 WeSolved BV <https://wesolved.com>
# @author Miro Tasevski <miro.tasevski@wesolved.com>
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl).
import requests

from odoo import fields, models


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

    def test_connection(self):
        """Method to test Stockpilot API connection"""
        try:
            url = f"{self.base_url}/api/test_connection"
            headers = {
                "API-Client-ID": self.api_client_id,
                "API-Client-Secret": self.api_client_secret,
            }
            response = requests.get(url, headers=headers)

            return {
                "type": "ir.actions.client",
                "tag": "display_notification",
                "params": {
                    "title": "Success" if response.status_code == 200 else "Warning",
                    "message": (
                        "Connection successful!"
                        if response.status_code == 200
                        else "Failed to connect to Stockpilot API"
                    ),
                    "type": "success" if response.status_code == 200 else "warning",
                    "sticky": False,
                },
            }
        except Exception as e:
            return {
                "type": "ir.actions.client",
                "tag": "display_notification",
                "params": {
                    "title": "Error",
                    "message": f"Error: {str(e)}",
                    "type": "danger",
                    "sticky": True,
                },
            }
