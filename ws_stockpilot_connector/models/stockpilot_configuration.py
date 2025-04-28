from odoo import fields, models, api


class StockpilotConfiguration(models.Model):
    _name = 'stockpilot.configuration'
    _description = 'Stockpilot Configuration'

    api_client_id = fields.Char(string='API Client ID', default='f9e56e88-14e1-4fc0-8089-04aba8e6088b')
    api_client_secret = fields.Char(string='API Client Secret',
                                    default='4c2145b40980fd2005f80bf97776b6e63600587d0c0cbe404fade80027bb9a1f')
    base_url = fields.Char(string='Base URL', default='https://api.stockpilot.dev')
    environment = fields.Selection([
        ('test', 'Test'),
        ('production', 'Production'),
    ], string='Environment', default='test')
