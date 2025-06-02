# Copyright (C) 2025 WeSolved BV <https://wesolved.com>
# @author Miro Tasevski <miro.tasevski@wesolved.com>
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl).

from odoo import fields, models


class ResPartner(models.Model):
    _inherit = "res.partner"

    stockpilot_customer_id = fields.Char(
        string="Stockpilot Customer ID",
        copy=False,
        help="Original customer ID from Stockpilot for sync",
    )
