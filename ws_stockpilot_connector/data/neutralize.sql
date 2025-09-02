-- Neutralize Stockpilot Configuration
UPDATE stockpilot_configuration
SET api_client_id = 'dummy_client_id_12345',
    api_client_secret = 'dummy_secret_abcdef67890',
    base_url = 'https://api.stockpilot.dev',
    environment = 'test';
