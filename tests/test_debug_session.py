"""Behavioral regressions for recovery, argument enforcement and negotiation."""
import pytest
from test_gateway import configured, approve, tool
from test_gateway_transport import server, approve as approve_wire
from test_gateway_http import server as http_server, config as http_config
from driftguard.gateway import GateError, GuardStore
from driftguard.gateway_transport import ProtectedGateway, LEGACY, TransportError, DownstreamSession

@pytest.mark.parametrize('args',[{}, {'query':42}, {'query':'ok','extra':True}, {'query':None}])
def test_invalid_arguments_do_not_execute(args):
    with configured() as store:
        definition=tool(); definition['inputSchema'].update(required=['query'],additionalProperties=False)
        row=approve(store,definition); calls=[]
        with pytest.raises(GateError,match='approved input schema'):
            store.dispatch('local','search',args,lambda *a:calls.append(a),expected_hash=row['sha256'],expected_revision=row['revision'])
        assert calls==[]
        assert not any(e['event_type']=='call_completed' for e in store.events())

@pytest.mark.parametrize('schema',[{'$ref':'https://example.invalid/external'}, {'pattern':'(a+)+$'}, {'anyOf':[{}]}])
def test_unsupported_contract_never_executes(schema):
    with configured() as store:
        definition=tool();definition['inputSchema'].update(schema)
        row=approve(store,definition); calls=[]
        with pytest.raises(GateError,match='unsupported validation'):
            store.dispatch('local','search',{'query':'safe'},lambda *a:calls.append(a),expected_hash=row['sha256'],expected_revision=row['revision'])
        assert calls==[]

@pytest.mark.parametrize('dialect',['https://json-schema.org/draft/2020-12/schema','http://json-schema.org/draft-07/schema#'])
def test_valid_contract_dispatch_and_nested_validation(dialect):
    with configured() as store:
        definition=tool();definition['inputSchema']={'$schema':dialect,'type':'object','properties':{'rows':{'type':'array','maxItems':2,'items':{'type':'integer','minimum':1}}},'required':['rows']}
        row=approve(store,definition)
        kwargs=dict(expected_hash=row['sha256'],expected_revision=row['revision'])
        assert store.dispatch('local','search',{'rows':[1,2]},lambda n,a:a,**kwargs)=={'rows':[1,2]}
        for value in ([0],[1,2,3],['1']):
            with pytest.raises(GateError):store.dispatch('local','search',{'rows':value},lambda *a:pytest.fail('invalid data executed'),**kwargs)

@pytest.mark.parametrize('selected',['2025-06-18','2025-03-26'])
def test_actual_stdio_negotiated_identity_and_calls(server,selected):
    config,update,root=server; update(negotiatedVersion=selected)
    with GuardStore() as store:
        gateway=ProtectedGateway(config(LEGACY),store)
        try:
            assert gateway.identity.protocol_version==selected
            assert store.list_servers()[0]['protocol_version']==selected
            approve_wire(store)
            assert gateway.call('weather',{})['content'][0]['text']=='Sunny'
            downstream=DownstreamSession(gateway)
            result=downstream.handle({'jsonrpc':'2.0','id':1,'method':'initialize','params':{'protocolVersion':selected}})
            assert result['result']['protocolVersion']==selected
        finally:gateway.close()

def test_unknown_protocol_is_rejected(server):
    config,update,_=server;update(negotiatedVersion='2099-01-01')
    with GuardStore() as store:
        with pytest.raises(TransportError,match='negotiation'):ProtectedGateway(config(LEGACY),store)

def test_http_negotiated_version_used_on_subsequent_requests(tmp_path):
    with http_server() as (url,state),GuardStore(tmp_path/'state.sqlite3') as store:
        state['version']='2025-06-18'
        gateway=ProtectedGateway(http_config(url),store)
        try:
            assert gateway.identity.protocol_version=='2025-06-18'
            assert state['requests'][-1][1]['MCP-Protocol-Version']=='2025-06-18'
            row=store.get_tool('http-fixture','read_notes')
            store.approve('http-fixture','read_notes',expected_hash=row['sha256'],expected_revision=row['revision'])
            assert gateway.call('read_notes',{})['content'][0]['text']=='safe result'
        finally:gateway.close()
