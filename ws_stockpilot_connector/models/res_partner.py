# In your partner model (e.g., `stockpilot_partner.py`)
from odoo import fields, models

class ResPartner(models.Model):
    _inherit = 'res.partner'

    stockpilot_customer_id = fields.Char(
        string='Stockpilot Customer ID',
        copy=False,
        help="Original customer ID from Stockpilot for sync",
    )
