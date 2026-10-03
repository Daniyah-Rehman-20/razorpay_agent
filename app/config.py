import os
from dataclasses import dataclass, field
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()
ROOT = Path(__file__).resolve().parents[1]

@dataclass
class Settings:
    db_path: str = field(default_factory=lambda: os.getenv('DATABASE_PATH', str(ROOT / 'var/recovery.db')))
    webhook_secret: str = field(default_factory=lambda: os.getenv('WEBHOOK_SECRET', ''))
    admin_token: str = field(default_factory=lambda: os.getenv('ADMIN_TOKEN', ''))
    public_base_url: str = field(default_factory=lambda: os.getenv('PUBLIC_BASE_URL', 'http://127.0.0.1:8000').rstrip('/'))
    provider: str = field(default_factory=lambda: os.getenv('PROVIDER', 'mock'))
    provider_api_key: str = field(default_factory=lambda: os.getenv('PROVIDER_API_KEY', ''))
    provider_agent_id: str = field(default_factory=lambda: os.getenv('PROVIDER_AGENT_ID', ''))
    provider_phone_number_id: str = field(default_factory=lambda: os.getenv('PROVIDER_PHONE_NUMBER_ID', ''))
    allowed_numbers: set = field(default_factory=lambda: {x.strip() for x in os.getenv('ALLOWED_TEST_NUMBERS', '').split(',') if x.strip()})
    razorpay_key_id: str = field(default_factory=lambda: os.getenv('RAZORPAY_KEY_ID', ''))
    razorpay_key_secret: str = field(default_factory=lambda: os.getenv('RAZORPAY_KEY_SECRET', ''))
    razorpay_webhook_secret: str = field(default_factory=lambda: os.getenv('RAZORPAY_WEBHOOK_SECRET', ''))

    def validate(self):
        if len(self.webhook_secret) < 24 or len(self.admin_token) < 24:
            raise ValueError('Run python scripts/setup_local.py or set distinct ADMIN_TOKEN and WEBHOOK_SECRET of at least 24 characters.')
        if self.admin_token == self.webhook_secret:
            raise ValueError('Admin and webhook credentials must be different.')
        if self.provider not in {'mock', 'vapi'}:
            raise ValueError('PROVIDER must be mock or vapi')
        if self.razorpay_key_id and not self.razorpay_key_id.startswith('rzp_test_'):
            raise ValueError('Only Razorpay TEST keys are accepted.')
        if self.razorpay_key_id and not (self.razorpay_key_secret and self.razorpay_webhook_secret):
            raise ValueError('Test payment integration requires key and webhook secrets.')
