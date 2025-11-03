# Copyright (C) 2025 WeSolved BV <https://wesolved.com>
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl).

from odoo import fields, models


class CountryWarehouse(models.Model):
    _name = "country.warehouse"

    country_id = fields.Many2one("res.country")
    warehouse_id = fields.Many2one("stock.warehouse")
    stockpilot_configuration_id = fields.Many2one("stockpilot.configuration")
