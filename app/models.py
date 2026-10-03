from enum import Enum
from typing import Literal
from pydantic import BaseModel, ConfigDict, Field

class Outcome(str, Enum):
    RECOVERED='RECOVERED'
    LINK_SENT='LINK_SENT'
    PROMISE_TO_PAY='PROMISE_TO_PAY'
    RETRY_FAILED='RETRY_FAILED'
    ESCALATED='ESCALATED'
    DISPUTE='DISPUTE'
    CANCELLED_CLAIM='CANCELLED_CLAIM'
    VERIFICATION_FAILED='VERIFICATION_FAILED'
    WRONG_NUMBER='WRONG_NUMBER'
    NO_CONTACT='NO_CONTACT'
    VOICEMAIL='VOICEMAIL'
    DNC='DNC'
    NO_RESPONSE='NO_RESPONSE'
    DROPPED='DROPPED'
    TECH_ERROR='TECH_ERROR'

class CustomerRequest(BaseModel):
    model_config = ConfigDict(extra='forbid')
    customer_id: str = Field(pattern=r'^C\d{3}$')

class Verify(CustomerRequest):
    answer: str = Field(min_length=1, max_length=80)

class Consent(CustomerRequest):
    consent: Literal[True]

class Link(Consent):
    channel: Literal['sms'] = 'sms'

class Schedule(Consent):
    date: str = Field(max_length=10)

class Callback(CustomerRequest):
    time_window: str = Field(min_length=1, max_length=200)

class Escalate(CustomerRequest):
    reason: str = Field(min_length=1, max_length=300)

class Log(CustomerRequest):
    outcome: Outcome
    notes: str = Field(default='', max_length=500)

MODELS = {'verify_identity': Verify, 'get_payment_details': CustomerRequest,
          'retry_payment': Consent, 'send_payment_link': Link, 'schedule_retry': Schedule,
          'request_callback': Callback, 'escalate_to_human': Escalate,
          'mark_dnc': CustomerRequest, 'log_outcome': Log}
