"""All Vapi-specific transport and webhook normalization live here."""
import json
from urllib.parse import urlparse
from uuid import uuid4
import httpx

VARIABLE_KEYS = {'customer_id','first_name','company','language','current_date'}

class Provider:
    def __init__(self, settings):
        self.settings = settings

    def start_call(self, customer_id, phone, variables):
        if set(variables) != VARIABLE_KEYS or variables['customer_id'] != customer_id:
            raise ValueError('Unexpected provider variables')
        s = self.settings
        if s.provider == 'mock':
            return 'mock-' + uuid4().hex
        if not all((s.provider_api_key,s.provider_agent_id,s.provider_phone_number_id)):
            raise ValueError('Vapi credentials, assistant ID and phone number ID are required')
        # Authentication belongs on the SAVED assistant/server, never call overrides.
        with httpx.Client(timeout=15) as client:
            response = client.post('https://api.vapi.ai/call', headers={'Authorization':f'Bearer {s.provider_api_key}'},json={
                'assistantId':s.provider_agent_id,'phoneNumberId':s.provider_phone_number_id,
                'customer':{'number':phone},'assistantOverrides':{'variableValues':variables}})
            response.raise_for_status()
            return response.json()['id']

    @staticmethod
    def parse_tools(body):
        message = body.get('message', {})
        call_id = message.get('call',{}).get('id')
        result=[]
        for tool in message.get('toolCallList',[]):
            f = tool.get('function') or tool
            args = f.get('arguments',f.get('parameters',{}))
            if isinstance(args,str):
                args=json.loads(args)
            result.append((tool['id'],f['name'],args))
        return call_id,result

    @staticmethod
    def parse_end(body):
        m = body.get('message',{})
        artifact=m.get('artifact') or {}
        reason=m.get('endedReason','')
        def safe_url(x):
            return x if isinstance(x,str) and urlparse(x).scheme=='https' and urlparse(x).netloc else None
        outcome='VOICEMAIL' if 'voicemail' in reason else ('NO_CONTACT' if reason in {'customer-did-not-answer','customer-busy'} else 'DROPPED')
        return {'provider_id':m.get('call',{}).get('id'), 'outcome':outcome,
                'duration':max(0,float(m.get('durationSeconds') or 0)),
                'cost':max(0,float(m.get('cost') or 0)),
                'transcript_url':safe_url(artifact.get('transcriptUrl')),
                'recording_url':safe_url(artifact.get('recordingUrl') or m.get('recordingUrl'))}
