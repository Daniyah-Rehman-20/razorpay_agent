"""Generate Vapi import JSON from current config; does not create a call or send data."""
import json
import os
from pathlib import Path
from app.config import Settings, ROOT
from app.models import MODELS


def export():
    s=Settings();s.validate()
    credential_id=os.getenv('VAPI_CREDENTIAL_ID','')
    if not credential_id or not s.public_base_url.startswith('https://'):
        raise SystemExit('Set VAPI_CREDENTIAL_ID to a saved Vapi credential and PUBLIC_BASE_URL to your HTTPS backend URL.')
    tools=json.loads((ROOT/'provider/tools.json').read_text())
    server={'url':s.public_base_url+'/webhooks/vapi','credentialId':credential_id}
    for tool in tools:
        tool['server']=server
    assistant={
        'name':'Riya - Fictional Autopay Recovery Demo',
        'firstMessage':'Hello, this is Riya, an automated AI assistant for a fictional {{company}} demo, not affiliated with {{company}}. Am I speaking with {{first_name}}?',
        'model':{'provider':'openai','model':os.getenv('VAPI_MODEL','gpt-4o-mini'),'temperature':0.2,
                 'messages':[{'role':'system','content':(ROOT/'provider/system-prompt.md').read_text()}],
                 'tools':tools+[{'type':'endCall'}]},
        'voice':{'provider':os.getenv('VAPI_VOICE_PROVIDER','vapi'),'voiceId':os.getenv('VAPI_VOICE_ID','Naina')},
        'server':server,'serverMessages':['tool-calls','end-of-call-report'],
        'maxDurationSeconds':240,'silenceTimeoutSeconds':10,
        'artifactPlan':{'recordingEnabled':True},
        'voicemailMessage':'Hello, this is a fictional demo message for {{first_name}}. Please check with the demo operator when convenient. Thank you.'}
    if assistant['voice']['provider']=='vapi':
        assistant['voice'].update({'version':2,'language':'auto'})
    directory=ROOT/'provider/generated';directory.mkdir(exist_ok=True)
    (directory/'assistant.json').write_text(json.dumps(assistant,indent=2))
    (directory/'tools.json').write_text(json.dumps(tools,indent=2))
    print('Generated provider/generated/assistant.json and tools.json. Review the voice/transcriber settings in Vapi before placing a call.')

if __name__=='__main__':
    export()
