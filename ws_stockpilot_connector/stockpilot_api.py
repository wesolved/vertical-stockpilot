import logging

import requests

from odoo import _
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)


class StockpilotApi:
    def __init__(self, client_id, client_secret, env="production"):
        self.client_id = client_id
        self.client_secret = client_secret
        if env == "production":
            self.base_url = "https://api.stockpilot.dev"
        else:
            self.base_url = "https://api.stockpilot.dev"
        self.headers = {
            "X-CLIENT-ID": self.client_id,
            "X-CLIENT-SECRET": self.client_secret,
        }

    def _execute_get_request(self, endpoint, params=False):
        """Execute get request towards Stockpilot"""
        if not params:
            params = {}

        response = requests.get(
            "%s/%s" % (self.base_url.rstrip("/"), endpoint),
            headers=self.headers,
            params=params,
            timeout=60,
        )

        return response

    def _execute_post_request(self, endpoint, data):
        """Execute post request towards Stockpilot"""
        try:
            response = requests.request(
                "POST",
                "%s/%s" % (self.base_url.rstrip("/"), endpoint),
                headers=self.headers,
                json=data,
                timeout=60,
            )
            response.raise_for_status()
            return response.json()
        except requests.exceptions.RequestException as e:
            error_msg = (
                f"Stockpilot API Error: {e.response.status_code} {e.response.reason}"
            )
            if e.response.text:
                error_msg += f"\n{e.response.text}"
            _logger.error(error_msg)
            raise UserError(_(error_msg))
        except Exception as e:
            _logger.exception("[Stockpilot] Unexpected error calling API")
            raise UserError(_("Unexpected error calling Stockpilot API: %s") % str(e))

    def _execute_put_request(self, endpoint, data):
        """Execute post request towards Stockpilot"""
        try:
            response = requests.request(
                "PUT",
                "%s/%s" % (self.base_url.rstrip("/"), endpoint),
                headers=self.headers,
                json=data,
                timeout=60,
            )
            response.raise_for_status()
            return response.json()
        except requests.exceptions.RequestException as e:
            error_msg = (
                f"Stockpilot API Error: {e.response.status_code} {e.response.reason}"
            )
            if e.response.text:
                error_msg += f"\n{e.response.text}"
            _logger.error(error_msg)
            raise UserError(_(error_msg))
        except Exception as e:
            _logger.exception("[Stockpilot] Unexpected error calling API")
            raise UserError(_("Unexpected error calling Stockpilot API: %s") % str(e))

    def _execute_patch_request(self, endpoint, data):
        """Execute post request towards Stockpilot"""
        try:
            response = requests.request(
                "PATCH",
                "%s/%s" % (self.base_url.rstrip("/"), endpoint),
                headers=self.headers,
                json=data,
                timeout=60,
            )
            response.raise_for_status()
            return response.json()
        except requests.exceptions.RequestException as e:
            error_msg = (
                f"Stockpilot API Error: {e.response.status_code} {e.response.reason}"
            )
            if e.response.text:
                error_msg += f"\n{e.response.text}"
            _logger.error(error_msg)
            raise UserError(_(error_msg))
        except Exception as e:
            _logger.exception("[Stockpilot] Unexpected error calling API")
            raise UserError(_("Unexpected error calling Stockpilot API: %s") % str(e))
